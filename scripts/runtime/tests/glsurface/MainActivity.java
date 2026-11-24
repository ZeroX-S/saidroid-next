package org.example.saildroid.glsurface;

import android.app.Activity;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import android.os.Bundle;
import android.widget.Button;
import android.widget.FrameLayout;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** Exercises GLSurfaceView's EGL10 JNI and a real GLES2 window queue. */
public final class MainActivity extends Activity implements GLSurfaceView.Renderer {
    private GLSurfaceView surface;
    private volatile boolean touched;
    private boolean initialLogged, touchLogged;
    private int width, height;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        FrameLayout root = new FrameLayout(this);
        surface = new GLSurfaceView(this);
        surface.setEGLContextClientVersion(2);
        surface.setRenderer(this);
        surface.setRenderMode(GLSurfaceView.RENDERMODE_WHEN_DIRTY);
        FrameLayout.LayoutParams content = new FrameLayout.LayoutParams(-1, -1);
        content.bottomMargin = 220;
        root.addView(surface, content);
        Button button = new Button(this);
        button.setText("Change real GLES2 frame");
        FrameLayout.LayoutParams controls = new FrameLayout.LayoutParams(-1, 220);
        controls.gravity = android.view.Gravity.BOTTOM;
        root.addView(button, controls);
        button.setOnClickListener(view -> {
            touched = true;
            surface.requestRender();
            System.err.println("SD_GLSURFACE_PROBE=physical_touch_handled");
        });
        setContentView(root);
    }

    @Override public void onSurfaceCreated(GL10 unused, EGLConfig config) {
        String version = GLES20.glGetString(GLES20.GL_VERSION);
        if (version == null || !version.contains("OpenGL ES"))
            throw new AssertionError("No real GLES context");
        System.err.println("SD_GLSURFACE_PROBE=context_ready|version=" + version);
    }

    @Override public void onSurfaceChanged(GL10 unused, int w, int h) {
        width = w; height = h;
        GLES20.glViewport(0, 0, w, h);
    }

    @Override public void onDrawFrame(GL10 unused) {
        boolean changed = touched;
        GLES20.glClearColor(changed ? 0.12f : 0.16f, changed ? 0.32f : 0.64f,
                changed ? 0.82f : 0.38f, 1);
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
        if (GLES20.glGetError() != GLES20.GL_NO_ERROR)
            throw new AssertionError("GLES2 clear failed");
        if (!changed && !initialLogged) {
            initialLogged = true;
            System.err.println("SD_GLSURFACE_PROBE=initial_frame|size=" + width + "x" + height);
        } else if (changed && !touchLogged) {
            touchLogged = true;
            System.err.println("SD_GLSURFACE_PROBE=touch_frame|size=" + width + "x" + height);
        }
    }

    @Override public void onPause() { surface.onPause(); super.onPause(); }
    @Override public void onResume() { super.onResume(); surface.onResume(); }
}
