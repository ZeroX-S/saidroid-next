package org.example.saildroid.media;
import android.app.Activity;import android.os.Bundle;import android.os.Handler;import android.graphics.SurfaceTexture;import android.view.*;import android.widget.*;import android.media.MediaPlayer;
public final class MediaActivity extends Activity implements TextureView.SurfaceTextureListener {
 MediaPlayer player;Surface surface;int errors=0,prepared=0;Handler handler=new Handler();TextView status;
 void log(String s){System.err.println("MEDIA_ERROR_PROBE="+s);status.setText(s);}
 public void onCreate(Bundle b){super.onCreate(b);LinearLayout box=new LinearLayout(this);box.setOrientation(1);status=new TextView(this);box.addView(status,new LinearLayout.LayoutParams(-1,200));TextureView view=new TextureView(this);view.setSurfaceTextureListener(this);box.addView(view,new LinearLayout.LayoutParams(-1,1200));setContentView(box);log("created");}
 void attempt(){try{player=new MediaPlayer();player.setSurface(surface);player.setOnPreparedListener(mp->{prepared++;log("unexpected_prepared");});player.setOnErrorListener((mp,a,b)->{log("error|attempt="+errors+"|what="+a+"|extra="+b);errors++;mp.release();player=null;if(errors<2)handler.postDelayed(this::attempt,200);else log("passed|errors="+errors+"|prepared="+prepared);return true;});player.setDataSource(errors==0?"http://127.0.0.1:9312/missing":"https://127.0.0.1:9443/clip.webm",java.util.Collections.singletonMap("X-SaiDroid-Media","312"));player.prepareAsync();log("requested|attempt="+errors);}catch(Throwable e){log("exception|"+e);e.printStackTrace();}}
 public void onSurfaceTextureAvailable(SurfaceTexture t,int w,int h){surface=new Surface(t);attempt();}
 public boolean onSurfaceTextureDestroyed(SurfaceTexture t){if(player!=null)player.release();if(surface!=null)surface.release();return true;}
 public void onSurfaceTextureSizeChanged(SurfaceTexture t,int w,int h){}public void onSurfaceTextureUpdated(SurfaceTexture t){}
}
