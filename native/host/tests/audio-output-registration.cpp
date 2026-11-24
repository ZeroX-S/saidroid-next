#include <jni.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <map>
#include <stdexcept>
#include <string>

extern "C" void Java_SdAudio_nativeInstall(JNIEnv*, jclass, jclass);

namespace {
_jclass bridge, audio_system, audio_track, port_handler;
std::map<jclass, std::map<std::string, JNINativeMethod>> registrations;
int sampling_rate = 48000;
int frame_count = 0;
bool backend_exception = false;
bool pending_exception = false;
int calls = 0;

void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

jobject JNICALL global_ref(JNIEnv*, jobject value) { return value; }
jclass JNICALL find_class(JNIEnv*, const char *name) {
    if (!std::strcmp(name, "android/media/AudioSystem")) return &audio_system;
    if (!std::strcmp(name, "android/media/AudioPortEventHandler")) return &port_handler;
    throw std::runtime_error("Unexpected JNI class lookup");
}
jint JNICALL register_natives(JNIEnv*, jclass owner, const JNINativeMethod *methods, jint count) {
    for (int i = 0; i < count; ++i) registrations[owner][methods[i].name] = methods[i];
    return JNI_OK;
}
jmethodID JNICALL static_method(JNIEnv*, jclass owner, const char *name, const char *signature) {
    check(owner == &bridge, "Output getter bypassed the existing Java backend");
    check(!std::strcmp(signature, "()I"), "Output getter JNI signature changed");
    if (!std::strcmp(name, "primaryOutputSamplingRate")) return reinterpret_cast<jmethodID>(1);
    if (!std::strcmp(name, "primaryOutputFrameCount")) return reinterpret_cast<jmethodID>(2);
    throw std::runtime_error("Unexpected Java backend getter");
}
jint JNICALL call_static_int(JNIEnv*, jclass owner, jmethodID method, va_list) {
    check(owner == &bridge, "Output callback owner changed");
    ++calls;
    if (backend_exception) {
        pending_exception = true;
        return 0;
    }
    return method == reinterpret_cast<jmethodID>(1) ? sampling_rate : frame_count;
}
jint call(JNIEnv *env, jclass owner, const char *name) {
    const auto &methods = registrations.at(owner);
    auto found = methods.find(name);
    check(found != methods.end(), "Missing primary output JNI registration");
    check(!std::strcmp(found->second.signature, "()I"), "Native output signature changed");
    using Getter = jint (JNICALL *)(JNIEnv*, jclass);
    return reinterpret_cast<Getter>(found->second.fnPtr)(env, owner);
}
}

int main() {
    try {
        JNINativeInterface_ functions{};
        functions.NewGlobalRef = global_ref;
        functions.FindClass = find_class;
        functions.RegisterNatives = register_natives;
        functions.GetStaticMethodID = static_method;
        functions.CallStaticIntMethodV = call_static_int;
        JNIEnv environment{&functions};
        Java_SdAudio_nativeInstall(&environment, &bridge, &audio_track);
        check(registrations[&audio_track].size() == 1,
              "API28 AudioTrack channel registration changed");
        check(registrations[&audio_system].size() == 6,
              "Missing primary output JNI registration");
        check(!registrations[&audio_system].count("native_get_FCC_8"),
              "API28 channel getter was moved to AudioSystem");
        check(call(&environment, &audio_track, "native_get_FCC_8") == 8,
              "Channel constant callback changed");
        check(call(&environment, &audio_system, "getPrimaryOutputSamplingRate") == 48000,
              "Sampling-rate callback failed");
        sampling_rate = 44100;
        check(call(&environment, &audio_system, "getPrimaryOutputSamplingRate") == 44100,
              "Sampling-rate callback substituted a fixed value");
        check(call(&environment, &audio_system, "getPrimaryOutputFrameCount") == 0,
              "Unavailable frame count callback changed");
        backend_exception = true;
        check(call(&environment, &audio_system, "getPrimaryOutputSamplingRate") == 0 && pending_exception,
              "Java backend exception was discarded");
        check(calls == 4 && registrations[&port_handler].size() == 2,
              "Existing callback registration changed");
        backend_exception = false;
        pending_exception = false;
        registrations.clear();
        Java_SdAudio_nativeInstall(&environment, &bridge, &audio_system);
        check(registrations[&audio_system].size() == 7 && registrations[&audio_track].empty(),
              "API29 channel owner compatibility changed");
        check(call(&environment, &audio_system, "native_get_FCC_8") == 8,
              "API29 channel constant callback changed");
        std::puts("AUDIO_OUTPUT_REGISTRATION=PASS|cases=6");
        return 0;
    } catch (const std::exception &failure) {
        std::fprintf(stderr, "AUDIO_OUTPUT_REGISTRATION=FAIL|%s\n", failure.what());
        return 1;
    }
}
