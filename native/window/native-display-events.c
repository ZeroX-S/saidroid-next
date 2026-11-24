#define _GNU_SOURCE
#include "native-display-events.h"
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/timerfd.h>
#include <time.h>
#include <unistd.h>

/* API28 libgui's DisplayEventReceiver has two private pointer fields and a
 * 24-byte Event ABI. Keep those fields empty, with host-owned state keyed by
 * the receiver address. The translator resolves every instance method through
 * its bionic_ override before the original SurfaceFlinger implementation.
 * Android's DisplayEventDispatcher and Choreographer retain Looper ownership,
 * delayed callback scheduling, and callback dispatch on the requesting thread. */
struct display_event {
    uint32_t type;
    uint32_t display;
    int64_t timestamp;
    uint32_t count;
    uint32_t padding;
};
_Static_assert(sizeof(struct display_event) == 24, "API28 display event ABI");

struct receiver_state {
    const void *owner;
    int read_fd;
    int write_fd;
    int pending;
    uint32_t rate;
    uint32_t frame;
    struct receiver_state *next;
};
static pthread_mutex_t receivers_lock = PTHREAD_MUTEX_INITIALIZER;
static struct receiver_state *receivers;
static const int64_t offscreen_period_ns = 16666667;

static struct receiver_state *find_receiver(const void *owner) {
    struct receiver_state *receiver = receivers;
    while (receiver && receiver->owner != owner) receiver = receiver->next;
    return receiver;
}

void ndk_display_construct(void *, int)
    __asm__("bionic__ZN7android20DisplayEventReceiverC2ENS_16ISurfaceComposer11VsyncSourceE");
void ndk_display_construct(void *owner, int source) {
    (void)source;
    memset(owner, 0, 2 * sizeof(void *));
    struct receiver_state *receiver = calloc(1, sizeof(*receiver));
    if (!receiver) return;
    receiver->owner = owner;
    receiver->write_fd = -1;
    if (sd_window_display_available()) {
        int sockets[2];
        if (socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_NONBLOCK | SOCK_CLOEXEC, 0, sockets) < 0) {
            free(receiver);
            return;
        }
        receiver->read_fd = sockets[0];
        receiver->write_fd = sockets[1];
    } else {
        /* Headless service processes have no Wayland toplevel. A one-shot
         * monotonic timer supplies offscreen display events only on demand. */
        receiver->read_fd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
        if (receiver->read_fd < 0) {
            free(receiver);
            return;
        }
    }
    pthread_mutex_lock(&receivers_lock);
    receiver->next = receivers;
    receivers = receiver;
    pthread_mutex_unlock(&receivers_lock);
    fprintf(stderr, "SDDISPLAY=native_receiver|clock=%s|source=%d\n",
            receiver->write_fd >= 0 ? "wayland" : "offscreen", source);
}

void ndk_display_construct_complete(void *, int)
    __asm__("bionic__ZN7android20DisplayEventReceiverC1ENS_16ISurfaceComposer11VsyncSourceE");
void ndk_display_construct_complete(void *owner, int source) {
    ndk_display_construct(owner, source);
}

void ndk_display_dispose(void *) __asm__("bionic__ZN7android20DisplayEventReceiverD2Ev");
void ndk_display_dispose(void *owner) {
    pthread_mutex_lock(&receivers_lock);
    struct receiver_state **slot = &receivers;
    while (*slot && (*slot)->owner != owner) slot = &(*slot)->next;
    struct receiver_state *receiver = *slot;
    if (receiver) {
        *slot = receiver->next;
        close(receiver->read_fd);
        if (receiver->write_fd >= 0) close(receiver->write_fd);
        free(receiver);
    }
    pthread_mutex_unlock(&receivers_lock);
}

void ndk_display_dispose_complete(void *) __asm__("bionic__ZN7android20DisplayEventReceiverD1Ev");
void ndk_display_dispose_complete(void *owner) { ndk_display_dispose(owner); }

int ndk_display_check(const void *) __asm__("bionic__ZNK7android20DisplayEventReceiver9initCheckEv");
int ndk_display_check(const void *owner) {
    pthread_mutex_lock(&receivers_lock);
    int result = find_receiver(owner) ? 0 : -ENODEV;
    pthread_mutex_unlock(&receivers_lock);
    return result;
}

int ndk_display_fd(const void *) __asm__("bionic__ZNK7android20DisplayEventReceiver5getFdEv");
int ndk_display_fd(const void *owner) {
    pthread_mutex_lock(&receivers_lock);
    struct receiver_state *receiver = find_receiver(owner);
    int result = receiver ? receiver->read_fd : -ENODEV;
    pthread_mutex_unlock(&receivers_lock);
    return result;
}

static int arm_offscreen(struct receiver_state *receiver) {
    struct itimerspec timer = {0};
    int64_t interval = receiver->rate ? offscreen_period_ns * receiver->rate : 0;
    int64_t delay = interval;
    if (!delay && receiver->pending) delay = offscreen_period_ns;
    timer.it_value.tv_sec = delay / 1000000000;
    timer.it_value.tv_nsec = delay % 1000000000;
    timer.it_interval.tv_sec = interval / 1000000000;
    timer.it_interval.tv_nsec = interval % 1000000000;
    return timerfd_settime(receiver->read_fd, 0, &timer, NULL) == 0 ? 0 : -errno;
}

int ndk_display_rate(void *, uint32_t) __asm__("bionic__ZN7android20DisplayEventReceiver12setVsyncRateEj");
int ndk_display_rate(void *owner, uint32_t rate) {
    if (rate > INT_MAX) return -EINVAL;
    pthread_mutex_lock(&receivers_lock);
    struct receiver_state *receiver = find_receiver(owner);
    int result = -ENODEV;
    int request = 0;
    if (receiver) {
        uint32_t previous_rate = receiver->rate;
        receiver->rate = rate;
        result = receiver->write_fd < 0 ? arm_offscreen(receiver) : 0;
        if (result) receiver->rate = previous_rate;
        request = receiver->write_fd >= 0 && (rate || receiver->pending);
    }
    pthread_mutex_unlock(&receivers_lock);
    if (request) sd_window_request_display_frame();
    return result;
}

int ndk_display_request(void *) __asm__("bionic__ZN7android20DisplayEventReceiver16requestNextVsyncEv");
int ndk_display_request(void *owner) {
    pthread_mutex_lock(&receivers_lock);
    struct receiver_state *receiver = find_receiver(owner);
    int result = -ENODEV;
    int request = 0;
    if (receiver) {
        /* Repeated requests coalesce, and must not postpone an armed timer. */
        result = 0;
        if (!receiver->rate && !receiver->pending) {
            receiver->pending = 1;
            result = receiver->write_fd < 0 ? arm_offscreen(receiver) : 0;
            if (result) receiver->pending = 0;
        }
        request = receiver->write_fd >= 0;
    }
    pthread_mutex_unlock(&receivers_lock);
    if (request) sd_window_request_display_frame();
    return result;
}

ssize_t ndk_display_events(void *, struct display_event *, size_t)
    __asm__("bionic__ZN7android20DisplayEventReceiver9getEventsEPNS0_5EventEm");
ssize_t ndk_display_events(void *owner, struct display_event *events, size_t count) {
    if (!count) return 0;
    if (!events || count > SSIZE_MAX / sizeof(*events)) return -EINVAL;
    pthread_mutex_lock(&receivers_lock);
    struct receiver_state *receiver = find_receiver(owner);
    ssize_t result = -ENODEV;
    if (receiver) {
        uint64_t ticks;
        ssize_t bytes;
        do {
            bytes = receiver->write_fd < 0
                ? read(receiver->read_fd, &ticks, sizeof(ticks))
                : recv(receiver->read_fd, events, sizeof(*events), 0);
        } while (bytes < 0 && errno == EINTR);
        result = -ENODATA;
        if (bytes < 0) result = errno == EAGAIN ? 0 : -errno;
        if (bytes > 0) {
            result = 1;
            if (receiver->write_fd < 0) {
                struct timespec now;
                clock_gettime(CLOCK_MONOTONIC, &now);
                receiver->frame += (uint32_t)ticks * (receiver->rate ? receiver->rate : 1);
                *events = (struct display_event){0x7673796e, 0,
                    now.tv_sec * 1000000000LL + now.tv_nsec, receiver->frame, 0};
                receiver->pending = 0;
            }
        }
    }
    pthread_mutex_unlock(&receivers_lock);
    return result;
}

void sd_native_display_frame(int64_t timestamp) {
    int request = 0;
    pthread_mutex_lock(&receivers_lock);
    for (struct receiver_state *receiver = receivers; receiver; receiver = receiver->next) {
        if (receiver->write_fd < 0) continue;
        ++receiver->frame;
        if (receiver->pending || (receiver->rate && receiver->frame % receiver->rate == 0)) {
            struct display_event event = {0x7673796e, 0, timestamp, receiver->frame, 0};
            ssize_t bytes;
            do {
                bytes = send(receiver->write_fd, &event, sizeof(event), MSG_NOSIGNAL);
            } while (bytes < 0 && errno == EINTR);
            if (bytes == sizeof(event)) receiver->pending = 0;
        }
        request |= receiver->pending || receiver->rate;
    }
    pthread_mutex_unlock(&receivers_lock);
    if (request) sd_window_request_display_frame();
}
