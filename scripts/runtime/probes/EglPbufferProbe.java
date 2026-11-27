import android.opengl.*;
import android.graphics.Bitmap;
import java.nio.*;

/** Ordinary-user API29 JNI/backend test; no window, input, account, or system changes. */
public final class EglPbufferProbe {
    static void check(boolean value,String step){if(!value)throw new AssertionError(step+"|egl_error=0x"+Integer.toHexString(EGL14.eglGetError()));}
    public static void main(String[] args){try{
        if(Boolean.getBoolean("saidroid.eglProbeDiagnostics")){
            System.load(System.getProperty("saidroid.bridge.library"));
            SdBridge.installExitDiagnostics();
        }
        SdRuntime.initializeFramework(false);
        EGLDisplay display=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        check(display!=EGL14.EGL_NO_DISPLAY,"getDisplay");int[] version=new int[2];
        check(EGL14.eglInitialize(display,version,0,version,1),"initialize");
        EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
        check(EGL14.eglChooseConfig(display,new int[]{EGL14.EGL_SURFACE_TYPE,EGL14.EGL_PBUFFER_BIT,EGL14.EGL_RENDERABLE_TYPE,EGL14.EGL_OPENGL_ES2_BIT,EGL14.EGL_RED_SIZE,8,EGL14.EGL_GREEN_SIZE,8,EGL14.EGL_BLUE_SIZE,8,EGL14.EGL_ALPHA_SIZE,8,EGL14.EGL_NONE},0,configs,0,1,count,0)&&count[0]>0,"chooseConfig");
        EGLContext context=EGL14.eglCreateContext(display,configs[0],EGL14.EGL_NO_CONTEXT,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,2,EGL14.EGL_NONE},0);
        check(context!=EGL14.EGL_NO_CONTEXT,"createContext");
        EGLSurface surface=EGL14.eglCreatePbufferSurface(display,configs[0],new int[]{EGL14.EGL_WIDTH,2,EGL14.EGL_HEIGHT,2,EGL14.EGL_NONE},0);
        check(surface!=EGL14.EGL_NO_SURFACE,"createPbuffer");check(EGL14.eglMakeCurrent(display,surface,surface,context),"makeCurrent");
        int vertex=GLES20.glCreateShader(GLES20.GL_VERTEX_SHADER),fragment=GLES20.glCreateShader(GLES20.GL_FRAGMENT_SHADER);int[] ok=new int[1];
        GLES20.glShaderSource(vertex,"attribute vec4 position; void main(){gl_Position=position;}");GLES20.glCompileShader(vertex);GLES20.glGetShaderiv(vertex,GLES20.GL_COMPILE_STATUS,ok,0);if(ok[0]!=1)throw new AssertionError(GLES20.glGetShaderInfoLog(vertex));
        GLES20.glShaderSource(fragment,"precision mediump float; void main(){gl_FragColor=vec4(1.0,0.0,0.0,1.0);}");GLES20.glCompileShader(fragment);GLES20.glGetShaderiv(fragment,GLES20.GL_COMPILE_STATUS,ok,0);if(ok[0]!=1)throw new AssertionError(GLES20.glGetShaderInfoLog(fragment));
        int program=GLES20.glCreateProgram();GLES20.glAttachShader(program,vertex);GLES20.glAttachShader(program,fragment);GLES20.glLinkProgram(program);GLES20.glGetProgramiv(program,GLES20.GL_LINK_STATUS,ok,0);if(ok[0]!=1)throw new AssertionError(GLES20.glGetProgramInfoLog(program));
        int[] texture=new int[1];GLES20.glGenTextures(1,texture,0);GLES20.glBindTexture(GLES20.GL_TEXTURE_2D,texture[0]);Bitmap bitmap=Bitmap.createBitmap(2,2,Bitmap.Config.ARGB_8888);bitmap.eraseColor(0xff0000ff);GLUtils.texImage2D(GLES20.GL_TEXTURE_2D,0,bitmap,0);bitmap.recycle();if(GLES20.glGetError()!=GLES20.GL_NO_ERROR)throw new AssertionError("Bitmap upload");
        GLES20.glClearColor(1,0,0,1);GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);ByteBuffer pixel=ByteBuffer.allocateDirect(4);GLES20.glReadPixels(0,0,1,1,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,pixel);if(GLES20.glGetError()!=GLES20.GL_NO_ERROR||(pixel.get(0)&255)!=255||(pixel.get(1)&255)!=0||(pixel.get(2)&255)!=0||(pixel.get(3)&255)!=255)throw new AssertionError("Readback color");
        String renderer=GLES20.glGetString(GLES20.GL_RENDERER);
        GLES20.glDeleteTextures(1,texture,0);GLES20.glDeleteProgram(program);GLES20.glDeleteShader(vertex);GLES20.glDeleteShader(fragment);
        EGL14.eglMakeCurrent(display,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);check(EGL14.eglDestroySurface(display,surface),"destroySurface");check(EGL14.eglDestroyContext(display,context),"destroyContext");check(EGL14.eglTerminate(display),"terminate");
        System.err.println("API29_EGL=PASS|version="+version[0]+"."+version[1]+"|renderer="+renderer+"|pbuffer=2x2|shader=compiled-linked|Bitmap_upload=pass|readback=255,0,0,255|uid="+android.os.Process.myUid());Runtime.getRuntime().halt(0);
    }catch(Throwable error){error.printStackTrace();System.err.println("API29_EGL=failed");Runtime.getRuntime().halt(9);}}
}
