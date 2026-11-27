import java.math.BigInteger;
import java.util.Random;
/** API29 input-boundary contract; no allocation-heavy valid large inputs. */
public final class BigIntegerRandomContract {
 static final class CountingRandom extends Random {
  int calls;
  protected int next(int bits) { calls++; return super.next(bits); }
 }
 public static void main(String[] args) {
  dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(29);
  if(dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion()!=29)throw new AssertionError("SDK not bound");
  int checked=0;
  for(int offset=0;offset<31;offset++) {
   CountingRandom random=new CountingRandom();
   for(int variant=0;variant<2;variant++) {
    try { new BigInteger(Integer.MAX_VALUE-offset,variant==0?null:random);throw new AssertionError("Overflow input accepted"); }
    catch(NegativeArraySizeException expected) { checked++; }
    if(random.calls!=0)throw new AssertionError("Overflow input consumed randomness");
   }
  }
  for(int bits:new int[]{Integer.MIN_VALUE,-1}) {
   try { new BigInteger(bits,(Random)null);throw new AssertionError("Negative bit count accepted"); }
   catch(IllegalArgumentException expected) { checked++; }
  }
  if(!new BigInteger(0,(Random)null).equals(BigInteger.ZERO))throw new AssertionError("Zero/null changed");checked++;
  for(int bits:new int[]{1,7,8,9,31,32,33,64,65,127,128,1024}) {
   try { new BigInteger(bits,(Random)null);throw new AssertionError("Positive/null accepted"); }
   catch(NullPointerException expected) { checked++; }
   for(long seed:new long[]{0,1,-1,7,42,Long.MIN_VALUE,Long.MAX_VALUE,0x123456789abcdefL}) {
    Random first=new Random(seed),second=new Random(seed);byte[] bytes=new byte[(bits+7)/8];second.nextBytes(bytes);int excess=8*bytes.length-bits;bytes[0]&=(1<<(8-excess))-1;
    BigInteger expected=new BigInteger(1,bytes),actual=new BigInteger(bits,first);
    if(!actual.equals(expected)||actual.signum()<0||actual.bitLength()>bits)throw new AssertionError("Supported input changed: "+bits+" seed="+seed);
    if(first.nextLong()!=second.nextLong())throw new AssertionError("Random consumption changed");checked++;
   }
  }
  System.out.println("BIGINTEGER_RANDOM_CONTRACT=PASS|checks="+checked+"|uid="+android.system.Os.getuid());
 }
}
