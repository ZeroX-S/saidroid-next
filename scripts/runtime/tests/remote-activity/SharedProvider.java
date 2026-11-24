package org.example.saildroid.remoteactivity;

import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Process;

/** Default-process provider: a local substitute in :tool cannot satisfy it. */
public class SharedProvider extends ContentProvider {
    public static int calls;
    @Override public boolean onCreate(){return true;}
    @Override public Bundle call(String method,String arg,Bundle extras){
        if(!"roundtrip".equals(method))throw new IllegalArgumentException("Unknown provider method");
        Bundle result=new Bundle();result.putInt("pid",Process.myPid());result.putBoolean("parentVisited",ParentActivity.visited);result.putInt("calls",++calls);return result;
    }
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String order){throw new UnsupportedOperationException();}
    @Override public String getType(Uri uri){return null;}
    @Override public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
    @Override public int delete(Uri uri,String selection,String[] args){throw new UnsupportedOperationException();}
    @Override public int update(Uri uri,ContentValues values,String selection,String[] args){throw new UnsupportedOperationException();}
}
