/*
 * Runtime.gc policy boundary for the legacy OpenJDK JNI ABI.
 * Android10 Runtime.gc notifies BlockGuard before the real collector runs.
 * Keep the old public native signature and its original registration; forward
 * to the already-loaded original libopenjdk Runtime_gc implementation afterward.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <jni.h>

JNIEXPORT void JNICALL Runtime_gc(JNIEnv *env, jobject runtime)
{
    jclass guard = (*env)->FindClass(env, "dalvik/system/BlockGuard");
    if (guard == NULL) return;
    jmethodID get_policy = (*env)->GetStaticMethodID(
        env, guard, "getThreadPolicy", "()Ldalvik/system/BlockGuard$Policy;");
    if (get_policy == NULL) {
        (*env)->DeleteLocalRef(env, guard);
        return;
    }
    jobject policy = (*env)->CallStaticObjectMethod(env, guard, get_policy);
    (*env)->DeleteLocalRef(env, guard);
    if ((*env)->ExceptionCheck(env)) return;
    jclass policy_class = (*env)->FindClass(env, "dalvik/system/BlockGuard$Policy");
    if (policy_class == NULL) {
        (*env)->DeleteLocalRef(env, policy);
        return;
    }
    jclass missing_method = (*env)->FindClass(env, "java/lang/NoSuchMethodError");
    if (missing_method == NULL) {
        (*env)->DeleteLocalRef(env, policy_class);
        (*env)->DeleteLocalRef(env, policy);
        return;
    }
    jmethodID explicit_gc = (*env)->GetMethodID(env, policy_class, "onExplicitGc", "()V");
    (*env)->DeleteLocalRef(env, policy_class);
    if (explicit_gc == NULL) {
        /* API28's Policy has no explicit-GC callback. Clear only the lookup's
         * missing-method failure and restore every other pending exception. */
        jthrowable failure = (*env)->ExceptionOccurred(env);
        if (failure != NULL) {
            (*env)->ExceptionClear(env);
            if (!(*env)->IsInstanceOf(env, failure, missing_method)) {
                (*env)->Throw(env, failure);
            }
            (*env)->DeleteLocalRef(env, failure);
        }
    }
    (*env)->DeleteLocalRef(env, missing_method);
    if (explicit_gc != NULL) (*env)->CallVoidMethod(env, policy, explicit_gc);
    (*env)->DeleteLocalRef(env, policy);
    if ((*env)->ExceptionCheck(env)) return;

    /* NOLOAD forbids loading a different backend as a recovery fallback. */
    void *library = dlopen("libopenjdk.so", RTLD_NOW | RTLD_NOLOAD);
    void (*original)(JNIEnv *, jobject) = library
        ? (void (*)(JNIEnv *, jobject))dlsym(library, "Runtime_gc") : NULL;
    if (original == NULL || original == Runtime_gc) {
        if (library != NULL) dlclose(library);
        jclass error = (*env)->FindClass(env, "java/lang/UnsatisfiedLinkError");
        if (error != NULL) {
            (*env)->ThrowNew(env, error, "Original loaded libopenjdk Runtime_gc is unavailable");
            (*env)->DeleteLocalRef(env, error);
        }
        return;
    }
    original(env, runtime);
    dlclose(library);
}
