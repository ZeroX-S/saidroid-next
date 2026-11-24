#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

void sd_hwui_register_host(void *(*display)(void), void *(*window)(int),
                           int (*identify)(void *), void (*presented)(void));
unsigned bionic_eglQuerySurface(void *, void *, int, int *);
void *bionic_eglCreateWindowSurface(void *, void *, void *, const int *);
unsigned bionic_eglDestroySurface(void *, void *);
int bionic_eglGetError(void);
void *bionic_eglGetProcAddress(const char *);
void *__real_malloc(size_t);

static int fail_next_allocation;

void *__wrap_malloc(size_t size) {
    if (fail_next_allocation) {
        fail_next_allocation = 0;
        return NULL;
    }
    return __real_malloc(size);
}

static void *display(void) {
    return (void *)1;
}

static void *window(int id) {
    return id == 101 ? (void *)2 : NULL;
}

static int identify(void *native_window) {
    return native_window == (void *)2 ? 101 : 0;
}

int main(void) {
    int value = -1;
    sd_hwui_register_host(display, window, identify, NULL);
    void *surface = bionic_eglCreateWindowSurface((void *)1, NULL, (void *)2, NULL);
    assert(surface == (void *)3);
    assert(bionic_eglQuerySurface((void *)1, surface, 0x313d, &value) && value == 0);
    assert(bionic_eglGetProcAddress("eglQuerySurface") == (void *)bionic_eglQuerySurface);
    assert(bionic_eglQuerySurface((void *)1, surface, 0x3057, &value) && value == 64);
    assert(bionic_eglQuerySurface((void *)1, surface, 0x3056, &value) && value == 48);
    assert(bionic_eglQuerySurface((void *)1, (void *)4, 0x313d, &value) && value == 2);

    value = -1;
    assert(!bionic_eglQuerySurface(NULL, surface, 0x313d, &value) && value == -1);
    assert(bionic_eglGetError() == 0x3008);
    assert(!bionic_eglQuerySurface((void *)1, NULL, 0x313d, &value) && value == -1);
    assert(bionic_eglGetError() == 0x300d);
    assert(!bionic_eglQuerySurface((void *)1, surface, 0x313d, NULL));
    assert(bionic_eglGetError() == 0x300c);
    assert(!bionic_eglQuerySurface((void *)1, surface, -1, &value) && value == -1);
    assert(bionic_eglGetError() == 0x3004);

    assert(bionic_eglDestroySurface((void *)1, surface));
    assert(bionic_eglQuerySurface((void *)1, surface, 0x313d, &value) && value == 2);
    surface = bionic_eglCreateWindowSurface((void *)1, NULL, (void *)2, NULL);
    assert(surface == (void *)3);
    assert(bionic_eglQuerySurface((void *)1, surface, 0x313d, &value) && value == 0);
    assert(bionic_eglDestroySurface((void *)1, surface));

    void *driver = dlopen("libEGL.so.1", RTLD_NOW | RTLD_LOCAL);
    assert(driver);
    unsigned (*destroyed)(void) = dlsym(driver, "driver_destroyed_surfaces");
    assert(destroyed && destroyed() == 2);
    fail_next_allocation = 1;
    assert(!bionic_eglCreateWindowSurface((void *)1, NULL, (void *)2, NULL));
    assert(!fail_next_allocation);
    assert(bionic_eglGetError() == 0x3003);
    assert(destroyed() == 3);
    assert(bionic_eglQuerySurface((void *)1, (void *)3, 0x313d, &value) && value == 2);
    dlclose(driver);
    puts("{\"passed\":true,\"owned_window_age\":0,\"other_surface_age\":2,\"geometry_and_errors_preserved\":true,\"allocation_failure_cleanup\":true}");
    return 0;
}
