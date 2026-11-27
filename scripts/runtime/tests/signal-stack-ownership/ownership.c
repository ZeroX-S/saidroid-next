#define _GNU_SOURCE
#include <jni.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <errno.h>
#include <dlfcn.h>

typedef struct { JavaVM *vm; int mode; int result; } Context;
static int perms(uintptr_t start, uintptr_t end, const char *want) {
    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return 0;
    char line[1024], flags[5]; unsigned long a, b;
    uintptr_t next = start;
    while (fgets(line, sizeof(line), f)) {
        if (sscanf(line, "%lx-%lx %4s", &a, &b, flags) != 3) continue;
        if (a <= next && b > next) {
            if (strncmp(flags, want, 3)) { fclose(f); return 0; }
            next = b;
            if (next >= end) { fclose(f); return 1; }
        }
    }
    fclose(f); return 0;
}
static void *worker(void *arg) {
    Context *c = arg; JNIEnv *env = NULL; stack_t owned, now;
    const size_t foreign_size = 128 * 1024;
    void *foreign = MAP_FAILED; size_t page = (size_t)sysconf(_SC_PAGESIZE);
    int attached = 0;
#define REQUIRE(x, n) do { if (!(x)) { c->result = -(n); goto cleanup; } } while (0)
    if (c->mode == 2 || c->mode == 3) {
        foreign = mmap(NULL, foreign_size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        REQUIRE(foreign != MAP_FAILED, 1);
        memset(foreign, 0x5a, foreign_size);
    }
    if (c->mode == 3) {
        stack_t prior = { .ss_sp = (char *)foreign + 13, .ss_size = foreign_size - 13, .ss_flags = 0 };
        REQUIRE(sigaltstack(&prior, NULL) == 0, 2);
    }
    REQUIRE((*c->vm)->AttachCurrentThread(c->vm, (void **)&env, NULL) == JNI_OK, 3);
    attached = 1;
    REQUIRE(sigaltstack(NULL, &owned) == 0 && !(owned.ss_flags & SS_DISABLE), 4);
    uintptr_t p = (uintptr_t)owned.ss_sp;
    REQUIRE(owned.ss_size >= 256 * 1024 && owned.ss_size % page == 0, 5);
    REQUIRE(perms(p, p + owned.ss_size, "rw-"), 6);
    REQUIRE(perms(p - page, p, "---") && perms(p + owned.ss_size, p + owned.ss_size + page, "---"), 7);
    void (*arm)(void *, size_t) = dlsym(RTLD_DEFAULT, "stack_observer_arm");
    int (*observed)(void) = dlsym(RTLD_DEFAULT, "stack_observer_result");
    REQUIRE(arm && observed, 18);
    arm((void *)(p - page), owned.ss_size + 2 * page);
    if (c->mode == 1) {
        stack_t disabled = { .ss_flags = SS_DISABLE, .ss_size = 256 * 1024 };
        REQUIRE(sigaltstack(&disabled, NULL) == 0, 8);
    } else if (c->mode == 2) {
        stack_t replacement = { .ss_sp = (char *)foreign + 13, .ss_size = foreign_size - 13, .ss_flags = 0 };
        REQUIRE(sigaltstack(&replacement, NULL) == 0, 9);
    } else if (c->mode == 4) {
        stack_t alias = { .ss_sp = (char *)owned.ss_sp + 17, .ss_size = owned.ss_size - 17, .ss_flags = 0 };
        REQUIRE(sigaltstack(&alias, NULL) == 0, 10);
    }
    REQUIRE((*c->vm)->DetachCurrentThread(c->vm) == JNI_OK, 11);
    attached = 0;
    REQUIRE(observed(), 19);
    REQUIRE(sigaltstack(NULL, &now) == 0, 12);
    if (c->mode == 2 || c->mode == 3) {
        REQUIRE(!(now.ss_flags & SS_DISABLE) && now.ss_sp == (char *)foreign + 13 && now.ss_size == foreign_size - 13, 13);
        REQUIRE(perms((uintptr_t)foreign, (uintptr_t)foreign + foreign_size, "rw-"), 14);
        for (size_t i = 0; i < foreign_size; i++) REQUIRE(((unsigned char *)foreign)[i] == 0x5a, 15);
    } else REQUIRE(now.ss_flags & SS_DISABLE, 16);
    c->result = 1;
cleanup:
    if (attached) (*c->vm)->DetachCurrentThread(c->vm);
    stack_t disabled = { .ss_flags = SS_DISABLE, .ss_size = 256 * 1024 };
    sigaltstack(&disabled, NULL);
    if (foreign != MAP_FAILED) munmap(foreign, foreign_size);
    return NULL;
}
JNIEXPORT jint JNICALL Java_ArtSignalStackOwnership_exercise(JNIEnv *env, jclass cls, jint mode, jint iterations) {
    (void)cls; Context c = { .mode = mode };
    if ((*env)->GetJavaVM(env, &c.vm) != JNI_OK) return -100;
    for (int i = 0; i < iterations; i++) {
        pthread_t thread;
        if (pthread_create(&thread, NULL, worker, &c)) return -101;
        if (pthread_join(thread, NULL)) return -102;
        if (c.result != 1) return c.result;
    }
    return iterations;
}
