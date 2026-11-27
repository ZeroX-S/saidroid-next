import android.os.Build;
public final class DeviceModelContract {
 public static void main(String[] args) {
  String[] values={Build.MANUFACTURER,Build.BRAND,Build.MODEL,Build.PRODUCT,Build.DEVICE};
  if(args.length!=5)throw new AssertionError("expected five hardware fields");
  String[] names={"manufacturer","brand","model","name","device"};
  for(int i=0;i<values.length;i++){
   System.out.println("HARDWARE_FIELD="+names[i]+"|"+values[i]);
   if(!values[i].equals(args[i]))throw new AssertionError(names[i]+" expected "+args[i]+", actual "+values[i]);
  }
  if(Build.VERSION.SDK_INT!=29)throw new AssertionError("SDK changed");
  System.out.println("HARDWARE_COMPONENT_FINGERPRINT="+Build.FINGERPRINT);
  System.out.println("DEVICE_MODEL_CONTRACT=passed|sdk=29");
 }
}
