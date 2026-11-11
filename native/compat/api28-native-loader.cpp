#include <jni.h>
#include <stddef.h>
#include <string>

extern "C" {
void InitializeNativeLoader();
void ResetNativeLoader();
void* OpenNativeLibrary(JNIEnv*, int, const char*, jobject, const char*, jstring, bool*, char**);
void* OpenNativeLibraryInNamespace(void*, const char*, bool*, char**);
bool CloseNativeLibrary(void*, bool, char**);
void* FindNamespaceByClassLoader(JNIEnv*, jobject);
void* FindNativeLoaderNamespaceByClassLoader(JNIEnv*, jobject);
void NativeLoaderFreeErrorMessage(char*);
}

static void copy_error(std::string* destination, char* message) {
    if (destination) *destination = message ? message : "";
    if (message) NativeLoaderFreeErrorMessage(message);
}

namespace android {
class NativeLoaderNamespace;

void InitializeNativeLoader() { ::InitializeNativeLoader(); }
void ResetNativeLoader() { ::ResetNativeLoader(); }

jstring CreateClassLoaderNamespace(JNIEnv* env, int sdk, jobject loader, bool shared,
                                   bool vendor, jstring libraries, jstring permitted) {
    jclass type = env->FindClass("SdClassLoaderNamespaces");
    if (!type) return nullptr;
    jmethodID bind = env->GetStaticMethodID(type, "bindLegacy",
        "(Ljava/lang/ClassLoader;ILjava/lang/String;Ljava/lang/String;ZZ)Ljava/lang/String;");
    jstring error = bind ? static_cast<jstring>(env->CallStaticObjectMethod(
        type, bind, loader, sdk, libraries, permitted, shared, vendor)) : nullptr;
    env->DeleteLocalRef(type);
    return error;
}

void* OpenNativeLibrary(JNIEnv* env, int sdk, const char* path, jobject loader,
                        jstring libraries, bool* translated, std::string* error) {
    char* message = nullptr;
    void* handle = ::OpenNativeLibrary(env, sdk, path, loader, nullptr, libraries, translated, &message);
    copy_error(error, message);
    return handle;
}

void* OpenNativeLibrary(NativeLoaderNamespace* space, const char* path,
                        bool* translated, std::string* error) {
    char* message = nullptr;
    void* handle = ::OpenNativeLibraryInNamespace(space, path, translated, &message);
    copy_error(error, message);
    return handle;
}

bool CloseNativeLibrary(void* handle, bool translated, std::string* error) {
    char* message = nullptr;
    bool closed = ::CloseNativeLibrary(handle, translated, &message);
    copy_error(error, message);
    return closed;
}

void* FindNamespaceByClassLoader(JNIEnv* env, jobject loader) {
    return ::FindNamespaceByClassLoader(env, loader);
}

NativeLoaderNamespace* FindNativeLoaderNamespaceByClassLoader(JNIEnv* env, jobject loader) {
    return static_cast<NativeLoaderNamespace*>(::FindNativeLoaderNamespaceByClassLoader(env, loader));
}
}

