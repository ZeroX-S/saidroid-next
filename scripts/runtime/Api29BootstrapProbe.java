/** VM-only ABI gate. No old framework or framework native is loaded. */
public final class Api29BootstrapProbe {
    public static void main(String[] args) {
        System.load(args[0]);
        boolean loaded=SdBridge.loadBionicLibrary(args[1]+"/libandroid_runtime.so",args[1]);
        System.err.println("API29_NATIVE_BOOTSTRAP="+(loaded?"loaded":"blocked"));
        if(!loaded)Runtime.getRuntime().halt(2);
        int registered=SdBridge.registerFrameworkNatives();
        if(registered<1)throw new AssertionError("Native registration failed: "+registered);
        if(android.os.Build.VERSION.SDK_INT!=29)throw new AssertionError("Not API 29");
        android.os.Parcel parcel=android.os.Parcel.obtain();
        parcel.writeString("API29 parcel");parcel.writeLong(0x12345678abcdef01L);parcel.setDataPosition(0);
        if(!"API29 parcel".equals(parcel.readString())||parcel.readLong()!=0x12345678abcdef01L)throw new AssertionError("Parcel round trip");
        parcel.recycle();
        android.graphics.Bitmap bitmap=android.graphics.Bitmap.createBitmap(64,64,android.graphics.Bitmap.Config.ARGB_8888);
        android.graphics.Canvas canvas=new android.graphics.Canvas(bitmap);
        canvas.drawColor(android.graphics.Color.RED);
        android.graphics.Paint paint=new android.graphics.Paint();paint.setColor(android.graphics.Color.BLUE);
        canvas.drawRect(8,8,40,40,paint);
        if(bitmap.getPixel(2,2)!=android.graphics.Color.RED||bitmap.getPixel(20,20)!=android.graphics.Color.BLUE)throw new AssertionError("Canvas pixels differ");
        java.io.ByteArrayOutputStream image=new java.io.ByteArrayOutputStream();
        if(!bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,image)||image.size()<100)throw new AssertionError("PNG encoding failed");
        System.err.println("API29_GRAPHICS=PASS|canvas=pixels|png_bytes="+image.size());
        if(android.graphics.Typeface.DEFAULT==null)throw new AssertionError("Default font unavailable");
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(20);canvas.drawText("Android 10",0,60,paint);
        if(paint.measureText("Android 10")<=0)throw new AssertionError("Text measurement failed");
        System.err.println("API29_TEXT=PASS|glyphs=rendered");
        System.err.println("API29_CORE=PASS|sdk="+android.os.Build.VERSION.SDK_INT+"|release="+android.os.Build.VERSION.RELEASE+"|parcel=roundtrip|native_modules="+registered);
        Runtime.getRuntime().halt(0);
    }
}
