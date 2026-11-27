package org.example.saildroid.cameragl;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.SurfaceTexture;
import android.hardware.Camera;
import android.opengl.GLES11Ext;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import android.os.Bundle;
import android.widget.Button;
import android.widget.FrameLayout;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** Real Camera -> SurfaceTexture -> GLES -> JPEG Activity -> preview return. */
public final class MainActivity extends Activity implements GLSurfaceView.Renderer {
    static byte[] picture;
    private GLSurfaceView view;
    private Camera camera;
    private SurfaceTexture texture;
    private boolean resumed, permission, capturing;
    private int generation, program, name, width, height;
    private volatile int rendered;
    private boolean visiblePixels;
    private final ByteBuffer sample = ByteBuffer.allocateDirect(8 * 8 * 4);
    private final FloatBuffer vertices = ByteBuffer.allocateDirect(16 * 4)
            .order(ByteOrder.nativeOrder()).asFloatBuffer();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        permission = checkSelfPermission("android.permission.CAMERA") == PackageManager.PERMISSION_GRANTED;
        vertices.put(new float[]{-1,-1,0,1, 1,-1,1,1, -1,1,0,0, 1,1,1,0}).position(0);
        view = new GLSurfaceView(this);
        view.setEGLContextClientVersion(2);
        view.setRenderer(this);
        view.setRenderMode(GLSurfaceView.RENDERMODE_WHEN_DIRTY);
        FrameLayout root = new FrameLayout(this);
        FrameLayout.LayoutParams image = new FrameLayout.LayoutParams(-1, -1);
        image.bottomMargin = 220;
        root.addView(view, image);
        Button shutter = new Button(this);
        shutter.setText("Capture real photo; review without saving");
        FrameLayout.LayoutParams controls = new FrameLayout.LayoutParams(-1, 220);
        controls.gravity = android.view.Gravity.BOTTOM;
        root.addView(shutter, controls);
        shutter.setOnClickListener(unused -> {
            if (camera == null || rendered < 30 || capturing) throw new AssertionError("Preview not ready");
            capturing = true;
            System.err.println("SD_CAMERA_GL=shutter_touch|generation=" + generation);
            camera.takePicture(null, null, (bytes, source) -> {
                if (bytes == null || bytes.length < 100 || bytes[0] != (byte)0xff || bytes[1] != (byte)0xd8)
                    throw new AssertionError("Missing physical JPEG");
                picture = bytes;
                System.err.println("SD_CAMERA_GL=jpeg|bytes=" + bytes.length + "|generation=" + generation);
                startActivity(new Intent(this, ReviewActivity.class));
            });
        });
        setContentView(root);
        if (!permission) requestPermissions(new String[]{"android.permission.CAMERA"}, 81);
    }

    @Override public void onRequestPermissionsResult(int code, String[] names, int[] grants) {
        if (code != 81 || grants.length != 1 || grants[0] != PackageManager.PERMISSION_GRANTED)
            throw new AssertionError("Camera permission denied");
        permission = true;
        startCamera();
    }

    private void startCamera() {
        if (!resumed || !permission || texture == null || camera != null) return;
        try {
            int cameraId=0;
            for(int id=0;id<Camera.getNumberOfCameras();id++){Camera.CameraInfo info=new Camera.CameraInfo();Camera.getCameraInfo(id,info);if(info.facing==Camera.CameraInfo.CAMERA_FACING_FRONT){cameraId=id;break;}}
            camera = Camera.open(cameraId);
            System.err.println("SD_CAMERA_GL=physical_camera|id="+cameraId+"|prefer=front");
            Camera.Parameters parameters = camera.getParameters();
            parameters.setPreviewSize(640, 480);
            parameters.setPictureSize(640, 480);
            camera.setParameters(parameters);
            camera.setPreviewTexture(texture);
            camera.setErrorCallback((error, source) -> { throw new AssertionError("Camera error " + error); });
            final int[] samples={0};
            camera.setPreviewCallbackWithBuffer((bytes,source)->{
                if(!resumed||camera!=source)return;
                if(++samples[0]%30==0){int maximum=0;long sum=0;int count=0;for(int i=0;i<640*480;i+=37){int value=bytes[i]&255;maximum=Math.max(maximum,value);sum+=value;count++;}System.err.println("SD_CAMERA_GL=physical_luma|frame="+samples[0]+"|maximum="+maximum+"|mean="+sum/count);}
                source.addCallbackBuffer(bytes);
            });
            camera.addCallbackBuffer(new byte[460800]);camera.addCallbackBuffer(new byte[460800]);
            camera.startPreview();
            capturing = false;
            System.err.println("SD_CAMERA_GL=preview_started|generation=" + generation);
        } catch (java.io.IOException failure) { throw new AssertionError(failure); }
    }

    @Override public void onResume() {
        super.onResume();
        resumed = true;
        view.onResume();
    }

    @Override public void onPause() {
        resumed = false;
        if (camera != null) {
            camera.setPreviewCallbackWithBuffer(null);
            camera.stopPreview(); camera.release(); camera = null;
        }
        view.onPause();
        if (texture != null) { texture.release(); texture = null; }
        System.err.println("SD_CAMERA_GL=paused_released|generation=" + generation);
        super.onPause();
    }

    private int shader(int type, String source) {
        int shader = GLES20.glCreateShader(type);
        GLES20.glShaderSource(shader, source); GLES20.glCompileShader(shader);
        int[] status = new int[1]; GLES20.glGetShaderiv(shader, GLES20.GL_COMPILE_STATUS, status, 0);
        if (status[0] == 0) throw new AssertionError(GLES20.glGetShaderInfoLog(shader));
        return shader;
    }

    @Override public void onSurfaceCreated(GL10 unused, EGLConfig config) {
        generation++; rendered = 0; visiblePixels = false;
        int[] names = new int[1]; GLES20.glGenTextures(1, names, 0); name = names[0];
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, name);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE);
        int vertex = shader(GLES20.GL_VERTEX_SHADER, "attribute vec2 p; attribute vec2 t; varying vec2 uv; void main(){gl_Position=vec4(p,0.,1.);uv=t;}");
        int fragment = shader(GLES20.GL_FRAGMENT_SHADER, "#extension GL_OES_EGL_image_external : require\nprecision mediump float; varying vec2 uv; uniform samplerExternalOES image; void main(){gl_FragColor=texture2D(image,uv);}");
        program = GLES20.glCreateProgram(); GLES20.glAttachShader(program, vertex); GLES20.glAttachShader(program, fragment); GLES20.glLinkProgram(program);
        int[] linked = new int[1]; GLES20.glGetProgramiv(program, GLES20.GL_LINK_STATUS, linked, 0);
        if (linked[0] == 0) throw new AssertionError(GLES20.glGetProgramInfoLog(program));
        GLES20.glDeleteShader(vertex); GLES20.glDeleteShader(fragment);
        texture = new SurfaceTexture(name);
        texture.setOnFrameAvailableListener(value -> view.requestRender());
        runOnUiThread(() -> startCamera());
    }

    @Override public void onSurfaceChanged(GL10 unused, int w, int h) { width=w; height=h; }
    @Override public void onDrawFrame(GL10 unused) {
        if (texture == null) return;
        texture.updateTexImage();
        GLES20.glViewport(0,0,width,height);
        if(rendered==0){
            GLES20.glClearColor(1,0,1,1); GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);sample.clear();
            GLES20.glReadPixels(width/2,height/2,8,8,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,sample);
            int error=GLES20.glGetError();int r=sample.get(0)&255,g=sample.get(1)&255,b=sample.get(2)&255;
            System.err.println("SD_CAMERA_GL=readback_control|generation="+generation+"|size="+width+"x"+height+"|rgb="+r+","+g+","+b+"|error="+error);
            if(error!=0||r<240||g>10||b<240)throw new AssertionError("GLES readback control failed");
        }
        GLES20.glUseProgram(program);
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0);
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, name);
        GLES20.glUniform1i(GLES20.glGetUniformLocation(program,"image"),0);
        int p=GLES20.glGetAttribLocation(program,"p"),t=GLES20.glGetAttribLocation(program,"t");
        vertices.position(0); GLES20.glVertexAttribPointer(p,2,GLES20.GL_FLOAT,false,16,vertices);
        vertices.position(2); GLES20.glVertexAttribPointer(t,2,GLES20.GL_FLOAT,false,16,vertices);
        GLES20.glEnableVertexAttribArray(p); GLES20.glEnableVertexAttribArray(t);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP,0,4);
        if (GLES20.glGetError()!=GLES20.GL_NO_ERROR) throw new AssertionError("Real camera GLES draw failed");
        if (++rendered==30) System.err.println("SD_CAMERA_GL=preview_rendered|generation="+generation+"|frames=30");
        // Fixture-only output verification. Production preview still performs
        // no GPU readback. Wait for the real camera's exposure to settle.
        if (!visiblePixels && rendered >= 30 && rendered % 15 == 0) {
            int maximum=0, minimum=255, brightSamples=0;
            for(int sy=1;sy<=5;sy++)for(int sx=1;sx<=5;sx++){
                sample.clear();GLES20.glReadPixels(width*sx/6,height*sy/6,8,8,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,sample);
                for(int i=0;i<sample.capacity();i++)if(i%4!=3){int value=sample.get(i)&255;maximum=Math.max(maximum,value);minimum=Math.min(minimum,value);if(value>40)brightSamples++;}
            }
            System.err.println("SD_CAMERA_GL=readback_sample|generation="+generation+"|maximum="+maximum+"|minimum="+minimum+"|error="+GLES20.glGetError());
            if(maximum>40&&maximum-minimum>16&&brightSamples>32){visiblePixels=true;System.err.println("SD_CAMERA_GL=preview_pixels|generation="+generation+"|minimum="+minimum+"|maximum="+maximum+"|frames="+rendered+"|bright_samples="+brightSamples);}
        }
    }
}
