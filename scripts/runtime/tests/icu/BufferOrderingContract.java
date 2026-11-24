import java.nio.ByteBuffer;
import java.nio.DoubleBuffer;
import java.nio.FloatBuffer;

/** Signed-zero/NaN ordering across real heap/direct/read-only NIO buffers. */
public final class BufferOrderingContract {
    private static DoubleBuffer buffer(double value,int kind){
        DoubleBuffer result=kind%2==0?DoubleBuffer.allocate(3):ByteBuffer.allocateDirect(24).asDoubleBuffer();
        result.put(0,91);result.put(1,value);result.put(2,-73);result.position(1);result.limit(2);
        return kind<2?result:result.asReadOnlyBuffer();
    }
    private static int expected(double x,double y){
        return x<y?-1:x>y?1:x==y?0:Double.isNaN(x)?(Double.isNaN(y)?0:1):-1;
    }
    public static void main(String[] args){
        double[] values={Double.NEGATIVE_INFINITY,-1,-0.0,+0.0,1,Double.POSITIVE_INFINITY,
                Double.NaN,Double.longBitsToDouble(0x7ff8000000001234L)};
        int checks=0;
        for(double x:values)for(double y:values)for(int a=0;a<4;a++)for(int b=0;b<4;b++){
            DoubleBuffer left=buffer(x,a),right=buffer(y,b);
            int actual=Integer.signum(left.compareTo(right)),expected=expected(x,y);
            if(actual!=expected)throw new AssertionError("NIO ordering: "+x+" / "+y+" = "+actual+", expected "+expected);
            if(left.position()!=1||right.position()!=1||left.limit()!=2||right.limit()!=2)
                throw new AssertionError("Comparison changed buffer range");
            checks++;
        }
        DoubleBuffer shorter=DoubleBuffer.wrap(new double[]{1}),longer=DoubleBuffer.wrap(new double[]{1,2});
        if(shorter.compareTo(longer)>=0||longer.compareTo(shorter)<=0)throw new AssertionError("Prefix order changed");
        if(Double.compare(-0.0,+0.0)>=0||Double.compare(+0.0,-0.0)<=0)
            throw new AssertionError("Scalar Double.compare semantics changed");
        if(FloatBuffer.wrap(new float[]{-0.0f}).compareTo(FloatBuffer.wrap(new float[]{+0.0f}))!=0)
            throw new AssertionError("Float buffer zero order changed");
        System.out.println("BUFFER_ORDERING_CONTRACT=PASS|pair_checks="+checks+"|prefix=true|scalar_unchanged=true");
    }
}
