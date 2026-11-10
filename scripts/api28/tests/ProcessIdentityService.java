package org.example.saildroid.api28media;

import android.app.Application;
import android.app.Service;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Message;
import android.os.Messenger;

/** Replies from the manifest's default application process through kernel Binder. */
public final class ProcessIdentityService extends Service {
    private final Messenger endpoint = new Messenger(new Handler(request -> {
        Message response = Message.obtain();
        Bundle data = new Bundle();
        data.putString("process", Application.getProcessName());
        response.setData(data);
        try { request.replyTo.send(response); }
        catch (android.os.RemoteException failure) { throw new AssertionError(failure); }
        return true;
    }));

    @Override public IBinder onBind(Intent intent) { return endpoint.getBinder(); }
}
