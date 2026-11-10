import android.app.*;
import android.content.pm.ParceledListSlice;
import android.os.*;
import android.service.notification.StatusBarNotification;
import java.io.*;
import java.lang.reflect.*;
import java.nio.channels.FileLock;
import java.util.*;

/** Private channel metadata and explicit disabled delivery until a host notifier exists. */
public final class SdNotificationPolicy implements InvocationHandler {
    private static final SdNotificationPolicy instance=new SdNotificationPolicy();
    private final Binder binder=new Binder();private final INotificationManager service;
    private SdNotificationPolicy(){service=(INotificationManager)Proxy.newProxyInstance(INotificationManager.class.getClassLoader(),new Class<?>[]{INotificationManager.class},this);binder.attachInterface(service,"android.app.INotificationManager");}
    public static IBinder binder(){return instance.binder;}
    private static void own(Object name){if(!SdApkPackage.NAME.equals(name))throw new SecurityException("Notification package differs");}
    private static void user(Object user){if((Integer)user!=android.os.Process.myUid()/100000)throw new SecurityException("Notification user differs");}
    private static void uid(Object uid){if((Integer)uid!=android.os.Process.myUid())throw new SecurityException("Notification UID differs");}
    private static File root(){File root=new File(SdApkPackage.applicationInfo().dataDir,"files/saildroid-notification-policy");if(!root.isDirectory()&&!root.mkdirs())throw new IllegalStateException("Notification policy storage unavailable");return root;}
    private static File entry(String kind,String id)throws Exception{
        if(id==null||id.isEmpty())throw new IllegalArgumentException("Notification channel ID required");
        byte[] hash=java.security.MessageDigest.getInstance("SHA-256").digest(id.getBytes("UTF-8"));StringBuilder key=new StringBuilder();for(byte b:hash)key.append(String.format(java.util.Locale.US,"%02x",b&255));
        File directory=new File(root(),kind);if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Notification metadata directory unavailable");return new File(directory,key+".parcel");
    }
    private static <T> T read(File file,Parcelable.Creator<T> creator)throws Exception{
        if(!file.isFile())return null;byte[] bytes=java.nio.file.Files.readAllBytes(file.toPath());Parcel parcel=Parcel.obtain();try{parcel.unmarshall(bytes,0,bytes.length);parcel.setDataPosition(0);return creator.createFromParcel(parcel);}finally{parcel.recycle();}
    }
    private static void write(File file,Parcelable value)throws Exception{
        Parcel parcel=Parcel.obtain();File temporary=File.createTempFile("pending-",".parcel",file.getParentFile());
        try{value.writeToParcel(parcel,0);try(FileOutputStream output=new FileOutputStream(temporary)){output.write(parcel.marshall());output.getFD().sync();}if(!temporary.renameTo(file))throw new IOException("Cannot commit notification metadata");}finally{parcel.recycle();temporary.delete();}
    }
    private static <T> List<T> list(String kind,Parcelable.Creator<T> creator)throws Exception{
        ArrayList<T> result=new ArrayList<T>();File[] files=new File(root(),kind).listFiles();if(files!=null)for(File file:files)if(file.getName().matches("[0-9a-f]{64}\\.parcel"))result.add(read(file,creator));return result;
    }
    @Override public synchronized Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
        String name=method.getName();if(name.equals("asBinder"))return binder;if(name.equals("toString"))return "SailDroid notification delivery disabled";if(name.equals("hashCode"))return System.identityHashCode(proxy);if(name.equals("equals"))return proxy==args[0];
        if(name.equals("areNotificationsEnabled")||name.equals("getPackageImportance")){own(args[0]);return name.equals("areNotificationsEnabled")?Boolean.FALSE:Integer.valueOf(NotificationManager.IMPORTANCE_NONE);}
        if(name.equals("areNotificationsEnabledForPackage")){own(args[0]);uid(args[1]);return false;}
        if(name.equals("getPrivateNotificationsAllowed"))return false; // No Android notification content can be displayed by this backend.
        if(name.equals("getActiveNotifications")){own(args[0]);return new StatusBarNotification[0];}
        if(name.equals("getAppActiveNotifications")){own(args[0]);user(args[1]);return new ParceledListSlice<StatusBarNotification>(Collections.<StatusBarNotification>emptyList());}
        if(name.equals("enqueueNotificationWithTag")){
            own(args[0]);own(args[1]);user(args[5]);
            if(!(args[4] instanceof Notification))throw new IllegalArgumentException("Notification required");
            // The same policy already reports notifications disabled and an
            // empty active list. Disabled posts do not reach any host notifier.
            System.err.println("SDNOTIFICATION=delivery_blocked|reason=host-policy-disabled|posted=false");return null;
        }
        if(name.equals("cancelNotificationWithTag")||name.equals("cancelAllNotifications")){own(args[0]);return null;/* No posted notifications exist. */}
        if(name.equals("createNotificationChannels")||name.equals("createNotificationChannelGroups")||name.equals("getNotificationChannel")||name.equals("getNotificationChannelForPackage")||name.equals("getNotificationChannels")||name.equals("getNotificationChannelGroups")||name.equals("getNotificationChannelGroup")||name.equals("deleteNotificationChannel")||name.equals("deleteNotificationChannelGroup")){
            own(args[0]);File lockFile=new File(root(),"metadata.lock");
            try(RandomAccessFile mutex=new RandomAccessFile(lockFile,"rw");FileLock held=mutex.getChannel().lock()){
                if(name.equals("createNotificationChannels")){
                    for(Object value:((ParceledListSlice<?>)args[1]).getList()){
                        NotificationChannel incoming=(NotificationChannel)value;File file=entry("channels",incoming.getId());NotificationChannel previous=read(file,NotificationChannel.CREATOR);
                        if(previous!=null){previous.setName(incoming.getName());previous.setDescription(incoming.getDescription());incoming=previous;}write(file,incoming);
                    }return null;
                }
                if(name.equals("createNotificationChannelGroups")){for(Object value:((ParceledListSlice<?>)args[1]).getList()){NotificationChannelGroup group=(NotificationChannelGroup)value;write(entry("groups",group.getId()),group);}return null;}
                if(name.equals("getNotificationChannel")){user(args[1]);own(args[2]);return read(entry("channels",(String)args[3]),NotificationChannel.CREATOR);}
                if(name.equals("getNotificationChannelForPackage")){uid(args[1]);return read(entry("channels",(String)args[2]),NotificationChannel.CREATOR);}
                if(name.equals("getNotificationChannels")){own(args[1]);user(args[2]);return new ParceledListSlice<NotificationChannel>(list("channels",NotificationChannel.CREATOR));}
                if(name.equals("getNotificationChannelGroups"))return new ParceledListSlice<NotificationChannelGroup>(list("groups",NotificationChannelGroup.CREATOR));
                if(name.equals("getNotificationChannelGroup"))return read(entry("groups",(String)args[1]),NotificationChannelGroup.CREATOR);
                if(name.equals("deleteNotificationChannel")){File file=entry("channels",(String)args[1]);if(file.exists()&&!file.delete())throw new IOException("Cannot delete notification channel");return null;}
                String id=(String)args[1];File file=entry("groups",id);if(file.exists()&&!file.delete())throw new IOException("Cannot delete notification group");
                for(NotificationChannel channel:list("channels",NotificationChannel.CREATOR))if(id.equals(channel.getGroup())){File channelFile=entry("channels",channel.getId());if(!channelFile.delete())throw new IOException("Cannot delete grouped notification channel");}return null;
            }
        }
        throw SdRuntimeDiagnostics.unsupported("Notification policy",method);
    }
}
