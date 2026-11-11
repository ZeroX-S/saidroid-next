package org.example.saildroid.api28media;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.ServiceInfo;
import android.graphics.SurfaceTexture;
import android.hardware.Camera;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import android.opengl.GLES11Ext;
import android.opengl.GLES20;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Message;
import android.os.Messenger;
import android.widget.TextView;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

/** Secondary activity binding a default-process service and consuming camera frames. */
public final class CameraProbeActivity extends Activity {
    private final CountDownLatch identityReady = new CountDownLatch(1);
    private volatile String serviceProcess;
    private boolean bound;
    private final Messenger reply = new Messenger(new Handler(message -> {
        serviceProcess = message.getData().getString("process");
        identityReady.countDown();
        return true;
    }));
    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            Message request = Message.obtain();
            request.replyTo = reply;
            try { new Messenger(binder).send(request); }
            catch (android.os.RemoteException failure) { throw new AssertionError(failure); }
        }
        @Override public void onServiceDisconnected(ComponentName name) {}
    };

    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        TextView status = new TextView(this);
        status.setText("Checking camera preview and service process");
        setContentView(status);
        new Thread(() -> {
            try {
                ComponentName name = new ComponentName(this, ProcessIdentityService.class);
                ServiceInfo info = getPackageManager().getServiceInfo(name, 0);
                System.err.println("API28_CAMERA=service_metadata|process=" + info.processName
                        + "|application=" + info.applicationInfo.processName);
                require(info.applicationInfo.processName.equals(info.processName), "Default service process missing");
                runOnUiThread(() -> {
                    bound = bindService(new Intent().setComponent(name), connection, BIND_AUTO_CREATE);
                    require(bound, "Default process service bind rejected");
                });
                require(identityReady.await(40, TimeUnit.SECONDS), "Service identity timeout");
                require(info.processName.equals(serviceProcess), "Service ran in the camera process");
                require(!android.app.Application.getProcessName().equals(serviceProcess), "Child process identity differs");
                System.err.println("API28_CAMERA=service_identity|process=" + serviceProcess);
                verifyPreview();
                System.err.println("API28_CAMERA=passed|photos_taken=0");
                runOnUiThread(() -> { setResult(RESULT_OK); finish(); });
            } catch (Throwable failure) {
                failure.printStackTrace();
                System.err.println("API28_CAMERA=failed|type=" + failure.getClass().getName());
                runOnUiThread(() -> { setResult(RESULT_CANCELED); finish(); });
            }
        }, "Camera preview regression").start();
    }

    private static void verifyPreview() throws Exception {
        EGLDisplay display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        int[] version = new int[2];
        require(EGL14.eglInitialize(display, version, 0, version, 1), "EGL initialization failed");
        EGLContext context = EGL14.EGL_NO_CONTEXT;
        EGLSurface surface = EGL14.EGL_NO_SURFACE;
        HandlerThread events = new HandlerThread("Preview frame events");
        events.start();
        try {
            EGLConfig[] configs = new EGLConfig[1];
            int[] count = new int[1];
            int[] attributes = {EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT,
                    EGL14.EGL_RENDERABLE_TYPE, EGL14.EGL_OPENGL_ES2_BIT, EGL14.EGL_NONE};
            require(EGL14.eglChooseConfig(display, attributes, 0, configs, 0, 1, count, 0)
                    && count[0] > 0, "EGL config missing");
            context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
                    new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE}, 0);
            require(context != EGL14.EGL_NO_CONTEXT, "EGL context failed");
            surface = EGL14.eglCreatePbufferSurface(display, configs[0],
                    new int[]{EGL14.EGL_WIDTH, 16, EGL14.EGL_HEIGHT, 16, EGL14.EGL_NONE}, 0);
            require(surface != EGL14.EGL_NO_SURFACE && EGL14.eglMakeCurrent(display, surface, surface, context),
                    "EGL pbuffer failed");
            int cameras = Camera.getNumberOfCameras();
            require(cameras > 0, "Camera inventory missing");
            boolean[] covered = new boolean[2];
            int[] selected = {-1, -1};
            for (int id = 0; id < cameras; id++) {
                Camera.CameraInfo info = new Camera.CameraInfo();
                Camera.getCameraInfo(id, info);
                require(info.facing >= 0 && info.facing < covered.length, "Unknown camera facing");
                require(selected[info.facing] < 0, "Auxiliary camera exposed through Camera1");
                selected[info.facing] = id;
            }
            require(selected[0] >= 0 && selected[1] >= 0, "Front/back inventory missing");
            int[] names = new int[1];
            GLES20.glGenTextures(1, names, 0);
            GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, names[0]);
            SurfaceTexture texture = new SurfaceTexture(names[0]);
            Semaphore available = new Semaphore(0);
            texture.setOnFrameAvailableListener(value -> available.release(), new Handler(events.getLooper()));
            try {
                for (int id : new int[]{selected[0], selected[1], selected[0]}) {
                    Camera.CameraInfo info = new Camera.CameraInfo();
                    Camera.getCameraInfo(id, info);
                    available.drainPermits();
                    Camera camera = null;
                    boolean started = false;
                    long began = android.os.SystemClock.uptimeMillis();
                    try {
                        camera = Camera.open(id);
                        Camera.Parameters parameters = camera.getParameters();
                        Camera.Size size = parameters.getSupportedPreviewSizes().get(0);
                        parameters.setPreviewSize(size.width, size.height);
                        camera.setParameters(parameters);
                        texture.setDefaultBufferSize(size.width, size.height);
                        camera.setPreviewTexture(texture);
                        camera.setDisplayOrientation(90);
                        camera.startPreview();
                        started = true;
                        long timestamp = 0;
                        for (int frame = 0; frame < 12; frame++) {
                            require(available.tryAcquire(10, TimeUnit.SECONDS), "Preview frame timeout, camera " + id);
                            available.drainPermits();
                            texture.updateTexImage();
                            require(texture.getTimestamp() > timestamp, "Camera frame timestamp did not advance");
                            timestamp = texture.getTimestamp();
                            if (frame == 0) System.err.println("API28_CAMERA=first_frame|id=" + id
                                    + "|elapsed_ms=" + (android.os.SystemClock.uptimeMillis() - began));
                            require(GLES20.glGetError() == GLES20.GL_NO_ERROR, "Camera texture GL error");
                        }
                        System.err.println("API28_CAMERA=preview|id=" + id + "|frames=12|size="
                                + size.width + "x" + size.height + "|orientation=90|timestamp=" + timestamp);
                        covered[info.facing] = true;
                        // Leave frames pending across release and reconnect. The
                        // consumer must receive notifications from the next camera.
                        Thread.sleep(500);
                    } finally {
                        long releasing = android.os.SystemClock.uptimeMillis();
                        if (camera != null) {
                            try { if (started) camera.stopPreview(); }
                            finally { camera.release(); }
                        }
                        require(android.os.SystemClock.uptimeMillis() - releasing < 2000,
                                "Camera release blocked while preview was unconsumed");
                    }
                }
            } finally {
                texture.release();
                GLES20.glDeleteTextures(1, names, 0);
            }
            require(covered[Camera.CameraInfo.CAMERA_FACING_BACK] && covered[Camera.CameraInfo.CAMERA_FACING_FRONT],
                    "Front/back preview coverage missing");
        } finally {
            EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT);
            if (surface != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display, surface);
            if (context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display, context);
            EGL14.eglTerminate(display);
            EGL14.eglReleaseThread();
            events.quitSafely();
            events.join();
        }
    }

    @Override public void onDestroy() {
        if (bound) unbindService(connection);
        super.onDestroy();
    }
}
