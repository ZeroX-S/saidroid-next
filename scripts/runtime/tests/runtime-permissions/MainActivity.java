package org.example.saildroid.permissions;
import android.app.*;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.os.*;
import android.provider.MediaStore;
import android.widget.*;
public final class MainActivity extends Activity {
 private static final String READ="android.permission.READ_EXTERNAL_STORAGE";
 private static final String UNKNOWN="org.example.saildroid.permissions.UNDECLARED";
 private int attempts;private TextView status;
 @Override public void onCreate(Bundle state){super.onCreate(state);Button button=new Button(this);status=button;setContentView(button);
  boolean granted=checkSelfPermission(READ)==PackageManager.PERMISSION_GRANTED;
  if(checkSelfPermission(UNKNOWN)!=PackageManager.PERMISSION_DENIED||shouldShowRequestPermissionRationale(UNKNOWN))throw new AssertionError("Undeclared permission mismatch");
  if(checkSelfPermission("android.permission.INTERNET")!=PackageManager.PERMISSION_GRANTED)throw new AssertionError("Normal permission lost");
  System.err.println("SDPERMISSION_PROBE=initial|granted="+granted+"|rationale="+shouldShowRequestPermissionRationale(READ));
  if(granted){verifyMedia();status.setText("Persisted permission passed");System.err.println("SDPERMISSION_PROBE=persistence_passed");return;}
  if(shouldShowRequestPermissionRationale(READ))throw new AssertionError("Fresh rationale should be false");
  button.setText("Request photos");button.setOnClickListener(v->{attempts++;requestPermissions(new String[]{READ,UNKNOWN},70+attempts);});
 }
 @Override public void onRequestPermissionsResult(int code,String[] names,int[] results){super.onRequestPermissionsResult(code,names,results);
  if(code!=70+attempts||names.length!=2||!names[0].equals(READ)||!names[1].equals(UNKNOWN)||results.length!=2||results[1]!=PackageManager.PERMISSION_DENIED)throw new AssertionError("Permission callback differs");
  if(attempts==1){if(results[0]!=PackageManager.PERMISSION_DENIED||!shouldShowRequestPermissionRationale(READ)||checkSelfPermission(READ)!=PackageManager.PERMISSION_DENIED)throw new AssertionError("Denial state differs");status.setText("Denied; request again");System.err.println("SDPERMISSION_PROBE=denial_passed|rationale=true");}
  else if(attempts==2){if(results[0]!=PackageManager.PERMISSION_GRANTED||checkSelfPermission(READ)!=PackageManager.PERMISSION_GRANTED||shouldShowRequestPermissionRationale(READ))throw new AssertionError("Grant state differs");verifyMedia();status.setText("Permission flow passed");System.err.println("SDPERMISSION_PROBE=flow_passed|callback_count=2");}
  else throw new AssertionError("Unexpected repeated callback");
 }
 private void verifyMedia(){try(Cursor c=getContentResolver().query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,new String[]{"_id","_data","width","height"},"_size > ?",new String[]{"0"},"date_modified DESC")){if(c==null)throw new AssertionError("Media cursor missing");if(c.moveToFirst())try(java.io.InputStream input=getContentResolver().openInputStream(android.content.ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,c.getLong(0)))){if(input.read()<0)throw new AssertionError("Real media bytes missing");}catch(java.io.IOException e){throw new AssertionError(e);}System.err.println("SDPERMISSION_PROBE=media_passed|rows="+c.getCount());}}
}
