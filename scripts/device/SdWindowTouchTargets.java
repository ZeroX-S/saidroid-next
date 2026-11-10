import android.view.View;
import android.view.WindowManager;

/** Touch hit testing is independent of the window that owns keyboard focus. */
final class SdWindowTouchTargets {
    private SdWindowTouchTargets() {}

    static boolean accepts(int visibility, int flags, int left, int top, int right, int bottom,
                           float x, float y) {
        if (visibility != View.VISIBLE || (flags & WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE) != 0)
            return false;
        // Android treats NOT_FOCUSABLE as NOT_TOUCH_MODAL for pointer dispatch.
        boolean modal = (flags & (WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL)) == 0;
        return modal || (x >= left && x < right && y >= top && y < bottom);
    }
}
