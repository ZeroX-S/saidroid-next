#include <jni.h>
#include <pulse/pulseaudio.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace {
constexpr jint bad_value = -2;
constexpr jint invalid_operation = -3;
constexpr jint dead_object = -6;
jfieldID recorder_field;
jclass authorization_class;
jmethodID authorize_method;

pa_sample_format_t sample_format(jint encoding) {
    switch (encoding) {
    case 2: return PA_SAMPLE_S16LE;
    case 3: return PA_SAMPLE_U8;
    case 4: return PA_SAMPLE_FLOAT32LE;
    default: return PA_SAMPLE_INVALID;
    }
}

unsigned channel_count(jint mask, jint index_mask = 0) {
    if (index_mask) return index_mask == 1 ? 1 : index_mask == 3 ? 2 : 0;
    return mask == 16 || mask == 1 ? 1 : mask == 12 ? 2 : 0;
}

std::string authorize(JNIEnv *env) {
    auto name = static_cast<jstring>(env->CallStaticObjectMethod(authorization_class, authorize_method));
    if (env->ExceptionCheck() || !name) return {};
    const char *text = env->GetStringUTFChars(name, nullptr);
    if (!text) { env->DeleteLocalRef(name); return {}; }
    std::string result(text);
    env->ReleaseStringUTFChars(name, text);
    env->DeleteLocalRef(name);
    return result;
}

struct Recorder {
    pa_mainloop *loop = nullptr;
    pa_context *context = nullptr;
    pa_stream *stream = nullptr;
    pa_sample_spec specification;
    std::string source;
    const jint encoding;
    const jint buffer_bytes;
    std::atomic<bool> recording{false};
    std::atomic<bool> released{false};
    std::mutex mutex;

    Recorder(pa_sample_spec spec, std::string name, jint format, jint bytes)
        : specification(spec), source(std::move(name)), encoding(format), buffer_bytes(bytes) {}

    ~Recorder() {
        disconnect();
    }

    void disconnect_stream() {
        if (stream) { pa_stream_disconnect(stream); pa_stream_unref(stream); stream = nullptr; }
        peek_offset = 0;
    }

    void disconnect() {
        disconnect_stream();
        if (context) { pa_context_disconnect(context); pa_context_unref(context); context = nullptr; }
        if (loop) { pa_mainloop_free(loop); loop = nullptr; }
    }

    bool connect() {
        if (context && pa_context_get_state(context) == PA_CONTEXT_READY) return true;
        disconnect();
        loop = pa_mainloop_new();
        if (!loop) return false;
        context = pa_context_new(pa_mainloop_get_api(loop), "SailDroid microphone");
        if (!context || pa_context_connect(context, nullptr, PA_CONTEXT_NOAUTOSPAWN, nullptr) < 0) return false;
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (pa_context_get_state(context) != PA_CONTEXT_READY) {
            if (!PA_CONTEXT_IS_GOOD(pa_context_get_state(context)) || std::chrono::steady_clock::now() >= deadline) return false;
            pa_mainloop_iterate(loop, 0, nullptr);
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        return true;
    }

    jint start(const std::string &selected_source) {
        std::lock_guard<std::mutex> lock(mutex);
        if (released) return invalid_operation;
        if (recording) return 0;
        source = selected_source;
        if (!connect()) return dead_object;
        disconnect_stream();
        pa_proplist *properties = pa_proplist_new();
        if (!properties) return dead_object;
        pa_proplist_sets(properties, PA_PROP_MEDIA_ROLE, "production");
        stream = pa_stream_new_with_proplist(context, "Application microphone", &specification, nullptr, properties);
        pa_proplist_free(properties);
        if (!stream) return dead_object;
        pa_buffer_attr attributes = {static_cast<uint32_t>(-1), static_cast<uint32_t>(-1),
                                    static_cast<uint32_t>(-1), static_cast<uint32_t>(-1),
                                    static_cast<uint32_t>(buffer_bytes)};
        auto flags = static_cast<pa_stream_flags_t>(PA_STREAM_ADJUST_LATENCY | PA_STREAM_DONT_MOVE);
        if (pa_stream_connect_record(stream, source.c_str(), &attributes, flags) < 0) {
            disconnect_stream();
            return dead_object;
        }
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (pa_stream_get_state(stream) != PA_STREAM_READY) {
            if (!PA_STREAM_IS_GOOD(pa_stream_get_state(stream)) || std::chrono::steady_clock::now() >= deadline) {
                disconnect_stream();
                return dead_object;
            }
            pa_mainloop_iterate(loop, 0, nullptr);
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        recording = true;
        return 0;
    }

    void stop() {
        // A blocking reader observes cancellation before stop waits for its lock.
        recording = false;
        std::lock_guard<std::mutex> lock(mutex);
        recording = false;
        disconnect_stream();
    }

    jint read(void *destination, size_t requested, bool blocking) {
        std::lock_guard<std::mutex> lock(mutex);
        if (!recording || !stream) return 0;
        const size_t frame_size = pa_frame_size(&specification);
        requested -= requested % frame_size;
        size_t copied = 0;
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (copied < requested && recording) {
            pa_mainloop_iterate(loop, 0, nullptr);
            if (pa_context_get_state(context) != PA_CONTEXT_READY || pa_stream_get_state(stream) != PA_STREAM_READY)
                return copied ? static_cast<jint>(copied) : dead_object;
            const void *data = nullptr;
            size_t available = 0;
            if (pa_stream_peek(stream, &data, &available) < 0) return copied ? static_cast<jint>(copied) : dead_object;
            if (!available) {
                if (!blocking || std::chrono::steady_clock::now() >= deadline) break;
                std::this_thread::sleep_for(std::chrono::milliseconds(2));
                continue;
            }
            if (available % frame_size || peek_offset >= available) return copied ? static_cast<jint>(copied) : dead_object;
            // PulseAudio peek blocks cannot be partially dropped. Retain their
            // unread bytes until a later Android read consumes them.
            size_t count = std::min(available - peek_offset, requested - copied);
            if (data) std::memcpy(static_cast<char *>(destination) + copied, static_cast<const char *>(data) + peek_offset, count);
            else std::memset(static_cast<char *>(destination) + copied, specification.format == PA_SAMPLE_U8 ? 128 : 0, count);
            copied += count;
            peek_offset += count;
            if (peek_offset == available) {
                if (pa_stream_drop(stream) < 0) return static_cast<jint>(copied);
                peek_offset = 0;
            }
            deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        }
        return static_cast<jint>(copied);
    }

    size_t peek_offset = 0;
};

std::mutex registry_mutex;
std::map<jlong, std::shared_ptr<Recorder>> recorders;
std::atomic<jlong> next_handle{1};

std::shared_ptr<Recorder> recorder(JNIEnv *env, jobject owner) {
    std::lock_guard<std::mutex> lock(registry_mutex);
    auto found = recorders.find(env->GetLongField(owner, recorder_field));
    return found == recorders.end() ? nullptr : found->second;
}

jint setup(JNIEnv *env, jobject owner, jobject, jobject attributes, jintArray rates, jint mask,
           jint index_mask, jint encoding, jint buffer_bytes, jintArray sessions, jstring, jlong native_handle) {
    if (native_handle || !attributes || !rates || !sessions || env->GetArrayLength(rates) != 1 || env->GetArrayLength(sessions) != 1)
        return bad_value;
    auto format = sample_format(encoding);
    unsigned channels = channel_count(mask, index_mask);
    jint rate = 0, session = 0;
    env->GetIntArrayRegion(rates, 0, 1, &rate);
    env->GetIntArrayRegion(sessions, 0, 1, &session);
    if (format == PA_SAMPLE_INVALID || !channels || rate < 0 || session < 0 || buffer_bytes <= 0) return bad_value;
    auto attributes_class = env->GetObjectClass(attributes);
    jfieldID source_field = env->GetFieldID(attributes_class, "mSource", "I");
    env->DeleteLocalRef(attributes_class);
    if (!source_field) return bad_value;
    jint audio_source = env->GetIntField(attributes, source_field);
    if (audio_source != 0 && audio_source != 1 && audio_source != 5 && audio_source != 6 && audio_source != 7 && audio_source != 9)
        return bad_value;
    auto source = authorize(env);
    if (env->ExceptionCheck() || source.empty()) return invalid_operation;
    pa_sample_spec spec = {format, static_cast<uint32_t>(rate ? rate : 48000), static_cast<uint8_t>(channels)};
    if (!pa_sample_spec_valid(&spec) || buffer_bytes % pa_frame_size(&spec)) return bad_value;
    try {
        auto value = std::make_shared<Recorder>(spec, source, encoding, buffer_bytes);
        jlong handle = next_handle++;
        std::lock_guard<std::mutex> lock(registry_mutex);
        if (env->GetLongField(owner, recorder_field)) return invalid_operation;
        recorders.emplace(handle, std::move(value));
        env->SetLongField(owner, recorder_field, handle);
        rate = spec.rate;
        if (!session) session = static_cast<jint>(handle & 0x7fffffff);
        env->SetIntArrayRegion(rates, 0, 1, &rate);
        env->SetIntArrayRegion(sessions, 0, 1, &session);
        return 0;
    } catch (const std::exception &) { return -20; }
}

void release(JNIEnv *env, jobject owner) {
    std::shared_ptr<Recorder> value;
    {
        std::lock_guard<std::mutex> lock(registry_mutex);
        auto found = recorders.find(env->GetLongField(owner, recorder_field));
        env->SetLongField(owner, recorder_field, 0);
        if (found == recorders.end()) return;
        value = found->second;
        value->released = true;
        recorders.erase(found);
    }
    value->stop();
}

jint start(JNIEnv *env, jobject owner, jint event, jint session) {
    if (event || session) return invalid_operation;
    auto value = recorder(env, owner);
    if (!value) return invalid_operation;
    std::string source = authorize(env);
    if (source.empty()) { value->stop(); return invalid_operation; }
    return value->start(source);
}

void stop(JNIEnv *env, jobject owner) { auto value = recorder(env, owner); if (value) value->stop(); }

bool bounds(JNIEnv *env, jarray array, jint offset, jint count) {
    return array && offset >= 0 && count >= 0 && offset <= env->GetArrayLength(array) && count <= env->GetArrayLength(array) - offset;
}

template<class Array, class Sample>
jint read_array(JNIEnv *env, jobject owner, Array array, jint offset, jint count, jboolean blocking, jint required_format) {
    if (!bounds(env, array, offset, count)) return bad_value;
    auto value = recorder(env, owner);
    if (!value || (required_format && value->encoding != required_format)
            || (!required_format && value->encoding == 4)) return invalid_operation;
    if (authorize(env).empty()) { value->stop(); return invalid_operation; }
    try {
        size_t bytes = std::min<size_t>(static_cast<size_t>(count) * sizeof(Sample), 65536);
        std::vector<Sample> data(bytes / sizeof(Sample));
        jint result = value->read(data.data(), bytes, blocking);
        if (result <= 0) return result;
        jint samples = result / sizeof(Sample);
        if constexpr (sizeof(Sample) == 1) env->SetByteArrayRegion(array, offset, samples, reinterpret_cast<jbyte *>(data.data()));
        else if constexpr (sizeof(Sample) == 2) env->SetShortArrayRegion(array, offset, samples, reinterpret_cast<jshort *>(data.data()));
        else env->SetFloatArrayRegion(array, offset, samples, reinterpret_cast<jfloat *>(data.data()));
        return samples;
    } catch (const std::exception &) { return dead_object; }
}

jint read_bytes(JNIEnv *env, jobject owner, jbyteArray array, jint offset, jint count, jboolean blocking) {
    return read_array<jbyteArray, jbyte>(env, owner, array, offset, count, blocking, 0);
}
jint read_shorts(JNIEnv *env, jobject owner, jshortArray array, jint offset, jint count, jboolean blocking) {
    return read_array<jshortArray, jshort>(env, owner, array, offset, count, blocking, 2);
}
jint read_floats(JNIEnv *env, jobject owner, jfloatArray array, jint offset, jint count, jboolean blocking) {
    return read_array<jfloatArray, jfloat>(env, owner, array, offset, count, blocking, 4);
}
jint read_buffer(JNIEnv *env, jobject owner, jobject buffer, jint count, jboolean blocking) {
    if (!buffer || count < 0) return bad_value;
    void *address = env->GetDirectBufferAddress(buffer);
    jlong capacity = env->GetDirectBufferCapacity(buffer);
    if (!address || capacity < 0) return 0;
    auto value = recorder(env, owner);
    if (!value) return invalid_operation;
    if (authorize(env).empty()) { value->stop(); return invalid_operation; }
    return value->read(address, std::min<jlong>({count, capacity, 65536}), blocking);
}
jint buffer_frames(JNIEnv *env, jobject owner) {
    auto value = recorder(env, owner);
    return value ? value->buffer_bytes / pa_frame_size(&value->specification) : invalid_operation;
}
jint min_buffer(JNIEnv *, jclass, jint rate, jint channels, jint encoding) {
    pa_sample_spec spec = {sample_format(encoding), static_cast<uint32_t>(rate), static_cast<uint8_t>(channels)};
    if (!pa_sample_spec_valid(&spec) || channels < 1 || channels > 2) return bad_value;
    return static_cast<jint>(std::max<uint32_t>(1, spec.rate / 25) * pa_frame_size(&spec));
}
jint no_position(JNIEnv *, jobject) { return 0; }
jint set_position(JNIEnv *, jobject, jint) { return invalid_operation; }
jboolean input_device(JNIEnv *, jobject, jint) { return JNI_FALSE; }
jint routed_device(JNIEnv *env, jobject owner) {
    auto value = recorder(env, owner);
    if (!value) return 0;
    std::lock_guard<std::mutex> lock(value->mutex);
    return value->recording && value->stream ? static_cast<jint>(pa_stream_get_device_index(value->stream) + 0x10000) : 0;
}
void device_callback(JNIEnv *, jobject) {}
jint timestamp(JNIEnv *, jobject, jobject, jint) { return invalid_operation; }
jint microphones(JNIEnv *, jobject, jobject) { return invalid_operation; }
jobject metrics(JNIEnv *env, jobject) {
    auto type = env->FindClass("android/os/PersistableBundle");
    auto value = env->NewObject(type, env->GetMethodID(type, "<init>", "()V"));
    env->DeleteLocalRef(type);
    return value;
}
}

extern "C" JNIEXPORT void JNICALL Java_SdAudioRecord_nativeInstall(JNIEnv *env, jclass authorization) {
    authorization_class = static_cast<jclass>(env->NewGlobalRef(authorization));
    authorize_method = env->GetStaticMethodID(authorization, "authorize", "()Ljava/lang/String;");
    auto type = env->FindClass("android/media/AudioRecord");
    if (!type || !authorize_method) return;
    recorder_field = env->GetFieldID(type, "mNativeRecorderInJavaObj", "J");
    if (!recorder_field) return;
    JNINativeMethod methods[] = {
        {const_cast<char *>("native_setup"), const_cast<char *>("(Ljava/lang/Object;Ljava/lang/Object;[IIIII[ILjava/lang/String;J)I"), reinterpret_cast<void *>(setup)},
        {const_cast<char *>("native_release"), const_cast<char *>("()V"), reinterpret_cast<void *>(release)},
        {const_cast<char *>("native_finalize"), const_cast<char *>("()V"), reinterpret_cast<void *>(release)},
        {const_cast<char *>("native_start"), const_cast<char *>("(II)I"), reinterpret_cast<void *>(start)},
        {const_cast<char *>("native_stop"), const_cast<char *>("()V"), reinterpret_cast<void *>(stop)},
        {const_cast<char *>("native_read_in_byte_array"), const_cast<char *>("([BIIZ)I"), reinterpret_cast<void *>(read_bytes)},
        {const_cast<char *>("native_read_in_short_array"), const_cast<char *>("([SIIZ)I"), reinterpret_cast<void *>(read_shorts)},
        {const_cast<char *>("native_read_in_float_array"), const_cast<char *>("([FIIZ)I"), reinterpret_cast<void *>(read_floats)},
        {const_cast<char *>("native_read_in_direct_buffer"), const_cast<char *>("(Ljava/lang/Object;IZ)I"), reinterpret_cast<void *>(read_buffer)},
        {const_cast<char *>("native_get_buffer_size_in_frames"), const_cast<char *>("()I"), reinterpret_cast<void *>(buffer_frames)},
        {const_cast<char *>("native_get_min_buff_size"), const_cast<char *>("(III)I"), reinterpret_cast<void *>(min_buffer)},
        {const_cast<char *>("native_set_marker_pos"), const_cast<char *>("(I)I"), reinterpret_cast<void *>(set_position)},
        {const_cast<char *>("native_get_marker_pos"), const_cast<char *>("()I"), reinterpret_cast<void *>(no_position)},
        {const_cast<char *>("native_set_pos_update_period"), const_cast<char *>("(I)I"), reinterpret_cast<void *>(set_position)},
        {const_cast<char *>("native_get_pos_update_period"), const_cast<char *>("()I"), reinterpret_cast<void *>(no_position)},
        {const_cast<char *>("native_setInputDevice"), const_cast<char *>("(I)Z"), reinterpret_cast<void *>(input_device)},
        {const_cast<char *>("native_getRoutedDeviceId"), const_cast<char *>("()I"), reinterpret_cast<void *>(routed_device)},
        {const_cast<char *>("native_enableDeviceCallback"), const_cast<char *>("()V"), reinterpret_cast<void *>(device_callback)},
        {const_cast<char *>("native_disableDeviceCallback"), const_cast<char *>("()V"), reinterpret_cast<void *>(device_callback)},
        {const_cast<char *>("native_get_timestamp"), const_cast<char *>("(Landroid/media/AudioTimestamp;I)I"), reinterpret_cast<void *>(timestamp)},
        {const_cast<char *>("native_get_active_microphones"), const_cast<char *>("(Ljava/util/ArrayList;)I"), reinterpret_cast<void *>(microphones)},
        {const_cast<char *>("native_getMetrics"), const_cast<char *>("()Landroid/os/PersistableBundle;"), reinterpret_cast<void *>(metrics)}
    };
    env->RegisterNatives(type, methods, sizeof(methods) / sizeof(methods[0]));
    env->DeleteLocalRef(type);
}
