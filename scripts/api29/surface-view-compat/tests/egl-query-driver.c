#include <stddef.h>

static int error = 0x3000;
static unsigned destroyed;

unsigned eglQuerySurface(void *display, void *surface, int attribute, int *value) {
    if (display != (void *)1) {
        error = 0x3008;
        return 0;
    }
    if (!surface) {
        error = 0x300d;
        return 0;
    }
    if (!value) {
        error = 0x300c;
        return 0;
    }
    switch (attribute) {
    case 0x313d: *value = 2; break;
    case 0x3057: *value = 64; break;
    case 0x3056: *value = 48; break;
    default:
        error = 0x3004;
        return 0;
    }
    return 1;
}

void *eglCreateWindowSurface(void *display, void *config, void *window, const int *attributes) {
    (void)config;
    (void)attributes;
    return display == (void *)1 && window == (void *)2 ? (void *)3 : NULL;
}

unsigned eglDestroySurface(void *display, void *surface) {
    (void)display;
    (void)surface;
    destroyed++;
    return 1;
}

unsigned driver_destroyed_surfaces(void) {
    return destroyed;
}

int eglGetError(void) {
    int result = error;
    error = 0x3000;
    return result;
}

void *eglGetProcAddress(const char *name) {
    (void)name;
    return NULL;
}
