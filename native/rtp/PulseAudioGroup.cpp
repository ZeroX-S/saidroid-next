#include <jni.h>
#include <pulse/pulseaudio.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <system_error>
#include <thread>
#include <vector>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <arpa/inet.h>
#include "AudioCodec.h"
#include "EchoSuppressor.h"
#include "rtp-log.h"

AudioCodec *newUlawCodec();
AudioCodec *newAlawCodec();

namespace {
int elapsedRealtime() {
    timespec value{};
    clock_gettime(CLOCK_BOOTTIME, &value);
    return static_cast<int>(value.tv_sec * 1000 + value.tv_nsec / 1000000);
}

#include "rtp-stream.inc"

constexpr int sample_rate = 8000;
constexpr size_t sample_count = 256;
constexpr size_t frame_bytes = sample_count * sizeof(int16_t);
jfieldID native_field;
jfieldID mode_field;
jclass authorization_class;
jmethodID authorize_method;

void fail(JNIEnv *env, const char *type, const char *message) {
    env->ThrowNew(env->FindClass(type), message);
}

std::string string(JNIEnv *env, jstring value) {
    if (!value) return {};
    const char *text = env->GetStringUTFChars(value, nullptr);
    if (!text) return {};
    std::string result(text);
    env->ReleaseStringUTFChars(value, text);
    return result;
}

std::string authorize(JNIEnv *env, const std::string &owner) {
    jstring package = env->NewStringUTF(owner.c_str());
    auto name = static_cast<jstring>(env->CallStaticObjectMethod(authorization_class, authorize_method, package));
    env->DeleteLocalRef(package);
    if (env->ExceptionCheck() || !name) return {};
    std::string result = string(env, name);
    env->DeleteLocalRef(name);
    return result;
}

/** One PulseAudio connection, owned by the call's device thread. */
class PulseDevice {
public:
    ~PulseDevice() {
        if (capture) { pa_stream_disconnect(capture); pa_stream_unref(capture); }
        if (playback) { pa_stream_disconnect(playback); pa_stream_unref(playback); }
        if (context) { pa_context_disconnect(context); pa_context_unref(context); }
        if (loop) pa_mainloop_free(loop);
    }

    bool connect(const std::string &source, bool microphone) {
        loop = pa_mainloop_new();
        if (!loop) return false;
        context = pa_context_new(pa_mainloop_get_api(loop), "SailDroid SIP");
        if (!context || pa_context_connect(context, nullptr, PA_CONTEXT_NOAUTOSPAWN, nullptr) < 0) return false;
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (pa_context_get_state(context) != PA_CONTEXT_READY) {
            if (!PA_CONTEXT_IS_GOOD(pa_context_get_state(context)) || std::chrono::steady_clock::now() >= deadline) return false;
            iterate();
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        pa_sample_spec spec = {PA_SAMPLE_S16LE, sample_rate, 1};
        pa_proplist *properties = pa_proplist_new();
        if (!properties) return false;
        pa_proplist_sets(properties, PA_PROP_MEDIA_ROLE, "voip");
        pa_proplist_sets(properties, PA_PROP_APPLICATION_NAME, "SailDroid SIP");
        playback = pa_stream_new_with_proplist(context, "SIP call playback", &spec, nullptr, properties);
        if (microphone) capture = pa_stream_new_with_proplist(context, "SIP call capture", &spec, nullptr, properties);
        pa_proplist_free(properties);
        if (!playback || (microphone && !capture)) return false;
        pa_buffer_attr attributes = {frame_bytes * 6, frame_bytes * 3, frame_bytes, frame_bytes, frame_bytes};
        auto flags = static_cast<pa_stream_flags_t>(PA_STREAM_ADJUST_LATENCY | PA_STREAM_AUTO_TIMING_UPDATE);
        if (pa_stream_connect_playback(playback, nullptr, &attributes, flags, nullptr, nullptr) < 0) return false;
        if (capture && pa_stream_connect_record(capture, source.c_str(), &attributes,
                static_cast<pa_stream_flags_t>(flags | PA_STREAM_DONT_MOVE)) < 0) return false;
        deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (pa_stream_get_state(playback) != PA_STREAM_READY || (capture && pa_stream_get_state(capture) != PA_STREAM_READY)) {
            if (!PA_STREAM_IS_GOOD(pa_stream_get_state(playback)) || (capture && !PA_STREAM_IS_GOOD(pa_stream_get_state(capture)))
                    || std::chrono::steady_clock::now() >= deadline) return false;
            iterate();
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        return true;
    }

    bool active() {
        iterate();
        return pa_context_get_state(context) == PA_CONTEXT_READY
                && pa_stream_get_state(playback) == PA_STREAM_READY
                && (!capture || pa_stream_get_state(capture) == PA_STREAM_READY);
    }

    bool write(const int16_t *samples) {
        size_t available = pa_stream_writable_size(playback);
        if (available == static_cast<size_t>(-1)) return false;
        if (available < frame_bytes) return true;
        return pa_stream_write(playback, samples, frame_bytes, nullptr, 0, PA_SEEK_RELATIVE) >= 0;
    }

    bool read(int16_t *samples) {
        std::memset(samples, 0, frame_bytes);
        if (!capture) return true;
        size_t copied = 0;
        while (copied < frame_bytes) {
            const void *data = nullptr;
            size_t available = 0;
            if (pa_stream_peek(capture, &data, &available) < 0) return false;
            if (!available) break;
            if (offset >= available) return false;
            size_t count = std::min(available - offset, frame_bytes - copied);
            if (data) std::memcpy(reinterpret_cast<char *>(samples) + copied, static_cast<const char *>(data) + offset, count);
            copied += count;
            offset += count;
            if (offset == available) {
                if (pa_stream_drop(capture) < 0) return false;
                offset = 0;
            }
        }
        return true;
    }

private:
    void iterate() { pa_mainloop_iterate(loop, 0, nullptr); }
    pa_mainloop *loop = nullptr;
    pa_context *context = nullptr;
    pa_stream *playback = nullptr;
    pa_stream *capture = nullptr;
    size_t offset = 0;
};

/** AOSP RTP mixing with PulseAudio replacing Android's native audio service. */
class AudioGroup {
public:
    explicit AudioGroup(std::string package) : owner(std::move(package)) { }
    ~AudioGroup() {
        stopDevice();
        stopNetwork();
        if (events >= 0) close(events);
        if (device_socket >= 0) close(device_socket);
        while (chain) {
            AudioStream *next = chain->mNext;
            delete chain;
            chain = next;
        }
    }

    bool initialize() {
        events = epoll_create1(EPOLL_CLOEXEC);
        if (events < 0) return false;
        int sockets[2];
        if (socketpair(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0, sockets) < 0) return false;
        device_socket = sockets[0];
        chain = new AudioStream;
        if (!chain->set(0, sockets[1], nullptr, nullptr, sample_rate, sample_count, -1, -1)) {
            close(sockets[1]);
            return false;
        }
        epoll_event event{};
        event.events = EPOLLIN;
        event.data.ptr = chain;
        return epoll_ctl(events, EPOLL_CTL_ADD, chain->mSocket, &event) == 0;
    }

    bool setMode(int requested, const std::string &source) {
        if (requested < 0 || requested > 3) return false;
        if (requested == mode && (requested == 0 || device_running)) return true;
        std::unique_ptr<PulseDevice> candidate;
        if (requested != 0) {
            candidate.reset(new PulseDevice);
            if (!candidate->connect(source, requested != 1)) return false;
        }
        stopDevice();
        stopNetwork();
        char discarded;
        while (recv(device_socket, &discarded, 1, MSG_DONTWAIT) > 0) { }
        while (recv(chain->mSocket, &discarded, 1, MSG_DONTWAIT) > 0) { }
        chain->mBufferHead = chain->mBufferTail = elapsedRealtime();
        mode = requested;
        if (chain->mNext) startNetwork();
        if (candidate) {
            device = std::move(candidate);
            device_running = true;
            try { device_thread = std::thread(&AudioGroup::deviceLoop, this); }
            catch (const std::system_error &) { device_running = false; device.reset(); return false; }
        }
        ALOGD("mode|value=%d|backend=pulseaudio", mode);
        return true;
    }

    bool add(AudioStream *stream) {
        stopNetwork();
        epoll_event event{};
        event.events = EPOLLIN;
        event.data.ptr = stream;
        if (epoll_ctl(events, EPOLL_CTL_ADD, stream->mSocket, &event) != 0) {
            if (chain->mNext) startNetwork();
            return false;
        }
        stream->mNext = chain->mNext;
        chain->mNext = stream;
        if (!startNetwork()) {
            chain->mNext = stream->mNext;
            epoll_ctl(events, EPOLL_CTL_DEL, stream->mSocket, nullptr);
            return false;
        }
        return true;
    }

    bool remove(AudioStream *stream) {
        stopNetwork();
        for (AudioStream *previous = chain; previous && previous->mNext; previous = previous->mNext) {
            if (previous->mNext == stream) {
                epoll_ctl(events, EPOLL_CTL_DEL, stream->mSocket, nullptr);
                previous->mNext = stream->mNext;
                delete stream;
                break;
            }
        }
        if (!chain->mNext) return false;
        startNetwork();
        return true;
    }

    void sendDtmf(int event) { dtmf_event = event; }
    const std::string owner;

private:
    void stopNetwork() {
        network_running = false;
        if (network_thread.joinable()) network_thread.join();
    }

    bool startNetwork() {
        network_running = true;
        try { network_thread = std::thread(&AudioGroup::networkLoop, this); }
        catch (const std::system_error &) { network_running = false; return false; }
        return true;
    }

    void stopDevice() {
        device_running = false;
        if (device_thread.joinable()) device_thread.join();
        device.reset();
    }

    void networkLoop() {
        std::vector<epoll_event> ready;
        for (AudioStream *stream = chain; stream; stream = stream->mNext) ready.emplace_back();
        while (network_running) {
            int tick = elapsedRealtime();
            int deadline = tick + 10;
            for (AudioStream *stream = chain; stream; stream = stream->mNext) {
                if (tick - stream->mTick >= 0) stream->encode(tick, chain);
                if (deadline - stream->mTick > 0) deadline = stream->mTick;
            }
            int event = dtmf_event.exchange(-1);
            if (event >= 0) {
                for (AudioStream *stream = chain; stream; stream = stream->mNext) stream->sendDtmf(event);
            }
            int count = epoll_wait(events, ready.data(), ready.size(), std::max(1, deadline - tick));
            if (count < 0) { if (errno == EINTR) continue; break; }
            for (int index = 0; index < count; ++index) static_cast<AudioStream *>(ready[index].data.ptr)->decode(tick);
        }
        network_running = false;
    }

    void deviceLoop() {
        std::unique_ptr<EchoSuppressor> echo;
        if (mode == 3) echo.reset(new EchoSuppressor(sample_count, sample_rate / 10));
        auto next = std::chrono::steady_clock::now();
        while (device_running && device->active()) {
            int16_t output[sample_count]{};
            int16_t input[sample_count]{};
            recv(device_socket, output, frame_bytes, MSG_DONTWAIT);
            if (!device->write(output) || !device->read(input)) break;
            if (mode != 1) {
                if (echo) echo->run(output, input);
                send(device_socket, input, frame_bytes, MSG_DONTWAIT);
            }
            next += std::chrono::milliseconds(sample_count * 1000 / sample_rate);
            auto now = std::chrono::steady_clock::now();
            if (now > next + std::chrono::milliseconds(64)) next = now;
            std::this_thread::sleep_until(next);
        }
        device_running = false;
    }

    AudioStream *chain = nullptr;
    int events = -1;
    int device_socket = -1;
    int mode = 0;
    std::atomic<int> dtmf_event{-1};
    std::atomic<bool> network_running{false};
    std::atomic<bool> device_running{false};
    std::thread network_thread;
    std::thread device_thread;
    std::unique_ptr<PulseDevice> device;
};

std::mutex registry_mutex;
std::map<jlong, std::unique_ptr<AudioGroup>> groups;
jlong next_group = 1;

AudioGroup *group(JNIEnv *env, jobject object) {
    auto found = groups.find(env->GetLongField(object, native_field));
    return found == groups.end() ? nullptr : found->second.get();
}

jlong add(JNIEnv *env, jobject object, jint stream_mode, jint socket, jstring address,
          jint port, jstring specification, jint dtmf, jstring package) {
    std::string owner = string(env, package);
    std::string source = authorize(env, owner);
    if (env->ExceptionCheck()) return 0;
    std::string remote_address = string(env, address);
    std::string codec_spec = string(env, specification);
    sockaddr_storage remote{};
    if (inet_pton(AF_INET, remote_address.c_str(), &reinterpret_cast<sockaddr_in *>(&remote)->sin_addr) == 1) {
        auto *ipv4 = reinterpret_cast<sockaddr_in *>(&remote);
        ipv4->sin_family = AF_INET;
        ipv4->sin_port = htons(port);
    } else if (inet_pton(AF_INET6, remote_address.c_str(), &reinterpret_cast<sockaddr_in6 *>(&remote)->sin6_addr) == 1) {
        auto *ipv6 = reinterpret_cast<sockaddr_in6 *>(&remote);
        ipv6->sin6_family = AF_INET6;
        ipv6->sin6_port = htons(port);
    } else {
        fail(env, "java/lang/IllegalArgumentException", "Invalid RTP remote address");
        return 0;
    }
    int payload = -1, rate = -1;
    char codec_name[16]{};
    if (port < 1 || port > 65535 || stream_mode < 0 || stream_mode > 2
            || sscanf(codec_spec.c_str(), "%d %15[^/]/%d", &payload, codec_name, &rate) != 3
            || payload < 0 || payload > 127 || rate != sample_rate || (dtmf != -1 && (dtmf < 96 || dtmf > 127))) {
        fail(env, "java/lang/IllegalArgumentException", "Invalid RTP audio configuration");
        return 0;
    }
    std::unique_ptr<AudioCodec> codec;
    if (strcasecmp(codec_name, "PCMU") == 0) codec.reset(newUlawCodec());
    else if (strcasecmp(codec_name, "PCMA") == 0) codec.reset(newAlawCodec());
    if (!codec) {
        fail(env, "java/lang/IllegalArgumentException", "RTP codec unavailable");
        return 0;
    }
    codec->name = strcasecmp(codec_name, "PCMU") == 0 ? "PCMU" : "PCMA";
    int frames = codec->set(rate, codec_spec.c_str());
    int duplicate = fcntl(socket, F_DUPFD_CLOEXEC, 0);
    if (duplicate < 0) { fail(env, "java/lang/IllegalStateException", "RTP socket unavailable"); return 0; }
    std::unique_ptr<AudioStream> stream(new AudioStream);
    if (!stream->set(stream_mode, duplicate, &remote, codec.get(), rate, frames, payload, dtmf)) {
        close(duplicate);
        fail(env, "java/lang/IllegalStateException", "RTP stream initialization failed");
        return 0;
    }
    codec.release();
    std::lock_guard<std::mutex> lock(registry_mutex);
    AudioGroup *current = group(env, object);
    std::unique_ptr<AudioGroup> created;
    if (!current) {
        created.reset(new AudioGroup(owner));
        current = created.get();
        if (!current->initialize() || !current->setMode(env->GetIntField(object, mode_field), source)) {
            fail(env, "java/lang/IllegalStateException", "PulseAudio call device unavailable");
            return 0;
        }
    }
    if (!current->add(stream.get())) {
        fail(env, "java/lang/IllegalStateException", "Cannot add RTP audio stream");
        return 0;
    }
    if (created) {
        jlong handle = next_group++;
        groups.emplace(handle, std::move(created));
        env->SetLongField(object, native_field, handle);
    }
    return reinterpret_cast<jlong>(stream.release());
}

void removeStream(JNIEnv *env, jobject object, jlong stream) {
    std::lock_guard<std::mutex> lock(registry_mutex);
    AudioGroup *current = group(env, object);
    if (!current) return;
    if (!stream || !current->remove(reinterpret_cast<AudioStream *>(stream))) {
        groups.erase(env->GetLongField(object, native_field));
        env->SetLongField(object, native_field, 0);
    }
}

void setMode(JNIEnv *env, jobject object, jint mode) {
    std::lock_guard<std::mutex> lock(registry_mutex);
    AudioGroup *current = group(env, object);
    if (!current) return;
    std::string source;
    if (mode != 0) {
        source = authorize(env, current->owner);
        if (env->ExceptionCheck()) return;
    }
    if (!current->setMode(mode, source)) {
        current->setMode(0, source);
        env->SetIntField(object, mode_field, 0);
        fail(env, "java/lang/IllegalStateException", "PulseAudio call device unavailable");
    }
}

void sendDtmf(JNIEnv *env, jobject object, jint event) {
    if (event < 0 || event > 15) { fail(env, "java/lang/IllegalArgumentException", "Invalid DTMF event"); return; }
    std::lock_guard<std::mutex> lock(registry_mutex);
    AudioGroup *current = group(env, object);
    if (current) current->sendDtmf(event);
}
} // namespace

extern "C" JNIEXPORT void JNICALL Java_SdRtp_nativeInstall(JNIEnv *env, jclass owner) {
    jclass audio_group = env->FindClass("android/net/rtp/AudioGroup");
    if (!audio_group) return;
    native_field = env->GetFieldID(audio_group, "mNative", "J");
    mode_field = env->GetFieldID(audio_group, "mMode", "I");
    authorize_method = env->GetStaticMethodID(owner, "authorize", "(Ljava/lang/String;)Ljava/lang/String;");
    if (!native_field || !mode_field || !authorize_method) return;
    authorization_class = static_cast<jclass>(env->NewGlobalRef(owner));
    gRandom = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (gRandom < 0) { fail(env, "java/lang/IllegalStateException", "RTP random source unavailable"); return; }
    JNINativeMethod methods[] = {
        {const_cast<char *>("nativeAdd"), const_cast<char *>("(IILjava/lang/String;ILjava/lang/String;ILjava/lang/String;)J"), reinterpret_cast<void *>(add)},
        {const_cast<char *>("nativeRemove"), const_cast<char *>("(J)V"), reinterpret_cast<void *>(removeStream)},
        {const_cast<char *>("nativeSetMode"), const_cast<char *>("(I)V"), reinterpret_cast<void *>(setMode)},
        {const_cast<char *>("nativeSendDtmf"), const_cast<char *>("(I)V"), reinterpret_cast<void *>(sendDtmf)},
    };
    env->RegisterNatives(audio_group, methods, sizeof(methods) / sizeof(methods[0]));
    env->DeleteLocalRef(audio_group);
}
