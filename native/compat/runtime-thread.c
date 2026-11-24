#define _GNU_SOURCE
#include <pthread.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <errno.h>

/* Android asks for another pthread's kernel TID, notably when registering
 * RenderThread. Returning the caller's gettid() silently boosts the UI thread.
 * Linux per-thread CPU clock IDs encode the owning TID; obtain one through
 * glibc's public pthread API instead of depending on its private pthread layout.
 */
int bionic_pthread_gettid_np(pthread_t thread) {
    if(pthread_equal(thread,pthread_self()))return (int)syscall(SYS_gettid);
    clockid_t clock;
    int error=pthread_getcpuclockid(thread,&clock);
    if(error){errno=error;return -1;}
    int tid=~((int)clock>>3);
    if(tid<=0){errno=ESRCH;return -1;}
    return tid;
}
