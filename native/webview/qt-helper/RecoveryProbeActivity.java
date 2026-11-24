package org.example.saildroid.networktoast;

import android.app.Activity;
import android.content.Intent;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Handler;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.File;
import org.json.JSONArray;

/** Normal APK regression for failed page recovery and queued Activity launches. */
public final class RecoveryProbeActivity extends Activity {
    private final Handler handler = new Handler();
    private WebView web;
    private int page;
    private int activityStage;
    private static int returnedStage;
    private int results;
    private boolean completed;

    public final class RuntimeBridge {
        @JavascriptInterface public String echo(String value) { return "native-" + value; }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.addJavascriptInterface(new RuntimeBridge(), "RuntimeProbe");
        web.setWebViewClient(new WebViewClient() {
            @Override public void onReceivedError(WebView view, int code, String detail, String url) {
                if (page != 0) throw new AssertionError("Unexpected page error " + detail);
                page = 1;
                handler.postDelayed(new Runnable() {
                    public void run() {
                        web.loadDataWithBaseURL("https://saildroid.invalid/",
                            "<!doctype html><title>Recovery probe</title><body>Recovery probe</body>",
                            "text/html", "UTF-8", null);
                    }
                }, 300);
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (page == 1) {
                    page = 2;
                    view.evaluateJavascript("document.title + '|' + RuntimeProbe.echo('ok')",
                        new ValueCallback<String>() {
                            public void onReceiveValue(String value) {
                                requireText(value, "Recovery probe|native-ok");
                                page = 3;
                                web.loadUrl("https://weixin.qq.com/");
                            }
                        });
                } else if (page == 3 && url.startsWith("https://weixin.qq.com/")) {
                    page = 4;
                    view.evaluateJavascript("location.protocol + '|' + location.hostname",
                        new ValueCallback<String>() {
                            public void onReceiveValue(String value) {
                                requireText(value, "https:|weixin.qq.com");
                                System.err.println("API28_COMPAT=webview_recovery|https=true|java_interface=true");
                                activityStage = 1;
                                startProxy();
                            }
                        });
                }
            }
            @Override public void onReceivedSslError(WebView view, SslErrorHandler action, SslError error) {
                action.cancel();
                throw new AssertionError("TLS failure " + error.getPrimaryError());
            }
        });
        setContentView(web);
        File missing = new File(getFilesDir(), "missing-runtime-probe.html");
        if (missing.exists()) throw new AssertionError("Missing-file probe path exists");
        web.loadUrl("file://" + missing.getAbsolutePath());
        handler.postDelayed(new Runnable() {
            public void run() {
                if (!completed) throw new AssertionError("Recovery probe deadline");
            }
        }, 60000);
    }

    private static void requireText(String value, String expected) {
        try {
            String text = new JSONArray("[" + value + "]").getString(0);
            if (!expected.equals(text)) throw new AssertionError("Unexpected JavaScript result " + text);
        } catch (Exception failure) { throw new AssertionError(failure); }
    }

    private void startProxy() {
        startActivityForResult(new Intent(this, ProxyActivity.class).putExtra("stage", activityStage), 41);
    }

    @Override protected void onActivityResult(int request, int code, Intent data) {
        super.onActivityResult(request, code, data);
        if (request != 41 || code != RESULT_CANCELED) throw new AssertionError("Result delivered to wrong owner " + request);
        results++;
    }

    @Override protected void onResume() {
        super.onResume();
        handler.postDelayed(new Runnable() {
            public void run() {
                if (isFinishing() || activityStage == 0 || returnedStage != activityStage) return;
                if (results != activityStage) throw new AssertionError("Missing proxy result " + results);
                if (activityStage == 1) {
                    activityStage = 2;
                    startProxy();
                } else {
                    completed = true;
                    // Exercise finish followed by an accepted launch in a one-Activity task.
                    finish();
                    startActivity(new Intent(RecoveryProbeActivity.this, FinalActivity.class));
                }
            }
        }, 500);
    }

    @Override protected void onDestroy() {
        web.destroy();
        super.onDestroy();
    }

    public static final class ProxyActivity extends Activity {
        private boolean started;
        @Override protected void onResume() {
            super.onResume();
            if (started) return;
            started = true;
            new Handler().postDelayed(new Runnable() {
                public void run() {
                    int stage = getIntent().getIntExtra("stage", 0);
                    Intent destination = new Intent(ProxyActivity.this, ReceiverActivity.class).putExtra("stage", stage);
                    finish();
                    if (stage == 1) startActivity(destination);
                    else startActivityForResult(destination, 42);
                }
            }, 200);
        }
    }

    public static final class ReceiverActivity extends Activity {
        private boolean started;
        @Override protected void onResume() {
            super.onResume();
            if (started) return;
            started = true;
            if (getReferrer() == null || !getPackageName().equals(getReferrer().getHost()))
                throw new AssertionError("Finished caller referrer lost");
            new Handler().postDelayed(new Runnable() {
                public void run() {
                    returnedStage = getIntent().getIntExtra("stage", 0);
                    System.err.println("API28_COMPAT=queued_launch|stage=" + returnedStage + "|referrer=true");
                    setResult(RESULT_OK);
                    finish();
                }
            }, 200);
        }
    }

    public static final class FinalActivity extends Activity {
        @Override protected void onResume() {
            super.onResume();
            if (returnedStage != 2) throw new AssertionError("Activity chain incomplete");
            if (getReferrer() == null || !getPackageName().equals(getReferrer().getHost()))
                throw new AssertionError("Last caller referrer lost");
            System.err.println("API28_COMPAT=passed|page_error_recovery=true|queued_launch=true|detached_results=true|last_activity=true");
        }
    }
}
