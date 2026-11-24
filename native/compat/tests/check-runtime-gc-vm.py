#!/usr/bin/env python3
"""Exercise API28 and API29 BlockGuard callbacks over the loaded JNI collector."""
from pathlib import Path
import shutil
import subprocess
import tempfile


repository = Path(__file__).resolve().parents[3]
jdk = Path(shutil.which("javac")).resolve().parents[1]
original = r'''
#include <jni.h>
static int collections;
JNIEXPORT void JNICALL Runtime_gc(JNIEnv *env, jobject runtime) {
    (void)env; (void)runtime; ++collections;
}
JNIEXPORT jint JNICALL Java_GcProbe_count(JNIEnv *env, jclass type) {
    (void)env; (void)type; return collections;
}
'''
entry = r'''
#include <jni.h>
JNIEXPORT void JNICALL Runtime_gc(JNIEnv *, jobject);
JNIEXPORT void JNICALL Java_GcProbe_collect(JNIEnv *env, jclass type) {
    (void)type;
    Runtime_gc(env, NULL);
}
'''
probe = r'''
import dalvik.system.BlockGuard;
public final class GcProbe {
    private static native void collect();
    private static native int count();
    public static void main(String[] arguments) {
        System.load(arguments[0]);
        System.load(arguments[1]);
        Throwable failure = null;
        try { collect(); } catch (Throwable error) { failure = error; }
        if (BlockGuard.FAILURE == null) {
            if (failure != null || count() != 1) throw new AssertionError("Collector was skipped", failure);
        } else {
            if (failure != BlockGuard.FAILURE || count() != 0) {
                throw new AssertionError("Policy exception or collector boundary changed", failure);
            }
        }
        if (BlockGuard.calls != BlockGuard.EXPECTED_CALLS) throw new AssertionError("Callback count differs");
        System.out.println("RUNTIME_GC=PASS|mode=" + arguments[2] + "|collections=" + count()
                + "|policy_calls=" + BlockGuard.calls);
    }
}
'''

variants = (
    ("api28", "", "", "null", 0),
    ("api29", "void onExplicitGc();", "public void onExplicitGc() { ++calls; }", "null", 1),
    ("api29-policy-failure", "void onExplicitGc();",
     "public void onExplicitGc() { ++calls; throw (RuntimeException)FAILURE; }",
     'new IllegalStateException("policy failure")', 1),
    ("api29-policy-method-error", "void onExplicitGc();",
     "public void onExplicitGc() { ++calls; throw (Error)FAILURE; }",
     'new NoSuchMethodError("callback failure")', 1),
)
with tempfile.TemporaryDirectory(prefix="saildroid-runtime-gc-") as temporary:
    folder = Path(temporary)
    (folder / "original.c").write_text(original)
    (folder / "entry.c").write_text(entry)
    flags = ["gcc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
             "-I" + str(jdk / "include"), "-I" + str(jdk / "include/linux")]
    subprocess.run(flags + [str(folder / "original.c"), "-Wl,-soname,libopenjdk.so",
                           "-o", str(folder / "libopenjdk.so")], check=True, timeout=60)
    subprocess.run(flags + [str(repository / "native/compat/runtime-policy/runtime-gc.c"),
                           str(folder / "entry.c"), "-ldl", "-o", str(folder / "policy.so")],
                   check=True, timeout=60)
    for name, declaration, implementation, failure, calls in variants:
        work = folder / name
        (work / "dalvik/system").mkdir(parents=True)
        guard = work / "dalvik/system/BlockGuard.java"
        guard.write_text("package dalvik.system;\npublic final class BlockGuard {\n"
                         + "public static int calls; public static final int EXPECTED_CALLS=" + str(calls) + ";\n"
                         + "public static final Throwable FAILURE=" + failure + ";\n"
                         + "public interface Policy { " + declaration + " }\n"
                         + "public static Policy getThreadPolicy() { return new Policy() { "
                         + implementation + " }; }\n}\n")
        (work / "GcProbe.java").write_text(probe)
        subprocess.run(["javac", "--release", "8", "-d", str(work), str(guard), str(work / "GcProbe.java")],
                       check=True, timeout=60)
        subprocess.run(["java", "-Xcheck:jni", "-cp", str(work), "GcProbe",
                        str(folder / "libopenjdk.so"), str(folder / "policy.so"), name],
                       check=True, timeout=15)
