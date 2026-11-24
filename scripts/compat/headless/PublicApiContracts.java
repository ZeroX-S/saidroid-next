package org.saildroid.compat;

import android.content.Intent;
import android.os.Parcel;
import android.os.Parcelable;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Member;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.net.BindException;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.util.ArrayList;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Application-owned checks for the restored Android 9 API surface. */
public final class PublicApiContracts {
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static Class<?> type(String descriptor) throws Exception {
        switch (descriptor) {
            case "V": return void.class;
            case "Z": return boolean.class;
            case "B": return byte.class;
            case "C": return char.class;
            case "S": return short.class;
            case "I": return int.class;
            case "J": return long.class;
            case "F": return float.class;
            case "D": return double.class;
            default:
                String name = descriptor.startsWith("L")
                        ? descriptor.substring(1, descriptor.length() - 1) : descriptor;
                return Class.forName(name.replace('/', '.'), false, PublicApiContracts.class.getClassLoader());
        }
    }

    private static Object call(Class<?> owner, Object target, String name, Class<?>[] parameters,
                               Object... arguments) throws Throwable {
        try { return owner.getMethod(name, parameters).invoke(target, arguments); }
        catch (InvocationTargetException failure) { throw failure.getCause(); }
    }

    private static Object get(Object target, String name) throws Throwable {
        return call(target.getClass(), target, name, new Class<?>[0]);
    }

    private static void members() throws Exception {
        Pattern parameter = Pattern.compile("\\[*([ZBCSIJFD]|L[^;]+;)");
        int count = 0;
        try (BufferedReader input = new BufferedReader(new InputStreamReader(
                PublicApiContracts.class.getResourceAsStream("api28-restored-members.txt"), "UTF-8"))) {
            String signature;
            while ((signature = input.readLine()) != null) {
                String[] parts = signature.split("->", 2);
                Class<?> owner = type(parts[0]);
                check(owner.getClassLoader() == Intent.class.getClassLoader(), "API class loaded outside boot classpath " + parts[0]);
                Member member;
                int start = parts[1].indexOf('(');
                if (start < 0) {
                    String[] field = parts[1].split(":", 2);
                    java.lang.reflect.Field actual = owner.getDeclaredField(field[0]);
                    check(actual.getType() == type(field[1]), "Field type differs " + signature);
                    member = actual;
                } else {
                    int end = parts[1].indexOf(')');
                    Matcher parameters = parameter.matcher(parts[1].substring(start + 1, end));
                    ArrayList<Class<?>> arguments = new ArrayList<Class<?>>();
                    while (parameters.find()) arguments.add(type(parameters.group()));
                    Class<?>[] types = arguments.toArray(new Class<?>[arguments.size()]);
                    String name = parts[1].substring(0, start);
                    if (name.equals("<init>")) {
                        member = owner.getDeclaredConstructor(types);
                    } else {
                        Method actual = owner.getDeclaredMethod(name, types);
                        check(actual.getReturnType() == type(parts[1].substring(end + 1)), "Return type differs " + signature);
                        member = actual;
                    }
                }
                check(Modifier.isPublic(member.getModifiers()) || Modifier.isProtected(member.getModifiers()),
                        "SDK member access differs " + signature);
                count++;
            }
        }
        check(count == 185, "Restored member count differs " + count);
        Class<?> opcodes = type("Ldalvik/bytecode/Opcodes;");
        check(opcodes.getField("OP_CONST_METHOD_HANDLE").getInt(null) == 0xfe, "Method handle opcode differs");
        check(opcodes.getField("OP_CONST_METHOD_TYPE").getInt(null) == 0xff, "Method type opcode differs");
        System.out.println("API28_PUBLIC_MEMBERS=PASS|members=" + count);
    }

    private static void sipProfile() throws Throwable {
        Class<?> builderType = type("Landroid/net/sip/SipProfile$Builder;");
        Object builder = builderType.getConstructor(String.class, String.class).newInstance("fixture", "example.invalid");
        call(builderType, builder, "setDisplayName", new Class<?>[]{String.class}, "API28 fixture");
        call(builderType, builder, "setAuthUserName", new Class<?>[]{String.class}, "fixture-auth");
        call(builderType, builder, "setProfileName", new Class<?>[]{String.class}, "compatibility");
        call(builderType, builder, "setPassword", new Class<?>[]{String.class}, "fixture-value");
        call(builderType, builder, "setProtocol", new Class<?>[]{String.class}, "tcp");
        call(builderType, builder, "setPort", new Class<?>[]{int.class}, 5070);
        call(builderType, builder, "setOutboundProxy", new Class<?>[]{String.class}, "sip:proxy.example.invalid");
        call(builderType, builder, "setSendKeepAlive", new Class<?>[]{boolean.class}, true);
        call(builderType, builder, "setAutoRegistration", new Class<?>[]{boolean.class}, false);
        Object profile = call(builderType, builder, "build", new Class<?>[0]);
        check("sip:fixture@example.invalid".equals(get(profile, "getUriString")), "SIP URI differs");
        check("TCP".equals(get(profile, "getProtocol")) && Integer.valueOf(5070).equals(get(profile, "getPort")), "SIP transport differs");
        check("proxy.example.invalid".equals(get(profile, "getProxyAddress")), "SIP proxy differs");
        Parcel parcel = Parcel.obtain();
        try {
            ((Parcelable) profile).writeToParcel(parcel, 0);
            parcel.setDataPosition(0);
            Parcelable.Creator<?> creator = (Parcelable.Creator<?>) profile.getClass().getField("CREATOR").get(null);
            Object restored = creator.createFromParcel(parcel);
            for (String name : new String[]{"getUriString", "getUserName", "getSipDomain", "getDisplayName", "getAuthUserName",
                    "getPassword", "getProfileName", "getProtocol", "getPort", "getProxyAddress", "getSendKeepAlive", "getAutoRegistration"}) {
                check(get(profile, name).equals(get(restored, name)), "SIP parcel field differs " + name);
            }
            check(creator.newArray(2).length == 2, "SIP parcel array differs");
        } finally { parcel.recycle(); }
        try {
            call(builderType, builder, "setPort", new Class<?>[]{int.class}, 999);
            throw new AssertionError("Invalid SIP port accepted");
        } catch (IllegalArgumentException expected) {}
        try {
            call(builderType, builder, "setProtocol", new Class<?>[]{String.class}, "invalid");
            throw new AssertionError("Invalid SIP protocol accepted");
        } catch (IllegalArgumentException expected) {}
        Class<?> manager = type("Landroid/net/sip/SipManager;");
        Intent incoming = new Intent();
        incoming.putExtra((String) manager.getField("EXTRA_CALL_ID").get(null), "fixture-call");
        incoming.putExtra((String) manager.getField("EXTRA_OFFER_SD").get(null), "fixture-description");
        check(Boolean.TRUE.equals(call(manager, null, "isIncomingCallIntent", new Class<?>[]{Intent.class}, incoming)), "SIP incoming Intent missing");
        check("fixture-call".equals(call(manager, null, "getCallId", new Class<?>[]{Intent.class}, incoming)), "SIP call identity differs");
        check("fixture-description".equals(call(manager, null, "getOfferSessionDescription", new Class<?>[]{Intent.class}, incoming)), "SIP session description differs");
        System.out.println("API28_SIP_PROFILE=PASS|parcel=true|validation=true|intent=true");
    }

    private static void rtp() throws Throwable {
        Class<?> codec = type("Landroid/net/rtp/AudioCodec;");
        Object[] first = (Object[]) call(codec, null, "getCodecs", new Class<?>[0]);
        check(first.length == 2 || first.length == 5, "RTP codec inventory differs");
        first[0] = null;
        check(((Object[]) call(codec, null, "getCodecs", new Class<?>[0]))[0] != null, "RTP codec array aliases its inventory");
        Object pcmu = codec.getField("PCMU").get(null);
        check(codec.getField("type").getInt(pcmu) == 0, "PCMU payload differs");
        check(call(codec, null, "getCodec", new Class<?>[]{int.class, String.class, String.class}, 0, null, null) != null, "PCMU selection failed");
        check(call(codec, null, "getCodec", new Class<?>[]{int.class, String.class, String.class}, 128, null, null) == null, "Invalid RTP payload accepted");
        check(call(codec, null, "getCodec", new Class<?>[]{int.class, String.class, String.class}, 97, "AMR/8000", "crc=1") == null, "Unsupported AMR mode accepted");
        InetAddress local = InetAddress.getByName("127.0.0.1");
        Class<?> streamType = type("Landroid/net/rtp/AudioStream;");
        Object stream = streamType.getConstructor(InetAddress.class).newInstance(local);
        int port = (Integer) get(stream, "getLocalPort");
        try {
            check(port > 0 && port % 2 == 0, "RTP socket port differs " + port);
            check(local.equals(get(stream, "getLocalAddress")), "RTP local address differs");
            try (DatagramSocket competing = new DatagramSocket(null)) {
                try {
                    competing.bind(new InetSocketAddress(local, port));
                    throw new AssertionError("Native RTP socket did not reserve its port");
                } catch (BindException expected) {}
            }
            call(streamType, stream, "associate", new Class<?>[]{InetAddress.class, int.class}, local, 5004);
            call(streamType, stream, "setMode", new Class<?>[]{int.class}, 1);
            call(streamType, stream, "setCodec", new Class<?>[]{codec}, pcmu);
            call(streamType, stream, "setDtmfType", new Class<?>[]{int.class}, 101);
            check(Integer.valueOf(5004).equals(get(stream, "getRemotePort")) && local.equals(get(stream, "getRemoteAddress")), "RTP remote endpoint differs");
            check(Integer.valueOf(1).equals(get(stream, "getMode")) && Integer.valueOf(101).equals(get(stream, "getDtmfType")), "RTP configuration differs");
            check(pcmu == get(stream, "getCodec") && Boolean.FALSE.equals(get(stream, "isBusy")), "RTP stream state differs");
            try {
                call(streamType, stream, "setMode", new Class<?>[]{int.class}, 3);
                throw new AssertionError("Invalid RTP mode accepted");
            } catch (IllegalArgumentException expected) {}
        } finally { call(streamType, stream, "release", new Class<?>[0]); }
        try (DatagramSocket released = new DatagramSocket(null)) {
            released.bind(new InetSocketAddress(local, port));
        }
        Object group = type("Landroid/net/rtp/AudioGroup;").getConstructor().newInstance();
        check(((Object[]) get(group, "getStreams")).length == 0, "New RTP group contains streams");
        check(Integer.valueOf(0).equals(get(group, "getMode")), "New RTP group mode differs");
        call(group.getClass(), group, "clear", new Class<?>[0]);
        System.out.println("API28_RTP_JNI=PASS|socket=true|port_released=true|codecs=" + first.length);
    }

    public static void run(String group) throws Throwable {
        switch (group) {
            case "api28-public-members": members(); return;
            case "sip-profile": sipProfile(); return;
            case "rtp-jni": rtp(); return;
            default: throw new IllegalArgumentException("Unknown public API group " + group);
        }
    }
}
