#include <jni.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/stat.h>
#include <time.h>

typedef struct ALooper ALooper;
typedef struct AChoreographer AChoreographer;
extern ALooper *ALooper_prepare(int);
extern int ALooper_pollOnce(int, int *, int *, void **);
extern AChoreographer *AChoreographer_getInstance(void);
extern void AChoreographer_postFrameCallback(AChoreographer *, void (*)(long, void *), void *);
extern void AChoreographer_postFrameCallbackDelayed(AChoreographer *, void (*)(long, void *), void *, long);

extern void receiver_create(void *, int) __asm__("_ZN7android20DisplayEventReceiverC1ENS_16ISurfaceComposer11VsyncSourceE");
extern void receiver_dispose(void *) __asm__("_ZN7android20DisplayEventReceiverD1Ev");
extern int receiver_fd(const void *) __asm__("_ZNK7android20DisplayEventReceiver5getFdEv");
extern int receiver_request(void *) __asm__("_ZN7android20DisplayEventReceiver16requestNextVsyncEv");
extern int receiver_check(const void *) __asm__("_ZNK7android20DisplayEventReceiver9initCheckEv");

struct callback_state {
    pthread_t owner;
    AChoreographer *choreographer;
    int callbacks;
    int wrong_thread;
    int bad_timestamp;
    int64_t requested_at;
    int64_t first_delay;
    int64_t last_timestamp;
    int64_t initialize_ns;
};

static int64_t monotonic_ns(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return now.tv_sec * 1000000000LL + now.tv_nsec;
}

static void frame_callback(long timestamp, void *data) {
    struct callback_state *state = data;
    state->wrong_thread |= !pthread_equal(pthread_self(), state->owner);
    state->bad_timestamp |= timestamp <= state->last_timestamp;
    state->last_timestamp = timestamp;
    if (!state->callbacks) state->first_delay = monotonic_ns() - state->requested_at;
    ++state->callbacks;
    if (state->callbacks < 3) {
        AChoreographer_postFrameCallback(state->choreographer, frame_callback, state);
    }
}

static void *run_callbacks(void *data) {
    struct callback_state *state = data;
    state->owner = pthread_self();
    ALooper_prepare(1);
    int64_t start = monotonic_ns();
    state->choreographer = AChoreographer_getInstance();
    state->initialize_ns = monotonic_ns() - start;
    if (!state->choreographer) return NULL;
    state->requested_at = monotonic_ns();
    AChoreographer_postFrameCallbackDelayed(state->choreographer, frame_callback, state, 40);
    int64_t deadline = state->requested_at + 5000000000LL;
    while (state->callbacks < 3 && monotonic_ns() < deadline) {
        ALooper_pollOnce(50, NULL, NULL, NULL);
    }
    return NULL;
}

JNIEXPORT jstring JNICALL
Java_org_example_saildroid_nativedisplay_NativeDisplayActivity_checkNativeDisplay(JNIEnv *env, jclass type) {
    (void)type;
    uint64_t receiver[2];
    receiver_create(receiver, 0);
    int fd = receiver_fd(receiver);
    int initialized = receiver_check(receiver) == 0 && fd >= 0;
    struct stat before_dispose, after_dispose;
    int identified = initialized && fstat(fd, &before_dispose) == 0;
    int scheduled = receiver_request(receiver) == 0;
    struct pollfd watched = {fd, POLLIN, 0};
    int event_ready = initialized && poll(&watched, 1, 2000) == 1;
    receiver_dispose(receiver);
    /* The render thread can reuse the descriptor number immediately. Verify
     * the original kernel object, as well as removal of receiver ownership. */
    int fd_status = fstat(fd, &after_dispose);
    int closed = fd_status < 0 && errno == EBADF;
    int reused = fd_status == 0 && identified &&
        (before_dispose.st_dev != after_dispose.st_dev || before_dispose.st_ino != after_dispose.st_ino);
    int disposed = identified && (closed || reused) && receiver_check(receiver) == -ENODEV;
    struct callback_state states[2] = {{0}, {0}};
    pthread_t workers[2];
    int created = 0;
    for (int index = 0; index < 2; ++index) {
        if (pthread_create(&workers[index], NULL, run_callbacks, &states[index]) != 0) break;
        ++created;
    }
    for (int index = 0; index < created; ++index) pthread_join(workers[index], NULL);
    int passed = initialized && scheduled && event_ready && disposed && created == 2;
    for (int index = 0; index < created; ++index) {
        passed &= states[index].callbacks == 3 && !states[index].wrong_thread
            && !states[index].bad_timestamp && states[index].first_delay >= 40000000
            && states[index].initialize_ns < 1000000000;
    }
    char result[512];
    snprintf(result, sizeof(result), "%s|native_choreographer=1|receiver_fd=%d|dispose=%d|callbacks=%d,%d|thread_errors=%d,%d|timestamp_errors=%d,%d|init_ms=%lld,%lld|delay_ms=%lld,%lld",
        passed ? "passed" : "failed", event_ready, disposed,
        states[0].callbacks, states[1].callbacks, states[0].wrong_thread, states[1].wrong_thread,
        states[0].bad_timestamp, states[1].bad_timestamp,
        (long long)(states[0].initialize_ns / 1000000), (long long)(states[1].initialize_ns / 1000000),
        (long long)(states[0].first_delay / 1000000), (long long)(states[1].first_delay / 1000000));
    return (*env)->NewStringUTF(env, result);
}
