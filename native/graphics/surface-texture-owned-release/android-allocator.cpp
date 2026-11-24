#include <string>
#include <cstdint>
#include <cutils/native_handle.h>
#include <system/window.h>
#include <ui/GraphicBuffer.h>
#include <gui/Surface.h>
#include <gui/GLConsumer.h>

/* This TU is built with Android libc++, not the host C++ runtime. A by-value
 * requestorName remains governed by that exact ABI and is destroyed normally. */
static int (*allocate_host)(unsigned,unsigned,int,unsigned,uint64_t,
                           const native_handle_t**,unsigned*);
extern "C" void sd_texture_set_host_allocator(void* callback) {
    allocate_host=reinterpret_cast<decltype(allocate_host)>(callback);
}
extern "C" int sd_texture_android_allocate(void*,unsigned w,unsigned h,int format,
        unsigned layers,uint64_t usage,const native_handle_t** handle,unsigned* stride,
        uint64_t, std::string requestorName) {
    (void)requestorName;
    return allocate_host?allocate_host(w,h,format,layers,usage,handle,stride):-19;
}
extern "C" const native_handle_t* sd_texture_buffer_handle(void* pointer) {
    const auto* buffer=static_cast<const ANativeWindowBuffer*>(pointer);
    return buffer && buffer->common.magic==ANDROID_NATIVE_BUFFER_MAGIC?buffer->handle:nullptr;
}

extern "C" void* sd_texture_client_buffer(void* pointer) {
    return pointer?static_cast<android::GraphicBuffer*>(pointer)->getNativeBuffer():nullptr;
}

extern "C" int sd_texture_surface_window_id(void* pointer) {
    /* Java stores Surface*, while EGL receives its ANativeWindow base. This
     * conversion must use the Android C++ ABI and its actual base adjustment. */
    auto*surface=static_cast<android::Surface*>(pointer);
    ANativeWindow*window=surface;int id=0;
    return window&&window->query(window,0x53440001,&id)==0?id:0;
}

namespace {
class CameraFrameListener final : public android::ConsumerBase::FrameAvailableListener {
    android::sp<android::ConsumerBase::FrameAvailableListener> original;
public:
    explicit CameraFrameListener(android::ConsumerBase::FrameAvailableListener* listener)
        : original(listener) {}
    void onFrameAvailable(const android::BufferItem& item) override {
        original->onFrameAvailable(item);
    }
    void onFrameReplaced(const android::BufferItem& item) override {
        // A reconnect can replace a pending frame from the previous camera.
        // SurfaceTexture's JNI listener otherwise leaves that frame unannounced.
        original->onFrameAvailable(item);
    }
};

struct CameraNotifications {
    android::sp<android::GLConsumer> consumer;
    android::sp<android::ConsumerBase::FrameAvailableListener> original;
    android::sp<CameraFrameListener> listener;
    CameraNotifications(android::GLConsumer* texture,
                        android::ConsumerBase::FrameAvailableListener* callback)
        : consumer(texture), original(callback), listener(new CameraFrameListener(callback)) {
        consumer->setFrameAvailableListener(listener);
    }
    ~CameraNotifications() {
        consumer->setFrameAvailableListener(original);
    }
};
}

extern "C" void* sd_texture_camera_notifications(void* texture, void* listener) {
    if (!texture || !listener) return nullptr;
    return new CameraNotifications(static_cast<android::GLConsumer*>(texture),
            static_cast<android::ConsumerBase::FrameAvailableListener*>(listener));
}

extern "C" void sd_texture_release_camera_notifications(void* notifications) {
    delete static_cast<CameraNotifications*>(notifications);
}
