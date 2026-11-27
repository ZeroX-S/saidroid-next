package org.example.saildroid.cameragl;
import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
public final class ReviewActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        byte[] bytes=MainActivity.picture;
        Bitmap image=BitmapFactory.decodeByteArray(bytes,0,bytes.length);
        if(image==null||image.getWidth()!=640||image.getHeight()!=480) throw new AssertionError("Captured JPEG dimensions differ");
        FrameLayout root=new FrameLayout(this);
        ImageView preview=new ImageView(this);preview.setImageBitmap(image);preview.setScaleType(ImageView.ScaleType.FIT_CENTER);
        FrameLayout.LayoutParams content=new FrameLayout.LayoutParams(-1,-1);content.bottomMargin=220;root.addView(preview,content);
        Button back=new Button(this);back.setText("Discard and return to real preview");
        FrameLayout.LayoutParams controls=new FrameLayout.LayoutParams(-1,220);controls.gravity=Gravity.BOTTOM;root.addView(back,controls);
        back.setOnClickListener(unused->{System.err.println("SD_CAMERA_GL=discard_touch");finish();});
        setContentView(root);
        System.err.println("SD_CAMERA_GL=review_ready|jpeg=640x480");
    }
}
