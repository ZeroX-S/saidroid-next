import android.content.Context;
import android.net.Uri;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.view.MotionEvent;
import android.view.KeyEvent;
import android.view.inputmethod.BaseInputConnection;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.ExtractedText;
import android.view.inputmethod.ExtractedTextRequest;
import android.view.inputmethod.InputMethodManager;
import android.text.InputType;
import org.json.JSONObject;
import android.view.View;
import android.webkit.*;
import android.webkit.WebViewProvider.ViewDelegate;
import android.webkit.WebViewProvider.ScrollDelegate;
import java.lang.reflect.*;
import java.util.*;

/**
 * API29 WebView provider using an isolated host Qt/WPE process. Pixel and event
 * traffic is asynchronous and bounded; the host never creates a visible window.
 * An absent or failed renderer produces an error callback and a diagnostic page.
 * See native/webview/qt-helper/UPSTREAM.md for verified scope and current gaps.
 */
public final class SdWebViewProvider {

    /**
     * Custom {@code onReceivedError} code for "this build has no renderer at all".
     *
     * <p>It is stable, negative and never emitted by a working WebView, so a client
     * can tell the two states apart without matching strings:
     * <ul>
     *   <li>{@code onPageStarted} fired and this code has NOT arrived yet ⇒ <b>loading</b>
     *       (progress stays 0; the placeholder page shows the loading state);</li>
     *   <li>this code arrived ⇒ <b>permanently unrenderable</b>; the load is over and
     *       {@code onPageFinished} will never fire for it.</li>
     * </ul>
     */
    public static final int ERROR_NO_RENDERER = -1001;

    /** Render phases drawn by the provider delegate. */
    static final int PHASE_IDLE = 0;
    static final int PHASE_LOADING = 1;
    static final int PHASE_ERROR_NO_RENDERER = 2;
    static final int PHASE_READY = 3;

    /** Diagnostic shown on screen and in callbacks. Keep in sync with the design doc. */
    static final String RENDERER_STATE = "WebView renderer unavailable (WPE bridge not connected)";
    static final String ERROR_DETAIL = "SailDroid: no WebView rendering engine in this build;"
            + "page content, JavaScript and networking are not executed. See docs/SD-WEBVIEW-DESIGN.md.";


    // ---------------------------------------------------------- evidence colours
    //
    // IRON RULE for every static field of this class: it must be a *literal*
    // (int/String) or a plain-Java object. `SdWebViewProvider.<clinit>` runs in the
    // binder broker too, and that process has no graphics natives: a single
    // `new Paint()` here killed the broker with
    //   UnsatisfiedLinkError: android.graphics.Paint.nInit  -> System.exit(12)
    // and took QQ plus every other launch down with it. Hence the colours are
    // written as ARGB literals instead of Color.rgb(...): even loading
    // android.graphics.Color from <clinit> is needless risk in a graphics-less
    // process. Guard: native/webview/tools/check-clinit-safety.py (runs in the
    // javac wrapper, so it cannot regress silently).
    //
    // The two placeholder states must be distinguishable by a *screenshot*, byte for
    // byte, without OCR and without string matching: the whole canvas is filled with
    // one solid colour per state, so an image check can assert on the modal colour.
    //
    //   idle    bg #10131A  band #455A64  marker #9E9E9E
    //   loading bg #1B2A49  band #2E86DE  marker #00C2A8
    //   error   bg #4A1D1D  band #E74C3C  marker #F1C40F
    //
    // The bottom 12 px bar carries `marker`: a full-width, exact-colour strip that
    // survives JPEG-ish noise in the middle of the frame, so a checker can look at
    // one row and say "this is the placeholder, and this is which state".
    static final int BG_IDLE = 0xFF10131A;
    static final int BG_LOADING = 0xFF1B2A49;
    static final int BG_ERROR = 0xFF4A1D1D;
    static final int BAND_IDLE = 0xFF455A64;
    static final int BAND_LOADING = 0xFF2E86DE;
    static final int BAND_ERROR = 0xFFE74C3C;
    static final int MARKER_IDLE = 0xFF9E9E9E;
    static final int MARKER_LOADING = 0xFF00C2A8;
    static final int MARKER_ERROR = 0xFFF1C40F;
    static final int TEXT_TITLE = 0xFFFFFFFF;
    static final int TEXT_BODY = 0xFFDEE2EA;
    static final int TEXT_MUTED = 0xFF8C94A2;

    static String hex(int argb) { return String.format("#%06X", argb & 0xFFFFFF); }

    /** Minimum {@code WebResourceError} the API23 {@code onReceivedError} overload needs. */
    static final class SdWebResourceError extends WebResourceError {
        private final int code;
        private final CharSequence description;
        SdWebResourceError(int code, String description) {
            this.code = code;
            this.description = description;
        }
        @Override public int getErrorCode() { return code; }
        @Override public CharSequence getDescription() { return description; }
    }

    /**
     * Minimum {@code WebResourceRequest}. There is no engine, so there is nothing
     * real to report: the request is the main-frame GET we were asked to load, with
     * no headers (an engine would fill these in; we do not invent them).
     */
    static final class SdWebResourceRequest implements WebResourceRequest {
        private final Uri uri;
        private boolean mainFrame=true,redirect,gesture;private String method="GET";
        SdWebResourceRequest(JSONObject request){this(request.optString("url"));mainFrame=request.optBoolean("mainFrame",true);redirect=request.optBoolean("redirect");gesture=request.optBoolean("gesture");method=request.optString("method","GET");}
        SdWebResourceRequest(String url) {
            Uri parsed;
            try { parsed = Uri.parse(url); } catch (Throwable t) { parsed = Uri.EMPTY; }
            this.uri = parsed;
        }
        @Override public Uri getUrl() { return uri; }
        @Override public boolean isForMainFrame() { return mainFrame; }
        @Override public boolean isRedirect() { return redirect; }
        @Override public boolean hasGesture() { return gesture; }
        @Override public String getMethod() { return method; }
        @Override public Map<String, String> getRequestHeaders() { return Collections.emptyMap(); }
    }

    // ---------------------------------------------------------------- cookies

    // Per-app private cookie mirror, synchronized with the real WebKit session.
    private static SdWebCookies COOKIES;
    static synchronized SdWebCookies cookies(){
        if(COOKIES==null)COOKIES=new SdWebCookies();
        return COOKIES;
    }

    // --------------------------------------------------------------- settings

    /**
     * One settings object per WebView, created once. The previous provider returned
     * a fresh object from every {@code getSettings()} call, so every value the app
     * wrote was silently dropped; a caller that reads back what it wrote must at
     * least see its own values here.
     */
    private static final class Settings extends WebSettings {
        private final Map<String, Object> values = new HashMap<String, Object>();
        private boolean bool(String k) { Object v = values.get(k); return v instanceof Boolean ? (Boolean) v : false; }
        private int integer(String k) { Object v = values.get(k); return v instanceof Integer ? (Integer) v : 0; }
        private long integer64(String k) { Object v = values.get(k); return v instanceof Long ? (Long) v : 0L; }
        private String string(String k) { Object v = values.get(k); return v == null ? null : String.valueOf(v); }
        private void put(String k, Object v) { values.put(k, v); }

        public void setNavDump(boolean v) { put("nav", v); } public boolean getNavDump() { return bool("nav"); }
        public void setSupportZoom(boolean v) { put("supportZoom", v); } public boolean supportZoom() { return bool("supportZoom"); }
        public void setMediaPlaybackRequiresUserGesture(boolean v) { put("mediaGesture", v); } public boolean getMediaPlaybackRequiresUserGesture() { return bool("mediaGesture"); }
        public void setBuiltInZoomControls(boolean v) { put("builtZoom", v); } public boolean getBuiltInZoomControls() { return bool("builtZoom"); }
        public void setDisplayZoomControls(boolean v) { put("displayZoom", v); } public boolean getDisplayZoomControls() { return bool("displayZoom"); }
        public void setAllowFileAccess(boolean v) { put("file", v); } public boolean getAllowFileAccess() { return bool("file"); }
        public void setAllowContentAccess(boolean v) { put("content", v); } public boolean getAllowContentAccess() { return bool("content"); }
        public void setLoadWithOverviewMode(boolean v) { put("overview", v); } public boolean getLoadWithOverviewMode() { return bool("overview"); }
        public void setEnableSmoothTransition(boolean v) { put("smooth", v); } public boolean enableSmoothTransition() { return bool("smooth"); }
        public void setUseWebViewBackgroundForOverscrollBackground(boolean v) { put("overscroll", v); } public boolean getUseWebViewBackgroundForOverscrollBackground() { return bool("overscroll"); }
        public void setSaveFormData(boolean v) { put("form", v); } public boolean getSaveFormData() { return bool("form"); }
        public void setSavePassword(boolean v) { put("password", v); } public boolean getSavePassword() { return bool("password"); }
        public void setTextZoom(int v) { put("textZoom", v); } public int getTextZoom() { return integer("textZoom"); }
        public void setAcceptThirdPartyCookies(boolean v) { put("thirdParty", v); } public boolean getAcceptThirdPartyCookies() { return bool("thirdParty"); }
        public void setDefaultZoom(ZoomDensity v) { put("defaultZoom", v); } public ZoomDensity getDefaultZoom() { Object v = values.get("defaultZoom"); return v instanceof ZoomDensity ? (ZoomDensity) v : ZoomDensity.MEDIUM; }
        public void setLightTouchEnabled(boolean v) { put("light", v); } public boolean getLightTouchEnabled() { return bool("light"); }
        public void setUserAgent(int v) { put("ua", v); } public int getUserAgent() { return integer("ua"); }
        public void setUseWideViewPort(boolean v) { put("wide", v); } public boolean getUseWideViewPort() { return bool("wide"); }
        public void setSupportMultipleWindows(boolean v) { put("windows", v); } public boolean supportMultipleWindows() { return bool("windows"); }
        public void setLayoutAlgorithm(LayoutAlgorithm v) { put("layout", v); } public LayoutAlgorithm getLayoutAlgorithm() { Object v = values.get("layout"); return v instanceof LayoutAlgorithm ? (LayoutAlgorithm) v : LayoutAlgorithm.NORMAL; }
        public void setStandardFontFamily(String v) { put("standard", v); } public String getStandardFontFamily() { return string("standard"); }
        public void setFixedFontFamily(String v) { put("fixed", v); } public String getFixedFontFamily() { return string("fixed"); }
        public void setSansSerifFontFamily(String v) { put("sans", v); } public String getSansSerifFontFamily() { return string("sans"); }
        public void setSerifFontFamily(String v) { put("serif", v); } public String getSerifFontFamily() { return string("serif"); }
        public void setCursiveFontFamily(String v) { put("cursive", v); } public String getCursiveFontFamily() { return string("cursive"); }
        public void setFantasyFontFamily(String v) { put("fantasy", v); } public String getFantasyFontFamily() { return string("fantasy"); }
        public void setMinimumFontSize(int v) { put("min", v); } public int getMinimumFontSize() { return integer("min"); }
        public void setMinimumLogicalFontSize(int v) { put("minLogical", v); } public int getMinimumLogicalFontSize() { return integer("minLogical"); }
        public void setDefaultFontSize(int v) { put("font", v); } public int getDefaultFontSize() { return integer("font"); }
        public void setDefaultFixedFontSize(int v) { put("fixedFont", v); } public int getDefaultFixedFontSize() { return integer("fixedFont"); }
        public void setLoadsImagesAutomatically(boolean v) { put("images", v); } public boolean getLoadsImagesAutomatically() { return bool("images"); }
        public void setBlockNetworkImage(boolean v) { put("blockImage", v); } public boolean getBlockNetworkImage() { return bool("blockImage"); }
        public void setBlockNetworkLoads(boolean v) { put("blockNetwork", v); } public boolean getBlockNetworkLoads() { return bool("blockNetwork"); }
        public void setJavaScriptEnabled(boolean v) { put("js", v); } public boolean getJavaScriptEnabled() { return bool("js"); }
        public void setAllowUniversalAccessFromFileURLs(boolean v) { put("universal", v); } public boolean getAllowUniversalAccessFromFileURLs() { return bool("universal"); }
        public void setAllowFileAccessFromFileURLs(boolean v) { put("fileUrls", v); } public boolean getAllowFileAccessFromFileURLs() { return bool("fileUrls"); }
        public void setPluginsEnabled(boolean v) { put("plugins", v); } public boolean getPluginsEnabled() { return bool("plugins"); }
        public void setPluginState(PluginState v) { put("pluginState", v); } public PluginState getPluginState() { Object v = values.get("pluginState"); return v instanceof PluginState ? (PluginState) v : PluginState.OFF; }
        public void setDatabasePath(String v) { put("databasePath", v); } public String getDatabasePath() { return string("databasePath"); }
        public void setGeolocationDatabasePath(String v) { put("geoDb", v); }
        public void setAppCacheEnabled(boolean v) { put("appCache", v); }
        public void setAppCachePath(String v) { put("appCachePath", v); }
        public void setAppCacheMaxSize(long v) { put("appCacheMax", v); }
        public void setDatabaseEnabled(boolean v) { put("database", v); } public boolean getDatabaseEnabled() { return bool("database"); }
        public void setDomStorageEnabled(boolean v) { put("dom", v); } public boolean getDomStorageEnabled() { return bool("dom"); }
        public void setGeolocationEnabled(boolean v) { put("geo", v); }
        public void setJavaScriptCanOpenWindowsAutomatically(boolean v) { put("jsWindows", v); } public boolean getJavaScriptCanOpenWindowsAutomatically() { return bool("jsWindows"); }
        public void setDefaultTextEncodingName(String v) { put("encoding", v); } public String getDefaultTextEncodingName() { return string("encoding"); }
        public void setUserAgentString(String v) { put("uaString", v); }
        public String getUserAgentString() {
            String v = string("uaString");
            return v != null ? v : DEFAULT_UA;
        }
        public void setNeedInitialFocus(boolean v) { put("initialFocus", v); }
        public void setRenderPriority(RenderPriority v) { put("renderPriority", v); }
        public void setCacheMode(int v) { put("cache", v); } public int getCacheMode() { return integer("cache"); }
        public void setMixedContentMode(int v) { put("mixed", v); } public int getMixedContentMode() { return integer("mixed"); }
        public void setVideoOverlayForEmbeddedEncryptedVideoEnabled(boolean v) { put("videoOverlay", v); }
        public boolean getVideoOverlayForEmbeddedEncryptedVideoEnabled() { return bool("videoOverlay"); }
        public void setOffscreenPreRaster(boolean v) { put("preRaster", v); } public boolean getOffscreenPreRaster() { return bool("preRaster"); }
        public void setSafeBrowsingEnabled(boolean v) { put("safeBrowsing", v); } public boolean getSafeBrowsingEnabled() { return bool("safeBrowsing"); }
        public void setDisabledActionModeMenuItems(int v) { put("disabledActionMode", v); } public int getDisabledActionModeMenuItems() { return integer("disabledAction"); }
        public void setForceDark(int v) { put("forceDark", v); } public int getForceDark() { return integer("forceDark"); }
        public void setAlgorithmicDarkeningAllowed(boolean v) { put("algoDarkening", v); } public boolean isAlgorithmicDarkeningAllowed() { return bool("algoDarkening"); }
    }

    static final String DEFAULT_UA =
            "Mozilla/5.0 (Linux; Android 10; SailDroid) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Mobile Safari/537.36";

    // ------------------------------------------------------------ diagnostics

    private static void log(String line) {
        // URLs in a login flow carry account IDs, tickets and session secrets.
        line=line.replaceAll("(?i)(https?|jsbridge|mqq|intent)://[^\\s|\"<>]+","$1://[redacted]");
        System.err.println("SDWEBVIEW=" + line);
    }
    private static String eventAudit(JSONObject event){
        JSONObject safe=new JSONObject();
        try{for(String key:new String[]{"event","status","action","accepted","id","active","frames","renders","elapsed_ms","value"})if(event.has(key))safe.put(key,event.get(key));}catch(Exception ignored){}
        return safe.toString();
    }

    private static void unsupported(String api) { log("unsupported|" + api); }

    private static Object defaultValue(Class<?> type) {
        if (type == Boolean.TYPE) return Boolean.FALSE;
        if (type == Integer.TYPE) return Integer.valueOf(0);
        if (type == Long.TYPE) return Long.valueOf(0L);
        if (type == Float.TYPE) return Float.valueOf(0f);
        if (type == Double.TYPE) return Double.valueOf(0d);
        if (type == Byte.TYPE) return Byte.valueOf((byte) 0);
        if (type == Short.TYPE) return Short.valueOf((short) 0);
        if (type == Character.TYPE) return Character.valueOf((char) 0);
        if (type == String.class) return "";
        if (type.isArray()) return Array.newInstance(type.getComponentType(), 0);
        return null;
    }

    // Paints must never be created in <clinit>: the binder broker process initializes this
    // class but has no graphics natives (android.graphics.Paint.nInit is missing there), so a
    // throwing class initializer takes the whole broker down with "registry_failed" (exit 12).
    private static Paint PANEL, TITLE, BODY;

    private static void ensurePaints() {
        if (PANEL != null) return;
        Paint panel = new Paint(), title = new Paint(), body = new Paint();
        panel.setStyle(Paint.Style.FILL);
        title.setColor(TEXT_TITLE);
        title.setAntiAlias(true);
        body.setColor(TEXT_BODY);
        body.setAntiAlias(true);
        PANEL = panel;
        TITLE = title;
        BODY = body;
    }

    /** True when {@code client}'s class overrides this method itself (not inherited). */
    private static boolean overrides(Object client, String name, Class<?>... params) {
        try {
            return client.getClass().getMethod(name, params).getDeclaringClass() != WebViewClient.class;
        } catch (Throwable t) {
            return false;
        }
    }

    // -------------------------------------------------------------- one view

    /** Per-WebView state: everything the old provider threw away between calls. */
    private static final class SdWebView {
        final WebView view;
        final WebView.PrivateAccess access;
        final Settings settings = new Settings();
        final SdWebInterfaces interfaces=new SdWebInterfaces();
        final SdWebCookies.Listener cookieListener;
        boolean commitPending;
        String url = "";
        String title = "";
        WebViewClient client;
        WebChromeClient chrome;
        DownloadListener download;
        int frameW, frameH;
        SdWebEngine engine;
        Bitmap webFrame;
        int progress, contentHeight, scrollY;
        boolean canBack, canForward, paused;
        boolean windowVisible=true;
        int scriptSequence;
        final Map<Integer, ValueCallback<String>> scripts = new HashMap<Integer, ValueCallback<String>>();
        boolean destroyed;
        boolean editorActive;
        String editorText="";
        int editorCursor,editorAnchor,editorPurpose,editorHints,editorEpoch;
        InputMethodConnection inputConnection;
        int phase = PHASE_IDLE;
        int errorCode=ERROR_NO_RENDERER;
        String errorDetail=ERROR_DETAIL;
        /**
         * The WebView paints its own background before onDraw, so colouring the view keeps the
         * state visible even when the host never reaches {@code WebView.onDraw} (measured: QQ's
         * com.tencent.smtt.sdk.WebView$a never triggers the draw callback, leaving a white hole).
         */
        private void applyPhaseBackground(int argb) {
            if (view == null) return;
            try {
                view.setBackgroundColor(argb);
                view.invalidate();
            } catch (Throwable t) {
                log("phase_background_failed|" + t.getClass().getName());
            }
        }
        long loadStartedAt;
        int drawSeq, webDrawSeq;
        int dispatchSeq;
        int diagDumps;
        int loggedPhase = -1;

        SdWebView(WebView view, WebView.PrivateAccess access) {
            this.view=view;this.access=access;
            cookieListener=new SdWebCookies.Listener(){public void changed(JSONObject operation){command(operation);}};
            cookies().attach(cookieListener);
        }

        boolean startEngine() {
            if (destroyed || view == null || !SdWebEngine.available()) return false;
            if (engine != null) return true;
            engine = new SdWebEngine(view.getContext().getDir("saidroid-webview", 0),
                    frameW > 0 ? frameW : SdDisplayShim.WIDTH,
                    frameH > 0 ? frameH : SdDisplayShim.HEIGHT, new SdWebEngine.Listener() {
                public void frame(Bitmap bitmap, long seq) {
                    if (destroyed) return;
                    webFrame = bitmap; view.postInvalidateOnAnimation();
                    if(commitPending){commitPending=false;if(client!=null)client.onPageCommitVisible(view,url);}

                    if (seq <= 3 || seq % 60 == 0) log("frame|seq=" + seq + "|w=" + bitmap.getWidth() + "|h=" + bitmap.getHeight());
                }
                public void event(JSONObject event) {
                    if (destroyed) return;
                    String kind = event.optString("event");
                    if(kind.equals("editor")){editorState(event);return;}
                    if(kind.equals("navigation")){navigation(event);return;}
                    if(kind.equals("js_interface")){
                        final int id=event.optInt("id");interfaces.call(event.optJSONObject("request"),new SdWebInterfaces.Reply(){public void send(JSONObject response){
                            try{command(new JSONObject().put("op","js_interface_reply").put("id",id).put("confirmed",true).put("text",response.toString()));}catch(Exception ignored){}
                        }});return;
                    }
                    if(kind.equals("js_dialog")){scriptDialog(event);return;}
                    if(kind.equals("cookies")){cookies().nativeSnapshot(event.optJSONArray("entries"),event.optLong("version"));return;}
                    if(kind.equals("document_committed")){commitPending=true;return;}
                    if (kind.equals("title")) {
                        title = event.optString("title");
                        if (chrome != null) chrome.onReceivedTitle(view, title);
                    } else if (kind.equals("url")) url = event.optString("url",url);
                    else if (kind.equals("progress")) {
                        progress = event.optInt("value"); if (chrome != null) chrome.onProgressChanged(view,progress);
                    } else if (kind.equals("history")) {
                        canBack = event.optBoolean("back"); canForward = event.optBoolean("forward");
                    } else if (kind.equals("scroll")) {
                        scrollY = event.optInt("y");contentHeight = event.optInt("height");
                    } else if (kind.equals("eval")) {
                        ValueCallback<String> callback = scripts.remove(event.optInt("id"));
                        if (callback != null) callback.onReceiveValue(event.optString("result","null"));
                    } else if (kind.equals("load")) {
                        int status=event.optInt("status");
                        if (status == 0) { phase=PHASE_LOADING; if (client != null) client.onPageStarted(view,event.optString("url",url),null); }
                        else if (status == 2 && phase != PHASE_ERROR_NO_RENDERER) { phase=PHASE_READY;progress=100; if (client != null) client.onPageFinished(view,event.optString("url",url));
                            if (System.getenv("SAILDROID_WEBVIEW_DIAGNOSTICS")!=null) {
                                view.postDelayed(new Runnable(){public void run(){try{command(new JSONObject().put("op","stats"));}catch(Exception ignored){}}},3000);
                                view.postDelayed(new Runnable(){public void run(){try{command(new JSONObject().put("op","stats"));}catch(Exception ignored){}}},6000);
                            }
                        }
                        else if (status == 3) failLoad(event.optString("url",url),WebViewClient.ERROR_UNKNOWN,event.optString("error","page load failed"));
                    } else if (kind.equals("error")) engineFailed(event.optString("message","engine error"));
                    log("engine_event|" + eventAudit(event));
                }
                public void failed(String reason) { if (!destroyed) engineFailed(reason); }
            });
            log("engine_started|renderer=qt-wpe|isolated=true");
            return true;
        }
        private InputMethodManager inputManager(){return(InputMethodManager)view.getContext().getSystemService(Context.INPUT_METHOD_SERVICE);}
        private void editorState(JSONObject state){
            int epoch=state.optInt("epoch");boolean active=state.optBoolean("active");
            if(epoch<editorEpoch)return;
            boolean changed=epoch!=editorEpoch||editorActive!=active||editorPurpose!=state.optInt("purpose")||editorHints!=state.optInt("hints");
            editorEpoch=epoch;editorActive=active;editorPurpose=state.optInt("purpose");editorHints=state.optInt("hints");
            editorText=state.optString("text");editorCursor=Math.max(0,Math.min(editorText.length(),state.optInt("cursor")));editorAnchor=Math.max(0,Math.min(editorText.length(),state.optInt("anchor")));
            if(inputConnection!=null&&inputConnection.epoch==epoch)inputConnection.updateMirror();
            InputMethodManager imm=inputManager();
            if(active){
                view.setFocusableInTouchMode(true);view.requestFocusFromTouch();view.requestFocus();
                if(imm!=null){
                    if(changed||!imm.isActive(view))imm.restartInput(view);
                    imm.updateSelection(view,editorCursor,editorAnchor,-1,-1);
                    if((editorHints&32)==0&&view.hasWindowFocus())imm.showSoftInput(view,InputMethodManager.SHOW_IMPLICIT);
                }
            }else if(imm!=null&&imm.isActive(view)){imm.hideSoftInputFromWindow(view.getWindowToken(),0);imm.restartInput(view);}
            View focus=view.getRootView().findFocus();
            log("editor_state|active="+active+"|epoch="+epoch+"|purpose="+editorPurpose+"|window_focus="+view.hasWindowFocus()+"|has_focus="+view.hasFocus()+"|focused_view="+(focus==null?"none":focus.getClass().getName())+"|served="+(imm!=null&&imm.isActive(view)));
        }
        InputMethodConnection createInputConnection(EditorInfo out){
            log("input_connection_requested|active="+editorActive+"|has_focus="+view.hasFocus()+"|out="+(out!=null));
            if(out==null||!editorActive)return null;
            out.packageName=SdApkPackage.NAME;out.fieldId=view.getId();out.initialSelStart=editorCursor;out.initialSelEnd=editorAnchor;
            out.inputType=InputType.TYPE_CLASS_TEXT;
            if(editorPurpose==6)out.inputType|=InputType.TYPE_TEXT_VARIATION_PASSWORD;
            else if(editorPurpose==4)out.inputType|=InputType.TYPE_TEXT_VARIATION_URI;
            else if(editorPurpose==5)out.inputType|=InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS;
            else if(editorPurpose==3)out.inputType=InputType.TYPE_CLASS_PHONE;
            else if(editorPurpose==1||editorPurpose==2)out.inputType=InputType.TYPE_CLASS_NUMBER;
            if((editorHints&1)==0)out.inputType|=InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS;
            out.imeOptions=EditorInfo.IME_ACTION_DONE|EditorInfo.IME_FLAG_NO_EXTRACT_UI;
            inputConnection=new InputMethodConnection(view);log("input_connection|epoch="+editorEpoch+"|purpose="+editorPurpose);return inputConnection;
        }
        final class InputMethodConnection extends BaseInputConnection{
            final int epoch=editorEpoch;
            final android.text.Editable mirror=new android.text.SpannableStringBuilder();
            boolean closed;
            InputMethodConnection(View target){super(target,true);updateMirror();}
            void updateMirror(){
                if(closed||epoch!=editorEpoch)return;
                if(!mirror.toString().equals(editorText)){mirror.replace(0,mirror.length(),editorText);BaseInputConnection.removeComposingSpans(mirror);}
                android.text.Selection.setSelection(mirror,editorCursor,editorAnchor);
            }
            @Override public android.text.Editable getEditable(){return mirror;}
            private boolean valid(){return!closed&&editorActive&&epoch==editorEpoch;}
            private boolean send(String op,JSONObject packet){if(!valid())return false;try{packet.put("op",op).put("epoch",epoch);return command(packet);}catch(Exception e){return false;}}
            public boolean commitText(CharSequence text,int pos){try{if(!valid())return false;super.commitText(text==null?"":text,pos);return send("ime_commit",new JSONObject().put("text",text==null?"":text.toString()));}catch(Exception e){return false;}}
            public boolean setComposingText(CharSequence text,int pos){try{if(!valid())return false;super.setComposingText(text==null?"":text,pos);return send("ime_preedit",new JSONObject().put("text",text==null?"":text.toString()).put("cursor",pos));}catch(Exception e){return false;}}
            public boolean finishComposingText(){if(!valid())return false;super.finishComposingText();return send("ime_finish",new JSONObject());}
            public boolean deleteSurroundingText(int before,int after){try{if(!valid()||before<0||after<0)return false;super.deleteSurroundingText(before,after);return send("ime_delete",new JSONObject().put("before",before).put("after",after));}catch(Exception e){return false;}}
            public boolean setSelection(int start,int end){try{if(!valid()||start<0||end<0||start>mirror.length()||end>mirror.length())return false;super.setSelection(start,end);return send("ime_select",new JSONObject().put("start",start).put("end",end));}catch(Exception e){return false;}}
            public boolean sendKeyEvent(KeyEvent event){try{return send("ime_key",new JSONObject().put("code",event.getKeyCode()).put("down",event.getAction()==KeyEvent.ACTION_DOWN).put("unicode",event.getUnicodeChar()).put("modifiers",event.getMetaState()));}catch(Exception e){return false;}}
            public boolean performEditorAction(int action){try{return send("ime_key",new JSONObject().put("code",KeyEvent.KEYCODE_ENTER).put("down",true))&&send("ime_key",new JSONObject().put("code",KeyEvent.KEYCODE_ENTER).put("down",false));}catch(Exception e){return false;}}
            public ExtractedText getExtractedText(ExtractedTextRequest request,int flags){if(!valid())return null;ExtractedText value=new ExtractedText();value.text=mirror.toString();value.startOffset=0;value.selectionStart=android.text.Selection.getSelectionStart(mirror);value.selectionEnd=android.text.Selection.getSelectionEnd(mirror);value.partialStartOffset=-1;value.partialEndOffset=-1;return value;}
            public boolean requestCursorUpdates(int mode){return valid();}
            public void closeConnection(){closed=true;super.closeConnection();}
        }

        void engineFailed(String reason) {
            if(engine != null)engine.close();engine=null;webFrame=null;
            log("engine_failed|reason=" + reason);
            for(ValueCallback<String> callback:scripts.values())if(callback!=null)callback.onReceiveValue(null);
            scripts.clear();phase=PHASE_LOADING;failLoad(url,WebViewClient.ERROR_UNKNOWN,"SailDroid WebView engine failed: "+reason);
        }
        boolean command(JSONObject packet) { return engine != null && engine.send(packet); }
        void configureEngine() throws Exception {
            command(new JSONObject().put("op","settings").put("javascript",settings.getJavaScriptEnabled()).put("deviceScale",view.getResources().getDisplayMetrics().density)
                .put("javascriptWindows",settings.getJavaScriptCanOpenWindowsAutomatically())
                .put("images",!settings.values.containsKey("images") || settings.getLoadsImagesAutomatically())
                .put("storage",settings.getDomStorageEnabled())
                .put("userAgent",settings.getUserAgentString() == null ? DEFAULT_UA : settings.getUserAgentString()));
            command(new JSONObject().put("op","interfaces").put("interfaces",interfaces.description()));
            command(cookies().snapshot());
        }
        boolean engineLoad(String target,String html,String base){return engineLoad(target,html,base,null);}
        boolean engineLoad(String target, String html, String base,Map<String,String> headers) {
            if (!startEngine()) return false;
            try {
                configureEngine();
                JSONObject load=new JSONObject().put("op","load");
                if(html != null)load.put("html",html).put("base",base == null ? "about:blank" : base);
                else {load.put("url",target);if(headers!=null)load.put("headers",new JSONObject(headers));}
                phase=PHASE_LOADING;progress=0;url=target;loadStartedAt=System.currentTimeMillis();
                command(load);updateVisibility();log("load|renderer=qt-wpe|via="+(html==null?"url":"html"));return true;
            }catch(Exception failure){engineFailed(failure.getClass().getSimpleName());return true;}
        }
        void updateVisibility() {
            if(engine==null)return;
            try{command(new JSONObject().put("op","visibility").put("active",windowVisible&&!paused));}
            catch(Exception failure){engineFailed("visibility");}
        }
        void resizeEngine() {
            if(engine == null || frameW < 1 || frameH < 1)return;
            int[] size=SdWebEngine.hostSize(frameW,frameH);
            try{command(new JSONObject().put("op","resize").put("width",size[0]).put("height",size[1]));}
            catch(Exception failure){engineFailed("resize:"+failure.getClass().getSimpleName());}
        }

        void navigation(final JSONObject event){
            boolean handled=false;
            try{if(client!=null)handled=client.shouldOverrideUrlLoading(view,new SdWebResourceRequest(event));}
            catch(Throwable callback){log("navigation_callback_failed|type="+callback.getClass().getSimpleName());handled=true;}
            try{command(new JSONObject().put("op","navigation_reply").put("id",event.optInt("id")).put("handled",handled).put("newWindow",event.optBoolean("newWindow")).put("url",event.optString("url")));}
            catch(Exception failure){engineFailed("navigation reply failed");}
            log("navigation_decision|handled="+handled+"|gesture="+event.optBoolean("gesture")+"|new_window="+event.optBoolean("newWindow"));
        }
        void scriptDialog(final JSONObject event){
            final int id=event.optInt("id"),kind=event.optInt("kind");
            android.webkit.JsResult.ResultReceiver receiver=new android.webkit.JsResult.ResultReceiver(){public void onJsResultComplete(android.webkit.JsResult result){
                try{JSONObject response=new JSONObject().put("op","js_dialog_reply").put("id",id).put("confirmed",result.getResult());if(result instanceof android.webkit.JsPromptResult)response.put("text",((android.webkit.JsPromptResult)result).getStringResult());command(response);}
                catch(Exception ignored){}
            }};
            android.webkit.JsResult result=kind==2?new android.webkit.JsPromptResult(receiver):new android.webkit.JsResult(receiver);
            boolean handled=false;
            try{if(chrome!=null){
                String address=event.optString("url",url),message=event.optString("message");
                if(kind==0)handled=chrome.onJsAlert(view,address,message,result);
                else if(kind==1)handled=chrome.onJsConfirm(view,address,message,result);
                else if(kind==2)handled=chrome.onJsPrompt(view,address,message,event.optString("default"),(android.webkit.JsPromptResult)result);
                else handled=chrome.onJsBeforeUnload(view,address,message,result);
            }}catch(Throwable callback){log("script_dialog_failed|type="+callback.getClass().getSimpleName());}
            if(!handled){
                final android.webkit.JsResult answer=result;
                try{android.app.AlertDialog.Builder dialog=new android.app.AlertDialog.Builder(view.getContext()).setMessage(event.optString("message"));
                    final android.widget.EditText input;
                    if(kind==2){input=new android.widget.EditText(view.getContext());input.setText(event.optString("default"));dialog.setView(input);}else input=null;
                    dialog.setPositiveButton(android.R.string.ok,new android.content.DialogInterface.OnClickListener(){public void onClick(android.content.DialogInterface d,int which){if(input!=null)((android.webkit.JsPromptResult)answer).confirm(input.getText().toString());else answer.confirm();}});
                    if(kind!=0)dialog.setNegativeButton(android.R.string.cancel,new android.content.DialogInterface.OnClickListener(){public void onClick(android.content.DialogInterface d,int which){answer.cancel();}});
                    dialog.setOnCancelListener(new android.content.DialogInterface.OnCancelListener(){public void onCancel(android.content.DialogInterface d){answer.cancel();}});dialog.show();
                }catch(Throwable unavailable){result.cancel();}
            }
        }

        // ---------------------------------------------------------- draw audit
        // Why this exists: QQ reaches QQBrowserActivity without crashing, but the
        // content area is white and ViewDelegate.onDraw is never called. The framework
        // bytecode says WebView.onDraw -> ViewDelegate.onDraw is the *only* paint path
        // (android.webkit.WebView.onDraw has exactly three instructions), so "no onDraw"
        // means either (a) the view is not in the drawn hierarchy (GONE/INVISIBLE/0x0/
        // clipped), (b) PFLAG_SKIP_DRAW is set (View.draw then skips onDraw entirely),
        // or (c) a different WebView instance is on screen. These dumps separate (a)
        // from (b) from (c) without guessing, and without touching the host tree.

        static String visName(View v) {
            if (v == null) return "null";
            int vis = v.getVisibility();
            return vis == View.VISIBLE ? "VISIBLE" : (vis == View.INVISIBLE ? "INVISIBLE" :
                    (vis == View.GONE ? "GONE" : ("?" + vis)));
        }

        static String className(Object o) {
            return o == null ? "null" : o.getClass().getName();
        }

        static String lpName(View v) {
            if (v == null) return "null";
            try {
                Object lp = v.getLayoutParams();
                return lp == null ? "null" : lp.getClass().getName();
            } catch (Throwable t) {
                return "err:" + t.getClass().getSimpleName();
            }
        }

        void scheduleDiag(String when) {
            if (view == null) return;
            try {
                view.postDelayed(new Runnable() {
                    public void run() { diagDump(when + "+1s"); }
                }, 1000L);
                view.postDelayed(new Runnable() {
                    public void run() { diagDump(when + "+3s"); }
                }, 3000L);
            } catch (Throwable t) {
                log("diag_failed|" + t.getClass().getName());
            }
        }

        void diagDump(String when) {
            if (view == null) return;
            diagDumps++;
            StringBuilder sb = new StringBuilder("diag|when=").append(when)
                    .append("|self=").append(className(view))
                    .append("|vis=").append(visName(view))
                    .append("|shown=").append(view.isShown())
                    .append("|willNotDraw=").append(view.willNotDraw())
                    .append("|alpha=").append(view.getAlpha())
                    .append("|attached=").append(view.isAttachedToWindow())
                    .append("|hw=").append(view.isHardwareAccelerated())
                    .append("|w=").append(view.getWidth())
                    .append("|h=").append(view.getHeight())
                    .append("|meas=").append(view.getMeasuredWidth()).append("x")
                    .append(view.getMeasuredHeight())
                    .append("|lp=").append(lpName(view))
                    .append("|draw_calls=").append(drawSeq)
                    .append("|dispatch_calls=").append(dispatchSeq);
            try {
                // Rect is pure Java (no native constructor), so this is safe here;
                // Paint/Bitmap in <clinit> is what killed the binder broker earlier.
                android.graphics.Rect r = new android.graphics.Rect();
                boolean gv = view.getGlobalVisibleRect(r);
                sb.append("|globVis=").append(gv)
                        .append("|glob=").append(r.left).append(",").append(r.top)
                        .append(",").append(r.right).append(",").append(r.bottom);
            } catch (Throwable t) {
                sb.append("|globVis=err:").append(t.getClass().getSimpleName());
            }
            log(sb.toString());
            Object cur = view;
            for (int depth = 0; depth < 8 && cur instanceof View; depth++) {
                View pv = (View) cur;
                log("diag|parent|depth=" + depth + "|class=" + className(pv)
                        + "|vis=" + visName(pv) + "|willNotDraw=" + pv.willNotDraw()
                        + "|w=" + pv.getWidth() + "|h=" + pv.getHeight()
                        + "|lp=" + lpName(pv));
                Object parent;
                try {
                    parent = pv.getParent();
                } catch (Throwable t) {
                    log("diag|parent_failed|" + t.getClass().getName());
                    break;
                }
                cur = parent;
            }
        }

        /**
         * Two-step, honest lifecycle: first {@code loading}, then (once we know the
         * renderer is absent) a terminal error with {@link #ERROR_NO_RENDERER}.
         * {@code onPageFinished} is never called, so nothing can mistake this for a
         * successfully loaded page.
         */
        void startLoad(String target, String how) {
            url = target;
            title = "";
            phase = PHASE_LOADING;
            loadStartedAt = System.currentTimeMillis();
            drawSeq = 0;
            log("state|phase=loading|url=" + target + "|via=" + how + "|renderer=none");
            if (client != null) {
                try {
                    client.onPageStarted(view, target, null);
                    log("callback|onPageStarted|url=" + target);
                } catch (Throwable t) {
                    log("callback_failed|onPageStarted|" + t.getClass().getName());
                }
            }
            applyPhaseBackground(0xFF1B2A49);
            log("progress|url=" + target + "|value=0|phase=loading");
            if (view != null) {
                view.postInvalidateOnAnimation();
                // One short frame in the loading state, then the terminal error: the
                // host sees an observable transition instead of a silent white screen.
                view.postDelayed(new Runnable() {
                    public void run() { failNoRenderer(SdWebView.this.url); }
                }, 180);
            } else {
                failNoRenderer(target);
            }
        }

        /** Terminal state: no renderer exists, so this load can never complete. */
        void failNoRenderer(String target) { failLoad(target,ERROR_NO_RENDERER,ERROR_DETAIL); }
        void failLoad(String target,int code,String detail) {
            if (destroyed || phase == PHASE_ERROR_NO_RENDERER) return;
            phase = PHASE_ERROR_NO_RENDERER;errorCode=code;errorDetail=detail;
            long ms = loadStartedAt == 0 ? 0 : System.currentTimeMillis() - loadStartedAt;
            applyPhaseBackground(0xFF4A1D1D);
            log("state|phase=error_no_renderer|url=" + target + "|ms=" + ms
                    + "|code=" + errorCode + "|renderer=" + (engine == null ? "none" : "qt-wpe"));
            if (client != null) {
                // Both overloads exist in API29. The base WebViewClient forwards the
                // API23 one to the legacy one, so blindly calling both would deliver
                // the same error twice to anyone overriding only the legacy method.
                // Instead: call the overload(s) this client actually overrides, so the
                // client receives the error exactly once, in its own idiom.
                boolean api23 = overrides(client, "onReceivedError",
                        WebView.class, WebResourceRequest.class, WebResourceError.class);
                boolean legacy = overrides(client, "onReceivedError",
                        WebView.class, int.class, String.class, String.class);
                if (api23) {
                    try {
                        client.onReceivedError(view, new SdWebResourceRequest(target),
                                new SdWebResourceError(errorCode, errorDetail));
                        log("callback|onReceivedError_api23|code=" + errorCode
                                + "|url=" + target + "|for_main_frame=true");
                    } catch (Throwable t) {
                        log("callback_failed|onReceivedError_api23|" + t.getClass().getName());
                    }
                }
                if (legacy) {
                    try {
                        client.onReceivedError(view, errorCode, errorDetail, target);
                        log("callback|onReceivedError|code=" + errorCode
                                + "|url=" + target);
                    } catch (Throwable t) {
                        log("callback_failed|onReceivedError|" + t.getClass().getName());
                    }
                }
                log("error_delivery|api23=" + api23 + "|legacy=" + legacy
                        + "|client=" + client.getClass().getName() + "|url=" + target);
            }
            log("load_failed|url=" + target + "|code=" + errorCode
                    + "|reason=" + (engine == null ? "renderer_unavailable" : "page_load_failed") + "|delivered_onPageFinished=false");
            if (view != null) view.postInvalidateOnAnimation();
        }

        void draw(Canvas canvas) {
            if (canvas == null) return;
            if (webFrame != null && !webFrame.isRecycled()) {
                canvas.drawBitmap(webFrame,null,new Rect(0,0,view.getWidth(),view.getHeight()),null);
                drawSeq++;if(++webDrawSeq<=3)log("draw|renderer=qt-wpe|seq="+webDrawSeq+"|w="+view.getWidth()+"|h="+view.getHeight());
                return;
            }
            if(System.getenv("SAILDROID_WEBVIEW_DIAGNOSTICS")==null){
                // A working engine's first frame can be asynchronous. Keep the
                // application's chosen WebView background, without a debug page.
                if(phase==PHASE_ERROR_NO_RENDERER){
                    ensurePaints();canvas.drawColor(0xfffafafa);TITLE.setColor(0xff333333);
                    TITLE.setTextSize(18*view.getResources().getDisplayMetrics().density);
                    canvas.drawText("网页暂时无法加载",24*view.getResources().getDisplayMetrics().density,64*view.getResources().getDisplayMetrics().density,TITLE);
                }
                return;
            }
            ensurePaints();
            int w = canvas.getWidth();
            int h = canvas.getHeight();
            drawSeq++;
            boolean loading = phase == PHASE_LOADING;
            boolean failed = phase == PHASE_ERROR_NO_RENDERER;
            int bg = failed ? BG_ERROR : (loading ? BG_LOADING : BG_IDLE);
            int band = failed ? BAND_ERROR : (loading ? BAND_LOADING : BAND_IDLE);
            int marker = failed ? MARKER_ERROR : (loading ? MARKER_LOADING : MARKER_IDLE);
            String phaseName = failed ? "error_no_renderer" : (loading ? "loading" : "idle");
            // Log the first few frames, then sparsely: enough to prove the placeholder
            // is really being drawn into the host's canvas, not so much that it spams.
            if (drawSeq <= 3 || drawSeq % 60 == 0) {
                log("draw|phase=" + phaseName + "|seq=" + drawSeq + "|w=" + w + "|h=" + h
                        + "|renderer=none");
            }
            if (loggedPhase != phase) {
                loggedPhase = phase;
                log("placeholder|phase=" + phaseName + "|bg=" + hex(bg) + "|band=" + hex(band)
                        + "|marker=" + hex(marker));
            }
            // Solid state colour over the whole canvas: the modal colour of any
            // screenshot of this placeholder identifies the state exactly.
            PANEL.setColor(bg);
            canvas.drawRect(0, 0, w, h, PANEL);
            float bandH = Math.max(64f, h * 0.03f);
            PANEL.setColor(band);
            canvas.drawRect(0, 0, w, bandH, PANEL);
            // Full-width exact-colour strip: readable from a single pixel row.
            PANEL.setColor(marker);
            canvas.drawRect(0, h - 12f, w, h, PANEL);
            float pad = Math.max(16f, w * 0.05f);
            float titleSize = Math.max(22f, Math.min(w, h) * 0.045f);
            float bodySize = Math.max(16f, titleSize * 0.62f);
            TITLE.setColor(TEXT_TITLE);
            TITLE.setTextSize(titleSize);
            BODY.setTextSize(bodySize);
            float y = bandH + pad + titleSize;
            canvas.drawText(loading ? "Loading web content" : "WebView unavailable", pad, y, TITLE);
            y += titleSize * 0.9f;
            canvas.drawText(loading && engine!=null ? "Starting WebKit renderer"
                    : (loading ? "Checking renderer availability" : errorDetail), pad, y, BODY);
            y += bodySize * 1.8f;
            if (failed) for (String line : wrap(errorDetail, 46)) {
                canvas.drawText(line, pad, y, BODY);
                y += bodySize * 1.25f;
            }
            y += bodySize * 0.8f;
            BODY.setColor(TEXT_MUTED);
            canvas.drawText("requested url:", pad, y, BODY);
            y += bodySize * 1.25f;
            BODY.setColor(TEXT_BODY);
            for (String line : wrap(url.length() == 0 ? "(none)" : url, 46)) {
                canvas.drawText(line, pad, y, BODY);
                y += bodySize * 1.25f;
            }
            BODY.setColor(TEXT_MUTED);
            y += bodySize * 0.8f;
            canvas.drawText("frame " + frameW + "x" + frameH + "  progress 0%  renderer=none"
                    + (loading ? "  state=loading" : (failed ? "  error=" + errorCode : "  state=idle")),
                    pad, y, BODY);
            BODY.setColor(TEXT_BODY);
        }

        private static List<String> wrap(String text, int cols) {
            List<String> out = new ArrayList<String>();
            if (text == null) return out;
            String rest = text;
            while (rest.length() > cols) {
                int cut = rest.lastIndexOf(' ', cols);
                if (cut <= 0) cut = cols;
                out.add(rest.substring(0, cut));
                rest = rest.substring(cut).trim();
            }
            if (rest.length() > 0) out.add(rest);
            return out;
        }

        Object handle(String name, Method m, Object[] args) {
            Class<?> rt = m.getReturnType();

            // ---- navigation: recorded, reported, never faked as success
            if (name.equals("loadUrl")) {
                String target = args != null && args.length > 0 ? String.valueOf(args[0]) : "(null)";
                url = target;
                title = "";
                if (target.startsWith("javascript:") && engine != null) {
                    try { command(new JSONObject().put("op","eval").put("id",0).put("script",target.substring(11))); }
                    catch(Exception failure){engineFailed("javascript command");} return null;
                }
                if (engineLoad(target,null,null,args.length>1&&args[1] instanceof Map?(Map<String,String>)args[1]:null)) return null;
                log("load_url|url=" + target + "|renderer=none");
                startLoad(target, "loadUrl");
                return null;
            }
            if (name.equals("postUrl")) {
                if(startEngine())try{configureEngine();url=String.valueOf(args[0]);phase=PHASE_LOADING;command(new JSONObject().put("op","post").put("url",url).put("body",android.util.Base64.encodeToString((byte[])args[1],android.util.Base64.NO_WRAP)));return null;}catch(Exception failure){engineFailed("POST request failed");}
                else startLoad(String.valueOf(args[0]),"postUrl");return null;
            }
            if (name.equals("loadData") || name.equals("loadDataWithBaseURL")) {
                boolean withBase=name.equals("loadDataWithBaseURL");
                String base=withBase && args[0]!=null ? String.valueOf(args[0]) : "about:blank";
                String data=String.valueOf(args[withBase?1:0]);
                String encoding=String.valueOf(args[withBase?3:2]);
                try {
                    if("base64".equalsIgnoreCase(encoding))data=new String(android.util.Base64.decode(data,android.util.Base64.DEFAULT),"UTF-8");
                    if(engineLoad(base,data,base))return null;
                }catch(Exception failure){log("load_data_failed|"+failure.getClass().getSimpleName());}
                startLoad(base,"loadData");return null;
            }
            if (name.equals("reload") || name.equals("goBack") || name.equals("goForward")
                    || name.equals("goBackOrForward") || name.equals("stopLoading")) {
                if(engine!=null)try {
                    String op=name.equals("reload")?"reload":name.equals("goBack")?"back":name.equals("goForward")?"forward":name.equals("stopLoading")?"stop":"unsupported";
                    command(new JSONObject().put("op",op));return null;
                }catch(Exception failure){engineFailed("navigation");}
                unsupported(name);return null;
            }
            if(name.equals("canGoBack"))return Boolean.valueOf(canBack);
            if(name.equals("canGoForward"))return Boolean.valueOf(canForward);
            if (name.equals("canGoBack") || name.equals("canGoForward")
                    || name.equals("canGoBackOrForward")) {
                return Boolean.FALSE;
            }
            if (name.equals("getUrl") || name.equals("getOriginalUrl")) return url;
            if (name.equals("getTitle")) return title;
            if (name.equals("getProgress")) return Integer.valueOf(progress);
            if (name.equals("getContentHeight")) return Integer.valueOf(contentHeight);
            if (name.equals("getContentWidth")) return Integer.valueOf(frameW);
            if (name.equals("getFavicon") || name.equals("getTouchIconUrl")) return null;
            if (name.equals("getCertificate")) return null;
            if (name.equals("getScale")) return Float.valueOf(1f);

            // ---- the rendering surface itself
            if (name.equals("getViewDelegate")) return viewDelegate();
            if (name.equals("getScrollDelegate")) return scrollDelegate();
            if (name.equals("getSettings")) return settings;

            // ---- clients
            if(name.equals("getWebViewClient"))return client;
            if(name.equals("getWebChromeClient"))return chrome;
            if (name.equals("setWebViewClient")) { client = (WebViewClient) args[0]; return null; }
            if (name.equals("setWebChromeClient")) { chrome = (WebChromeClient) args[0]; return null; }
            if (name.equals("setDownloadListener")) { download = (DownloadListener) args[0]; unsupported("setDownloadListener"); return null; }
            if (name.equals("setFindListener")) { unsupported("setFindListener"); return null; }
            if (name.equals("setPictureListener")) { unsupported("setPictureListener"); return null; }
            if (name.equals("setCertificate")) { unsupported("setCertificate"); return null; }

            // ---- script bridge: explicitly absent, not silently ignored
            if (name.equals("addJavascriptInterface")) {
                interfaces.add(String.valueOf(args[1]),args[0]);return null;
            }
            if (name.equals("removeJavascriptInterface")) { interfaces.remove(String.valueOf(args[0]));return null; }
            if (name.equals("createWebMessageChannel")) { unsupported("createWebMessageChannel"); return null; }
            if (name.equals("postMessageToMainFrame")) { unsupported("postMessageToMainFrame"); return null; }
            if (name.equals("evaluateJavaScript")) {
                if(engine!=null)try {
                    int id=++scriptSequence;
                    if(args.length>1 && args[1] instanceof ValueCallback)scripts.put(id,(ValueCallback<String>)args[1]);
                    command(new JSONObject().put("op","eval").put("id",id).put("script",String.valueOf(args[0])));return null;
                }catch(Exception failure){engineFailed("eval:"+failure.getClass().getSimpleName());}
                unsupported("evaluateJavaScript|len=" + (args != null && args.length > 0 && args[0] != null ? String.valueOf(args[0]).length() : 0));
                if (args != null && args.length > 1 && args[1] instanceof ValueCallback) {
                    ((ValueCallback<?>) args[1]).onReceiveValue(null);
                }
                return null;
            }

            if(name.equals("onPause")||name.equals("onResume")) {
                paused=name.equals("onPause");updateVisibility();return null;
            }
            if(name.equals("isPaused"))return Boolean.valueOf(paused);
            if(name.equals("clearView")){webFrame=null;view.invalidate();return null;}
            // ---- lifecycle / misc: state only
            if (name.equals("destroy")) { destroyed = true; if(engine!=null)engine.close();engine=null;webFrame=null;scripts.clear();interfaces.close();cookies().detach(cookieListener);log("destroyed"); return null; }
            if (name.equals("onPause") || name.equals("onResume") || name.equals("pauseTimers")
                    || name.equals("resumeTimers") || name.equals("freeMemory")
                    || name.equals("clearCache") || name.equals("clearFormData")
                    || name.equals("clearHistory") || name.equals("clearSslPreferences")
                    || name.equals("savePassword") || name.equals("setNetworkAvailable")
                    || name.equals("notifyFindDialogDismissed") || name.equals("saveState")
                    || name.equals("restoreState") || name.equals("savePicture")
                    || name.equals("restorePicture") || name.equals("zoomIn") || name.equals("zoomOut")
                    || name.equals("zoomBy") || name.equals("invokeZoomPicker") || name.equals("flingScroll")) {
                return null;
            }
            if (name.equals("copyBackForwardList") || name.equals("getHitTestResult")
                    || name.equals("capturePicture") || name.equals("createPrintDocumentAdapter")
                    || name.equals("saveWebArchive") || name.equals("findAll") || name.equals("findNext")
                    || name.equals("getHttpAuthUsernamePassword") || name.equals("getZoomControls")
                    || name.equals("setHttpAuthUsernamePassword") || name.equals("setInitialScale")
                    || name.equals("getRendererPriorityWaivedWhenNotVisible") || name.equals("getRendererRequestedPriority")
                    || name.equals("requestFocusNodeHref") || name.equals("requestImageRef")
                    || name.equals("setMapTrackballToArrowKeys") || name.equals("setRendererPriorityPolicy")
                    || name.equals("dumpViewHierarchyWithProperties") || name.equals("findHierarchyView")) {
                unsupported(name);
                return defaultValue(rt);
            }
            log("unhandled|" + name);
            return defaultValue(rt);
        }

        Object viewDelegate() {
            return Proxy.newProxyInstance(ViewDelegate.class.getClassLoader(),
                    new Class<?>[]{ViewDelegate.class}, new InvocationHandler() {
                        public Object invoke(Object p, Method m, Object[] args) {
                            String n = m.getName();
                            if (n.equals("toString")) return "SdWebView.ViewDelegate";
                            if (n.equals("hashCode")) return Integer.valueOf(System.identityHashCode(p));
                            if (n.equals("equals")) return Boolean.valueOf(p == args[0]);
                            if (n.equals("onDraw")) { draw(args != null && args.length > 0 ? (Canvas) args[0] : null); return null; }
                            if (n.equals("setBackgroundColor") && args != null && args.length == 1) {
                                // WebView.setBackgroundColor() forwards here, so the default View
                                // behaviour never runs and the host stays white. Re-apply it through
                                // View.setBackground(Drawable), which WebView does not override.
                                try {
                                    view.setBackground(new android.graphics.drawable.ColorDrawable(
                                            ((Integer) args[0]).intValue()));
                                    view.invalidate();
                                } catch (Throwable t) {
                                    log("set_background_failed|" + t.getClass().getName());
                                }
                                return null;
                            }
                            if (n.equals("setFrame")) {
                                // ViewDelegate.setFrame returns a boolean primitive: returning null here
                                // makes the proxy throw "Expected to unbox a 'boolean' primitive type but
                                // was returned null" from WebView.setFrame during the layout pass, which
                                // killed the process (2026-10-27, QQBrowserActivity first layout).
                                frameW = ((Integer) args[2]).intValue() - ((Integer) args[0]).intValue();
                                frameH = ((Integer) args[3]).intValue() - ((Integer) args[1]).intValue();
                                boolean changed=access.super_setFrame((Integer)args[0],(Integer)args[1],(Integer)args[2],(Integer)args[3]);
                                view.setWillNotDraw(false);
                                log("set_frame|" + frameW + "x" + frameH+"|actual="+view.getWidth()+"x"+view.getHeight());
                                resizeEngine();return Boolean.valueOf(changed);
                            }
                            if (n.equals("onSizeChanged")) {
                                frameW = ((Integer) args[0]).intValue();
                                frameH = ((Integer) args[1]).intValue();
                                log("size_changed|" + frameW + "x" + frameH);
                                resizeEngine();return null;
                            }
                            if (n.equals("onMeasure")) {
                                // No engine, so no intrinsic content size is claimed here; the
                                // WebView keeps the size its parent gave it.
                                return null;
                            }
                            if (n.equals("onAttachedToWindow")) {
                                view.setWillNotDraw(false);windowVisible=true;updateVisibility();
                                log("attached");
                                scheduleDiag("attach");
                                return null;
                            }
                            if (n.equals("onDetachedFromWindow")) { windowVisible=false;updateVisibility();log("detached"); return null; }
                            if (n.equals("onWindowVisibilityChanged")) {
                                windowVisible=((Integer)args[0]).intValue()==View.VISIBLE;updateVisibility();
                                log("diag|window_visibility|vis=" + (args != null && args.length > 0 ? String.valueOf(args[0]) : "?"));
                                return null;
                            }
                            if (n.equals("preDispatchDraw")) {
                                dispatchSeq++;
                                if (dispatchSeq <= 3) log("diag|predispatch|seq=" + dispatchSeq);
                                return Boolean.FALSE;
                            }
                            if (n.equals("setLayoutParams")) {
                                access.super_setLayoutParams((android.view.ViewGroup.LayoutParams) args[0]);
                                return null;
                            }
                            if (n.equals("shouldDelayChildPressedState")) return Boolean.FALSE;
                            if (n.equals("getAccessibilityNodeProvider")) return null;
                            if (n.equals("onCreateInputConnection")) {
                                EditorInfo info=args!=null&&args.length>0?(EditorInfo)args[0]:null;
                                return createInputConnection(info);
                            }
                            if (n.equals("onCheckIsTextEditor")) return Boolean.valueOf(editorActive);
                            if (n.equals("onTouchEvent") && engine!=null) {
                                MotionEvent event=(MotionEvent)args[0];
                                if(view.getWidth()<1||view.getHeight()<1)return Boolean.FALSE;
                                // The host consumes resize and touch packets in order. Send View
                                // extents so it maps input to its current viewport, not a stale frame.
                                try {command(SdWebEngine.touchCommand(event.getActionMasked(),event.getX(),event.getY(),event.getEventTime(),view.getWidth(),view.getHeight()));return Boolean.TRUE;}
                                catch(Exception failure){engineFailed("touch");return Boolean.FALSE;}
                            }
                            if (n.equals("dispatchKeyEvent") || n.equals("onTouchEvent")
                                    || n.equals("onKeyDown") || n.equals("onKeyUp")
                                    || n.equals("onGenericMotionEvent") || n.equals("onHoverEvent")
                                    || n.equals("onTrackballEvent") || n.equals("onDragEvent")) {
                                // No engine consumes input; returning false lets the host
                                // view (and its scroll container) handle the gesture.
                                return Boolean.FALSE;
                            }
                            if (n.equals("requestFocus")) return access.super_requestFocus((Integer)args[0],(Rect)args[1]);
                            if (n.equals("performLongClick")) return access.super_performLongClick();
                            // WebView passes its super result into these delegate calls.
                            // IMM needs both the actual Handler and focused View to
                            // bind a served editor; null silently aborts startInput.
                            if (n.equals("getHandler")||n.equals("findFocus")) return args[0];
                            return defaultValue(m.getReturnType());
                        }
                    });
        }

        Object scrollDelegate() {
            return Proxy.newProxyInstance(ScrollDelegate.class.getClassLoader(),
                    new Class<?>[]{ScrollDelegate.class}, new InvocationHandler() {
                        public Object invoke(Object p, Method m, Object[] args) {
                            String n = m.getName();
                            if (n.equals("toString")) return "SdWebView.ScrollDelegate";
                            if (n.equals("hashCode")) return Integer.valueOf(System.identityHashCode(p));
                            if (n.equals("equals")) return Boolean.valueOf(p == args[0]);
                            // No scrollable content exists, so every range is 0 and nothing scrolls.
                            return defaultValue(m.getReturnType());
                        }
                    });
        }
    }

    // ------------------------------------------------------------- the bridge

    private static Object provider(WebView view, WebView.PrivateAccess access) {
        final SdWebView state = new SdWebView(view,access);
        log("webview_created|class=" + (view == null ? "null" : view.getClass().getName()));
        return Proxy.newProxyInstance(WebViewProvider.class.getClassLoader(),
                new Class<?>[]{WebViewProvider.class}, new InvocationHandler() {
                    public Object invoke(Object p, Method m, Object[] args) {
                        String n = m.getName();
                        if (n.equals("toString")) return "SdWebViewProvider.WebViewProvider";
                        if (n.equals("hashCode")) return Integer.valueOf(System.identityHashCode(p));
                        if (n.equals("equals")) return Boolean.valueOf(p == args[0]);
                        if (n.equals("init")) {
                            log("provider_init|params=" + (args != null && args.length > 0 && args[0] instanceof Map
                                    ? ((Map<?, ?>) args[0]).size() : 0));
                            return null;
                        }
                        return state.handle(n, m, args);
                    }
                });
    }

    private static Object statics() {
        return Proxy.newProxyInstance(WebViewFactoryProvider.Statics.class.getClassLoader(),
                new Class<?>[]{WebViewFactoryProvider.Statics.class}, new InvocationHandler() {
                    public Object invoke(Object p, Method m, Object[] args) {
                        String n = m.getName();
                        if (n.equals("toString")) return "SdWebViewProvider.Statics";
                        if (n.equals("hashCode")) return Integer.valueOf(System.identityHashCode(p));
                        if (n.equals("equals")) return Boolean.valueOf(p == args[0]);
                        if (n.equals("getDefaultUserAgent")) return DEFAULT_UA;
                        if (n.equals("findAddress")) return defaultValue(m.getReturnType());
                        if (n.equals("freeMemoryForTests")) return defaultValue(m.getReturnType());
                        return defaultValue(m.getReturnType());
                    }
                });
    }

    /** Installs the provider once. Never throws: a failure is logged, not swallowed silently. */
    public static void install() {
        try {
            Class<?> factory = Class.forName("android.webkit.WebViewFactory");
            Field field = factory.getDeclaredField("sProviderInstance");
            field.setAccessible(true);
            if (field.get(null) != null) {
                log("provider_present|action=none");
                return;
            }
            Object instance = Proxy.newProxyInstance(WebViewFactoryProvider.class.getClassLoader(),
                    new Class<?>[]{WebViewFactoryProvider.class}, new InvocationHandler() {
                        public Object invoke(Object p, Method m, Object[] args) {
                            String n = m.getName();
                            if (n.equals("toString")) return "SdWebViewProvider";
                            if (n.equals("hashCode")) return Integer.valueOf(System.identityHashCode(p));
                            if (n.equals("equals")) return Boolean.valueOf(p == args[0]);
                            if (n.equals("createWebView")) {
                SdViewRepair.enable();
                WebView created = (WebView) args[0];
                try {
                    created.setWillNotDraw(false);
                } catch (Throwable t) {
                    log("set_will_not_draw_failed|" + t.getClass().getName());
                }
                return provider(created,(WebView.PrivateAccess)args[1]);
            }
                            if (n.equals("getCookieManager")) return cookies();
                            if (n.equals("getWebViewClassLoader")) return SdWebViewProvider.class.getClassLoader();
                            if (n.equals("getStatics")) return statics();
                            if (n.startsWith("get")) return defaultValue(m.getReturnType());
                            return defaultValue(m.getReturnType());
                        }
                    });
            field.set(null, instance);
            log("provider_installed|mode="+(SdWebEngine.available()?"isolated-qt-wpe":"diagnostic-only")+"|ua="+DEFAULT_UA);
        } catch (Throwable failure) {
            log("provider_failed|type=" + failure.getClass().getName() + "|msg=" + failure.getMessage());
        }
    }

    private SdWebViewProvider() {}
}
