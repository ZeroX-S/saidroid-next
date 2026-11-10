package org.example.saildroid.videothumbnail;

import android.app.Activity;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.media.MediaMetadataRetriever;
import android.media.ThumbnailUtils;
import android.os.Bundle;
import android.os.SystemClock;
import android.provider.MediaStore;
import android.widget.TextView;
import java.io.File;
import java.io.BufferedReader;
import java.io.FileReader;
import java.io.FileOutputStream;
import java.io.InputStream;

/** Exercises the video-grid thumbnail entry point with a synthetic MP4 asset. */
public final class VideoThumbnailActivity extends Activity {
    private int failures;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView status = new TextView(this);
        status.setText("Checking synthetic video thumbnails");
        setContentView(status);
        new Thread(() -> {
            try {
                verifyOomPolicy();
                verifyThumbnails();
                verifyInventory();
                if (failures != 0) throw new AssertionError("Thumbnail failures " + failures);
                System.err.println("VIDEO_THUMBNAIL=passed");
            } catch (Throwable failure) {
                failure.printStackTrace();
                System.err.println("VIDEO_THUMBNAIL=failed|type=" + failure.getClass().getName());
            }
        }, "Video thumbnail regression").start();
    }

    private void verifyOomPolicy() throws Exception {
        try (BufferedReader reader = new BufferedReader(new FileReader("/proc/self/oom_score_adj"))) {
            int adjustment = Integer.parseInt(reader.readLine());
            System.err.println("VIDEO_THUMBNAIL=oom-policy|adjustment=" + adjustment);
            if (adjustment != 0) throw new AssertionError("Application OOM protection inherited");
        }
    }

    private void verifyThumbnails() throws Exception {
        File video = new File(getFilesDir(), "synthetic.mp4");
        try (InputStream input = getAssets().open("clip.mp4");
             FileOutputStream output = new FileOutputStream(video)) {
            byte[] buffer = new byte[16384];
            int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        }
        try {
            MediaMetadataRetriever retriever = new MediaMetadataRetriever();
            try {
                retriever.setDataSource(video.getPath());
                inspect("default-frame", retriever.getFrameAtTime(), 1280, 960);
                inspect("zero-frame", retriever.getFrameAtTime(0,
                        MediaMetadataRetriever.OPTION_CLOSEST_SYNC), 1280, 960);
                inspect("scaled-frame", retriever.getScaledFrameAtTime(0,
                        MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 160, 120), 160, 120);
                inspect("negative-scaled-frame", retriever.getScaledFrameAtTime(-1,
                        MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 160, 120), 160, 120);
            } finally {
                retriever.release();
            }
            long began = SystemClock.elapsedRealtime();
            Bitmap thumbnail = ThumbnailUtils.createVideoThumbnail(video.getPath(),
                    MediaStore.Video.Thumbnails.MINI_KIND);
            inspect("mini-thumbnail", thumbnail, 512, 512);
            System.err.println("VIDEO_THUMBNAIL=mini-time|elapsed_ms="
                    + (SystemClock.elapsedRealtime() - began));
            thumbnail = ThumbnailUtils.createVideoThumbnail(video.getPath(),
                    MediaStore.Video.Thumbnails.MICRO_KIND);
            inspect("micro-thumbnail", thumbnail, 96, 96);
            thumbnail = ThumbnailUtils.createVideoThumbnail(video.getPath(),
                    MediaStore.Video.Thumbnails.MINI_KIND);
            Bitmap grid = ThumbnailUtils.extractThumbnail(thumbnail, 180, 135);
            if (thumbnail != null && thumbnail != grid) thumbnail.recycle();
            inspect("grid-thumbnail", grid, 180, 135);
        } finally {
            if (!video.delete()) throw new AssertionError("Synthetic video cleanup failed");
        }
    }

    private void verifyInventory() throws Exception {
        try (Cursor rows = getContentResolver().query(MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
                new String[]{"_id", "_data", "width", "height", "duration", "orientation"},
                null, null, null)) {
            if (rows == null) throw new AssertionError("Video inventory unavailable");
            int count = 0;
            while (rows.moveToNext()) {
                MediaMetadataRetriever retriever = new MediaMetadataRetriever();
                try {
                    retriever.setDataSource(rows.getString(1));
                    int width = Integer.parseInt(retriever.extractMetadata(
                            MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH));
                    int height = Integer.parseInt(retriever.extractMetadata(
                            MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT));
                    long duration = Long.parseLong(retriever.extractMetadata(
                            MediaMetadataRetriever.METADATA_KEY_DURATION));
                    int rotation = Integer.parseInt(retriever.extractMetadata(
                            MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION));
                    boolean valid = width > 0 && height > 0 && duration > 0
                            && rows.getInt(2) == width && rows.getInt(3) == height
                            && rows.getLong(4) == duration && rows.getInt(5) == rotation;
                    if (!valid) failures++;
                    count++;
                    System.err.println("VIDEO_THUMBNAIL=inventory|index=" + count
                            + "|width=" + rows.getInt(2) + "|height=" + rows.getInt(3)
                            + "|duration_ms=" + rows.getLong(4) + "|valid=" + valid);
                } finally {
                    retriever.release();
                }
            }
            if (count == 0) throw new AssertionError("Valid video fixture input missing");
        }
    }

    private void inspect(String stage, Bitmap bitmap, int maxWidth, int maxHeight) {
        if (bitmap == null) {
            failures++;
            System.err.println("VIDEO_THUMBNAIL=result|stage=" + stage + "|present=false");
            return;
        }
        try {
            int width = bitmap.getWidth();
            int height = bitmap.getHeight();
            int first = bitmap.getPixel(width / 4, height / 2);
            int second = bitmap.getPixel(width * 3 / 4, height / 2);
            boolean valid = width > 0 && height > 0 && width <= maxWidth
                    && height <= maxHeight && first != second;
            if (!valid) failures++;
            System.err.println("VIDEO_THUMBNAIL=result|stage=" + stage + "|present=true"
                    + "|width=" + width + "|height=" + height + "|varied="
                    + (first != second) + "|valid=" + valid);
        } finally {
            bitmap.recycle();
        }
    }
}
