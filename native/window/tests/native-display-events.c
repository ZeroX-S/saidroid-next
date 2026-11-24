#include "../native-display-events.c"
#include <assert.h>
#include <fcntl.h>
#include <poll.h>

static int available = 1;
static int requested;
int sd_window_display_available(void) { return available; }
void sd_window_request_display_frame(void) { ++requested; }

static void check_event(void *owner, int64_t timestamp, uint32_t count) {
    struct display_event event;
    assert(ndk_display_events(owner, &event, 1) == 1);
    assert(event.type == 0x7673796e && event.display == 0);
    assert(event.timestamp == timestamp && event.count == count);
    assert(ndk_display_events(owner, &event, 1) == 0);
}

int main(void) {
    void *first[2], *second[2];
    ndk_display_construct(first, 0);
    ndk_display_construct_complete(second, 1);
    assert(ndk_display_check(first) == 0 && ndk_display_check(second) == 0);
    assert(first[0] == NULL && first[1] == NULL);
    int fd = ndk_display_fd(first);
    assert(fcntl(fd, F_GETFD) & FD_CLOEXEC);
    struct display_event event;
    assert(ndk_display_events(first, NULL, 1) == -EINVAL);
    assert(ndk_display_events(first, &event, 0) == 0);
    assert(ndk_display_rate(first, UINT32_MAX) == -EINVAL);
    assert(ndk_display_request(first) == 0);
    assert(ndk_display_request(first) == 0);
    sd_native_display_frame(1000000000);
    check_event(first, 1000000000, 1);
    assert(ndk_display_events(second, &event, 1) == 0);
    sd_native_display_frame(1016666667);
    assert(ndk_display_events(first, &event, 1) == 0);
    assert(ndk_display_rate(second, 2) == 0);
    sd_native_display_frame(1033333334);
    assert(ndk_display_events(second, &event, 1) == 0);
    sd_native_display_frame(1050000001);
    check_event(second, 1050000001, 4);
    assert(ndk_display_rate(second, 0) == 0);
    ndk_display_request(first);
    ndk_display_dispose(first);
    assert(fcntl(fd, F_GETFD) == -1 && errno == EBADF);
    sd_native_display_frame(1066666668);
    assert(ndk_display_request(first) == -ENODEV);
    ndk_display_dispose_complete(second);
    assert(receivers == NULL);

    available = 0;
    ndk_display_construct(first, 0);
    fd = ndk_display_fd(first);
    struct pollfd poll_fd = {fd, POLLIN, 0};
    assert(poll(&poll_fd, 1, 0) == 0);
    assert(ndk_display_request(first) == 0);
    assert(ndk_display_request(first) == 0);
    assert(poll(&poll_fd, 1, 100) == 1);
    assert(ndk_display_events(first, &event, 1) == 1);
    assert(event.timestamp > 0 && event.count == 1 && event.type == 0x7673796e);
    assert(poll(&poll_fd, 1, 30) == 0);
    assert(ndk_display_rate(first, 1) == 0);
    assert(poll(&poll_fd, 1, 100) == 1);
    assert(ndk_display_events(first, &event, 1) == 1 && event.count >= 2);
    assert(ndk_display_rate(first, 0) == 0);
    assert(poll(&poll_fd, 1, 30) == 0);
    ndk_display_dispose_complete(first);
    assert(receivers == NULL && requested >= 3);
    puts("NATIVE_DISPLAY_EVENTS=passed|one_shot=1|rate=1|isolated=1|dispose=1|offscreen=1");
    return 0;
}
