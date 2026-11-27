#define _GNU_SOURCE
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

/* Test-only observer: all munmap calls reach the real kernel unchanged. */
static __thread uintptr_t expected_base;
static __thread size_t expected_size;
static __thread int exact_successes;
static __thread int incorrect_overlaps;
static __thread int immediate_unmapped;
void stack_observer_arm(void *base, size_t size) {
    expected_base = (uintptr_t)base; expected_size = size;
    exact_successes = incorrect_overlaps = immediate_unmapped = 0;
}
int stack_observer_result(void) {
    return exact_successes == 1 && incorrect_overlaps == 0 && immediate_unmapped == 1;
}
int munmap(void *addr, size_t len) {
    int result = (int)syscall(SYS_munmap, addr, len);
    int saved = errno;
    uintptr_t start = (uintptr_t)addr;
    if (expected_size && result == 0) {
        if (start == expected_base && len == expected_size) {
            exact_successes++;
            /* At the kernel boundary, before returning control to ART. */
            unsigned char vec[128];
            errno = 0;
            long status = syscall(SYS_mincore, addr, len, vec);
            if (status == -1 && errno == ENOMEM) immediate_unmapped++;
        } else if (start < expected_base + expected_size &&
                   (start >= expected_base || len > expected_base - start)) {
            incorrect_overlaps++;
        }
    }
    errno = saved;
    return result;
}
