package org.example.saildroid.downloadcontract;
import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.os.*;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/** Internal real-I/O tests, including returned bytes; not an official CTS APK. */
public final class DownloadContractInstrumentation extends Instrumentation {
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static final byte[] PAYLOAD=new byte[65539];
    static {for(int i=0;i<PAYLOAD.length;i++)PAYLOAD[i]=(byte)((i*73+19)&255);}
    private static int status(DownloadManager manager,long id)throws Exception{
        try(Cursor cursor=manager.query(new DownloadManager.Query().setFilterById(id))){require(cursor!=null&&cursor.moveToFirst(),"Download row exists");return cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));}
    }
    private static void await(DownloadManager manager,long id,int wanted)throws Exception{
        long until=SystemClock.uptimeMillis()+7000;
        while(SystemClock.uptimeMillis()<until){int current=status(manager,id);if(current==wanted)return;if(current==DownloadManager.STATUS_FAILED&&wanted!=current)throw new AssertionError("Actual download failed");Thread.sleep(15);}
        throw new AssertionError("Download status deadline");
    }
    private void runChecks()throws Exception{
        Context context=getTargetContext();final ServerSocket listener=new ServerSocket(0,3,InetAddress.getByName("127.0.0.1"));listener.setSoTimeout(7000);
        final AtomicReference<Throwable> failure=new AtomicReference<Throwable>();final CountDownLatch cancelAccepted=new CountDownLatch(1),releaseCancel=new CountDownLatch(1);
        Thread server=new Thread(new Runnable(){public void run(){
            try {
                for(int request=0;request<3;request++)try(Socket peer=listener.accept()){
                    peer.setSoTimeout(4000);BufferedReader input=new BufferedReader(new InputStreamReader(peer.getInputStream(),"US-ASCII"));String first=input.readLine();require(first!=null,"Actual HTTP request line");String line;while((line=input.readLine())!=null&&!line.isEmpty()){}
                    OutputStream output=peer.getOutputStream();
                    if(first.contains(" /ok ")){output.write(("HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: "+PAYLOAD.length+"\r\nConnection: close\r\n\r\n").getBytes("US-ASCII"));output.write(PAYLOAD);output.flush();}
                    else if(first.contains(" /missing ")){output.write("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".getBytes("US-ASCII"));output.flush();}
                    else if(first.contains(" /cancel ")){cancelAccepted.countDown();releaseCancel.await(6,TimeUnit.SECONDS);}
                    else throw new AssertionError("Unexpected HTTP path");
                }
            }catch(Throwable error){failure.set(error);}
        }});server.setDaemon(true);server.start();
        DownloadManager manager=(DownloadManager)context.getSystemService(Context.DOWNLOAD_SERVICE);ArrayList<Long> ids=new ArrayList<Long>();
        final Set<Long> completed=Collections.synchronizedSet(new HashSet<Long>());
        BroadcastReceiver receiver=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent intent){completed.add(intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID,-1));}};
        context.registerReceiver(receiver,new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE));
        String base="http://127.0.0.1:"+listener.getLocalPort();
        try {
            long id=manager.enqueue(new DownloadManager.Request(Uri.parse(base+"/ok")));ids.add(id);await(manager,id,DownloadManager.STATUS_SUCCESSFUL);
            try(Cursor cursor=manager.query(new DownloadManager.Query().setFilterById(id))){require(cursor.moveToFirst(),"Successful metadata exists");require(cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))==PAYLOAD.length,"Actual total bytes");require(cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))==PAYLOAD.length,"Actual completed bytes");}
            ByteArrayOutputStream downloaded=new ByteArrayOutputStream();
            try(InputStream input=new ParcelFileDescriptor.AutoCloseInputStream(manager.openDownloadedFile(id))){byte[] buffer=new byte[8192];int count;while((count=input.read(buffer))!=-1)downloaded.write(buffer,0,count);}
            require(Arrays.equals(downloaded.toByteArray(),PAYLOAD),"Actual downloaded binary bytes match response");
            long deadline=SystemClock.uptimeMillis()+3000;while(!completed.contains(id)&&SystemClock.uptimeMillis()<deadline)Thread.sleep(10);require(completed.contains(id),"Completion broadcast matches actual ID");
            long missing=manager.enqueue(new DownloadManager.Request(Uri.parse(base+"/missing")));ids.add(missing);await(manager,missing,DownloadManager.STATUS_FAILED);
            try(Cursor cursor=manager.query(new DownloadManager.Query().setFilterById(missing))){require(cursor.moveToFirst(),"Failed metadata exists");require(cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON))==404,"Actual HTTP 404 reason");}
            boolean rejected=false;try{manager.enqueue(new DownloadManager.Request(Uri.parse(base+"/ok")).setDestinationUri(Uri.fromFile(new File(context.getFilesDir(),"unsupported-destination"))));}catch(UnsupportedOperationException expected){rejected=true;}require(rejected,"Unsupported destination rejected before IO");require(!new File(context.getFilesDir(),"unsupported-destination").exists(),"No unauthorized destination file");
            long cancelled=manager.enqueue(new DownloadManager.Request(Uri.parse(base+"/cancel")));ids.add(cancelled);require(cancelAccepted.await(4,TimeUnit.SECONDS),"Real cancellation request accepted");require(manager.remove(cancelled)==1,"Active download removed");releaseCancel.countDown();
            try(Cursor cursor=manager.query(new DownloadManager.Query().setFilterById(cancelled))){require(!cursor.moveToFirst(),"Cancelled row stays absent");}
            require(manager.remove(id,missing)==2,"Completed/failed rows removed");ids.clear();
            try{manager.openDownloadedFile(id);throw new AssertionError("Deleted file remains accessible");}catch(FileNotFoundException expected){}
            server.join(5000);require(!server.isAlive(),"Actual HTTP server ended");if(failure.get()!=null)throw new AssertionError(failure.get());
            System.err.println("DOWNLOAD_CONTRACT=PASS|binary_bytes=65539|metadata=actual|http404=failed|cancel=removed|broadcast=matched|unsupported_destination=rejected|deleted_file=inaccessible");
        }finally{releaseCancel.countDown();for(long id:ids)try{manager.remove(id);}catch(Exception ignored){}context.unregisterReceiver(receiver);listener.close();}
    }
    @Override public void onCreate(Bundle arguments){super.onCreate(arguments);start();}
    @Override public void onStart(){
        Bundle event=new Bundle();event.putString("class",getClass().getName());event.putString("test","realDownloadLifecycle");event.putInt("numtests",1);sendStatus(1,event);Bundle result=new Bundle();
        try{runChecks();sendStatus(0,event);result.putString("stream","OK (1 test)\n");finish(-1,result);}
        catch(Throwable failure){event.putString("stack",android.util.Log.getStackTraceString(failure));sendStatus(-2,event);result.putString("stream","FAILURES!!! Tests run: 1, Failures: 1\n");result.putString("shortMsg",failure.toString());finish(-1,result);}
    }
}
