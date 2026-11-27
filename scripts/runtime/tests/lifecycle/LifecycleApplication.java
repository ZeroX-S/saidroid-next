package org.example.saildroid.lifecycle;

import android.app.Activity;
import android.app.Application;
import android.os.Bundle;

public final class LifecycleApplication extends Application implements Application.ActivityLifecycleCallbacks {
    static int started,resumed,violations;
    static boolean transition,childSeen;
    static int returns;
    @Override public void onCreate(){super.onCreate();registerActivityLifecycleCallbacks(this);}
    static void require(boolean condition,String reason){if(!condition){violations++;System.err.println("LIFECYCLE=violation|reason="+reason);}}
    private static void event(Activity a,String name){System.err.println("LIFECYCLE=callback|activity="+a.getClass().getSimpleName()+"|event="+name+"|started="+started+"|resumed="+resumed);}
    public void onActivityCreated(Activity a,Bundle state){if(a instanceof ChildActivity){childSeen=true;require(resumed==0,"outgoing-not-paused-before-child-created");}event(a,"create");}
    public void onActivityStarted(Activity a){started++;event(a,"start");}
    public void onActivityResumed(Activity a){resumed++;require(resumed==1,"multiple-resumed-activities");event(a,"resume");}
    public void onActivityPaused(Activity a){resumed--;require(resumed>=0,"negative-resumed-count");event(a,"pause");}
    public void onActivityStopped(Activity a){started--;if(transition)require(started>0,"in-app-transition-looked-like-background");event(a,"stop");}
    public void onActivitySaveInstanceState(Activity a,Bundle state){}
    public void onActivityDestroyed(Activity a){event(a,"destroy");}
}
