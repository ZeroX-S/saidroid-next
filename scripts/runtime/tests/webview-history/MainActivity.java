package org.example.saildroid.webhistory;
import android.app.*;import android.os.*;import android.webkit.*;import android.widget.*;import java.io.*;
public final class MainActivity extends Activity {
 private WebView web;private Handler handler=new Handler();private int step=0,attempts=0;private WebBackForwardList frozen;private String[] urls=new String[3];private Button button;
 private void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 @Override public void onCreate(Bundle state){super.onCreate(state);FrameLayout layout=new FrameLayout(this);button=new Button(this);button.setText("Waiting for real WebKit history");button.setOnClickListener(v->{check(step==5,"History not ready");button.setText("Physical history touch passed");System.err.println("SD_HISTORY_PROBE=touch_passed|step="+step);});web=new WebView(this);layout.addView(web,new FrameLayout.LayoutParams(-1,-1));FrameLayout.LayoutParams control=new FrameLayout.LayoutParams(-1,220,android.view.Gravity.BOTTOM);layout.addView(button,control);setContentView(layout);web.getSettings().setJavaScriptEnabled(true);WebBackForwardList empty=web.copyBackForwardList();check(empty!=null&&empty.getSize()==0&&empty.getCurrentIndex()==-1&&empty.getCurrentItem()==null,"Initial history differs");
  try{for(int i=0;i<3;i++){File f=new File(getFilesDir(),"history-"+i+".html");String html="<!doctype html><html><head><title>History "+i+"</title><meta name='viewport' content='width=device-width'></head><body style='background:"+new String[]{"#265c98","#2a8d61","#98386c"}[i]+";color:white;font:48px sans-serif'><h1>History "+i+"</h1><p>Rendered by real WebKit</p><script>window.historyProbe="+i+";</script></body></html>";try(FileOutputStream out=new FileOutputStream(f)){out.write(html.getBytes("UTF-8"));}urls[i]=android.net.Uri.fromFile(f).toString();}}catch(Exception failure){throw new AssertionError(failure);}
  web.loadUrl(urls[0]);handler.postDelayed(this::poll,300);
 }
 private void poll(){int page=step<3?step:step==3?0:1;WebBackForwardList list=web.copyBackForwardList();int size=step<3?step+1:3;int index=step<3?step:step==3?0:1;
  if(list.getSize()!=size||list.getCurrentIndex()!=index||list.getCurrentItem()==null||!urls[page].equals(list.getCurrentItem().getUrl())||!("History "+page).equals(list.getCurrentItem().getTitle())){check(++attempts<200,"Renderer history not ready at step "+step);handler.postDelayed(this::poll,100);return;}attempts=0;check(list.getItemAtIndex(-1)==null&&list.getItemAtIndex(size)==null,"Out-of-range history item differs");check(web.canGoBack()==(index>0)&&web.canGoForward()==(index+1<size),"History navigation booleans differ");check(web.canGoBackOrForward(0)&&!web.canGoBackOrForward(Integer.MAX_VALUE)&&!web.canGoBackOrForward(Integer.MIN_VALUE),"Relative history bounds differ");
  final int now=step;web.evaluateJavascript("JSON.stringify({page:window.historyProbe,title:document.title})",value->{check(value!=null&&value.contains("page\\\":"+page)&&value.contains("History "+page),"Actual JavaScript content differs: "+value);System.err.println("SD_HISTORY_PROBE=page_verified|step="+now+"|page="+page+"|size="+size+"|index="+index+"|javascript="+value);
   if(now==0){frozen=list;step=1;web.loadUrl(urls[1]);}
   else if(now==1){check(frozen.getSize()==1&&frozen.getCurrentIndex()==0,"Snapshot mutated after new navigation");step=2;web.loadUrl(urls[2]);}
   else if(now==2){step=3;web.goBackOrForward(-2);}
   else if(now==3){check(frozen.getCurrentItem().getId()==list.getCurrentItem().getId(),"History item ID changed");step=4;web.goForward();}
   else{check(frozen.getSize()==1&&frozen.getCurrentIndex()==0&&urls[0].equals(frozen.getCurrentItem().getUrl()),"Immutable snapshot changed");step=5;button.setText("Tap to verify history input");System.err.println("SD_HISTORY_PROBE=flow_passed|pages=3|relative_back=-2|forward=1|immutable=true");return;}
   handler.postDelayed(this::poll,200);
  });
 }
 @Override protected void onDestroy(){handler.removeCallbacksAndMessages(null);if(web!=null)web.destroy();super.onDestroy();}
}
