/** VM-only test: an application signal handler must not intercept ART null checks. */
public final class SignalJitProbe {
    private static native void install();
    private static native int hits();
    private static native void restore();
    static final class Node {int value=7;}
    private static int read(Node node){return node.value;}
    public static void main(String[] args)throws Exception{
        System.load(args[0]);install();
        Node node=new Node();int sum=0;
        for(int i=0;i<2000000;i++)sum+=read(node);
        Thread.sleep(150);
        boolean caught=false;try{read(null);}catch(NullPointerException expected){caught=true;}
        int count=hits();restore();
        if(!caught||count!=0||sum!=14000000)throw new AssertionError("Signal chaining: caught="+caught+", user_hits="+count);
        System.err.println("API29_SIGNAL_JIT=PASS|managed_null=caught|user_handler_hits=0");
    }
}
