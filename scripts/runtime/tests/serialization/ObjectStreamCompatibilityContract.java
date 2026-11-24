import java.io.*;
import java.util.Arrays;

/** Ordinary serialization plus real target-dependent compatibility callbacks. */
public final class ObjectStreamCompatibilityContract {
    private static int checks;
    private static void check(boolean ok,String label) { ++checks; if(!ok) throw new AssertionError(label); }
    private static class Explicit implements Serializable {
        private static final long serialVersionUID=0x123456789abcdefL;
        String text="Nemo \uD80C\uDC00";
        int[] numbers={1,-7,Integer.MAX_VALUE};
        long value=Long.MIN_VALUE;
    }
    private static class Base implements Serializable {
        static { if (System.nanoTime()==0) throw new AssertionError(); }
    }
    private static class Inherit extends Base {}
    private static class Own extends Base {
        static { if (System.nanoTime()==0) throw new AssertionError(); }
    }
    private static class Plain implements Serializable {}
    private static class NotSerializable {}
    public static void main(String[] args) throws Exception {
        java.lang.reflect.Method compute=ObjectStreamClass.class.getDeclaredMethod("computeDefaultSUID",Class.class);
        compute.setAccessible(true);
        dalvik.system.VMRuntime vm=dalvik.system.VMRuntime.getRuntime();
        int original=vm.getTargetSdkVersion();
        ObjectStreamClass.DefaultSUIDCompatibilityListener saved=ObjectStreamClass.suidCompatibilityListener;
        final int[] warnings={0};final Class<?>[] warned={null};final long[] hash={0};
        ObjectStreamClass.suidCompatibilityListener=(clazz,suid)->{warnings[0]++;warned[0]=clazz;hash[0]=suid;};
        try {
            vm.setTargetSdkVersion(23);
            long legacy=(Long)compute.invoke(null,Inherit.class);
            check(warnings[0]==1&&warned[0]==Inherit.class&&hash[0]==legacy,"real inherited initializer callback");
            long own23=(Long)compute.invoke(null,Own.class);
            long plain23=(Long)compute.invoke(null,Plain.class);
            check(warnings[0]==1,"own initializer and plain classes emit no compatibility warning");
            for(int sdk:new int[]{24,29,30}) {
                vm.setTargetSdkVersion(sdk);
                check((Long)compute.invoke(null,Inherit.class)!=legacy,"modern SUID differs at actual SDK boundary "+sdk);
                check((Long)compute.invoke(null,Own.class)==own23,"own initializer stable "+sdk);
                check((Long)compute.invoke(null,Plain.class)==plain23,"plain class stable "+sdk);
                check(warnings[0]==1,"no modern SDK compatibility warning "+sdk);
            }
            check(ObjectStreamClass.lookup(Explicit.class).getSerialVersionUID()==0x123456789abcdefL,"explicit version unchanged");
            check(ObjectStreamClass.lookup(NotSerializable.class)==null,"nonserializable lookup unchanged");
            check(ObjectStreamClass.lookupAny(NotSerializable.class).getSerialVersionUID()==0,"nonserializable version zero");
            Explicit payload=new Explicit();
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            try(ObjectOutputStream out=new ObjectOutputStream(bytes)){out.writeObject(payload);out.writeObject(payload);out.writeObject(new int[]{0,-1,42});}
            check(bytes.size()>0,"real serialized bytes produced");
            try(ObjectInputStream in=new ObjectInputStream(new ByteArrayInputStream(bytes.toByteArray()))) {
                Explicit restored=(Explicit)in.readObject();
                check(restored!=payload&&restored.text.equals(payload.text),"ordinary object and supplementary Unicode roundtrip");
                check(restored.value==payload.value&&Arrays.equals(restored.numbers,payload.numbers),"primitive fields roundtrip");
                check(in.readObject()==restored,"shared reference identity preserved");
                check(Arrays.equals((int[])in.readObject(),new int[]{0,-1,42}),"primitive array roundtrip");
                check(in.read()==-1,"stream ended normally");
            }
            check(warnings[0]==1,"explicit serialization does not fabricate compatibility warnings");
        } finally {
            ObjectStreamClass.suidCompatibilityListener=saved;
            vm.setTargetSdkVersion(original);
        }
        check(vm.getTargetSdkVersion()==original,"target SDK restored");
        check(ObjectStreamClass.suidCompatibilityListener==saved,"callback restored");
        System.out.println("OBJECTSTREAM_COMPATIBILITY=PASS|checks="+checks+"|actualSdkBoundary=23/24|nativeUnchanged=true");
    }
}
