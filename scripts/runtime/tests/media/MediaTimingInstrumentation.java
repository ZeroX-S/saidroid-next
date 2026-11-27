package org.example.saildroid.mediatiming;

import android.app.Instrumentation;
import android.os.Bundle;

/** Internal timing diagnostic. Its results never count as original CTS tests. */
public final class MediaTimingInstrumentation extends Instrumentation {
    private static native int runNative();
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle event=new Bundle();
        event.putString("class",getClass().getName());event.putString("test","privateNdkTiming");
        sendStatus(1,event);
        Bundle result=new Bundle();
        try {
            System.loadLibrary("mediatiming_jni");
            int code=runNative();
            if(code!=0)throw new IllegalStateException("Native timing diagnostic failed: "+code);
            sendStatus(0,event);
            result.putString("stream","Private NDK timing diagnostic completed; not a CTS result");
            finish(-1,result);
        } catch(Throwable failure) {
            event.putString("stack",android.util.Log.getStackTraceString(failure));
            sendStatus(-2,event);result.putString("shortMsg",failure.toString());finish(0,result);
        }
    }
}
