package org.example.saildroid.api28media;

import android.app.Activity;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.hardware.Camera;
import android.media.MediaDataSource;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.MediaStore;
import android.widget.TextView;
import java.io.File;
import java.io.FileInputStream;
import java.io.RandomAccessFile;

/** Normal APK regression for host media and bounded metadata retrieval. */
public final class MediaMetadataActivity extends Activity {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView status = new TextView(this);
        status.setText("Checking media metadata");
        setContentView(status);
        new Thread(() -> {
            try {
                verifyMedia();
                runOnUiThread(() -> startActivityForResult(new android.content.Intent(this, CameraProbeActivity.class), 42));
            } catch (Throwable failure) {
                failure.printStackTrace();
                System.err.println("API28_MEDIA=failed|type=" + failure.getClass().getName());
            }
        }, "Media metadata regression").start();
    }

    private void verifyMedia() throws Exception {
        int images = 0;
        try (Cursor rows = getContentResolver().query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                new String[]{"_id", "_data", "_size", "width", "height"}, null, null, null)) {
            require(rows != null, "Images cursor missing");
            while (rows.moveToNext()) {
                File file = new File(rows.getString(1));
                require(file.isFile() && file.length() == rows.getLong(2), "Image file size differs");
                BitmapFactory.Options bounds = new BitmapFactory.Options();
                bounds.inJustDecodeBounds = true;
                BitmapFactory.decodeFile(file.getPath(), bounds);
                require(bounds.outWidth > 0 && bounds.outHeight > 0, "Image cannot decode");
                images++;
            }
        }
        int videos = 0;
        try (Cursor rows = getContentResolver().query(MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
                new String[]{"_id", "_data"}, null, null, null)) {
            require(rows != null, "Videos cursor missing");
            while (rows.moveToNext()) {
                long began = android.os.SystemClock.elapsedRealtime();
                MediaMetadataRetriever retriever = new MediaMetadataRetriever();
                require(android.os.SystemClock.elapsedRealtime() - began < 1000, "Retriever setup blocked");
                try {
                    retriever.setDataSource(rows.getString(1));
                    int width = Integer.parseInt(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH));
                    int height = Integer.parseInt(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT));
                    require(width > 0 && height > 0, "Video dimensions missing");
                    require(Long.parseLong(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)) > 0, "Video duration missing");
                    Bitmap frame = retriever.getScaledFrameAtTime(0, MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 160, 120);
                    require(frame != null && frame.getWidth() > 0 && frame.getWidth() <= 160
                            && frame.getHeight() > 0 && frame.getHeight() <= 120, "Video thumbnail missing");
                    require(Math.abs((long) frame.getWidth() * height - (long) frame.getHeight() * width)
                            <= Math.max(width, height), "Video thumbnail aspect ratio differs");
                    frame.recycle();
                    Uri item = Uri.withAppendedPath(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, rows.getString(0));
                    retriever.setDataSource(this, item);
                    require(Integer.toString(width).equals(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)), "Content URI dimensions differ");
                    try (FileInputStream input = new FileInputStream(rows.getString(1))) {
                        retriever.setDataSource(input.getFD(), 0, input.getChannel().size());
                        require(Integer.toString(height).equals(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)), "Descriptor dimensions differ");
                        boolean rejected = false;
                        try { retriever.setDataSource(input.getFD(), -1, input.getChannel().size()); }
                        catch (IllegalArgumentException expected) { rejected = true; }
                        require(rejected, "Negative descriptor offset accepted");
                    }
                    final RandomAccessFile source = new RandomAccessFile(rows.getString(1), "r");
                    retriever.setDataSource(new MediaDataSource() {
                        @Override public int readAt(long position, byte[] bytes, int offset, int size) throws java.io.IOException {
                            source.seek(position);
                            return source.read(bytes, offset, size);
                        }
                        @Override public long getSize() throws java.io.IOException { return source.length(); }
                        @Override public void close() throws java.io.IOException { source.close(); }
                    });
                    require(Integer.toString(width).equals(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)), "Callback dimensions differ");
                    require(retriever.extractMetadata(9999) == null, "Unknown metadata fabricated");
                    System.err.println("API28_MEDIA=video|width=" + width + "|height=" + height
                            + "|elapsed_ms=" + (android.os.SystemClock.elapsedRealtime() - began));
                } finally { retriever.release(); retriever.release(); }
                videos++;
            }
        }
        require(images > 0 && videos > 0, "Host media absent");
        System.err.println("API28_MEDIA=inventory|images=" + images + "|videos=" + videos);
    }

    @Override public void onActivityResult(int request, int code, android.content.Intent data) {
        super.onActivityResult(request, code, data);
        require(request == 42 && code == RESULT_OK, "Remote camera Activity did not return");
        System.err.println("API28_MEDIA=passed|photos_taken=0|separate_camera_process=true");
    }
}
