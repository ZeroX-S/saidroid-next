#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <unistd.h>

/* ART extracts compressed APK DEX into an unpublished, page-aligned MemMap.
 * Replace only that allocation with identical MAP_PRIVATE file pages. ART
 * retains its original DEX location, verification, write protection and unmap.
 * Application writes remain copy-on-write, including debugger modifications. */
static const char extractor_symbol[] =
    "_Z15ExtractToMemoryP10ZipArchivePK8ZipEntryPhm";
static const char mapping_symbol[] =
    "_ZN3art8ZipEntry15ExtractToMemMapEPKcS2_PNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE";
typedef int32_t (*extractor_function)(void *, const void *, uint8_t *, size_t);
static extractor_function original_extractor;
static int (*archive_descriptor)(void *);
static void *mapping_entry;
/* GLib is already loaded by the native host. Keep CLI environments without
 * that dependency on the original extraction path. G_CHECKSUM_SHA256 is 2. */
static char *(*checksum_data)(int, const uint8_t *, size_t);
static void (*checksum_free)(void *);
static pthread_once_t symbols_once = PTHREAD_ONCE_INIT;

static void resolve_symbols(void) {
    original_extractor = (extractor_function)dlsym(RTLD_NEXT, extractor_symbol);
    archive_descriptor = dlsym(RTLD_NEXT, "_Z17GetFileDescriptorP10ZipArchive");
    mapping_entry = dlsym(RTLD_NEXT, mapping_symbol);
    /* ART's dependencies can be RTLD_LOCAL. Reuse their already-loaded
     * handles so the ZIP delegate stays available in that loading domain. */
    const char *root = getenv("ANDROID_ROOT");
    if (root) {
        char path[PATH_MAX];
        int length = snprintf(path, sizeof(path), "%s/lib/libartbase.so", root);
        void *handle = length > 0 && length < (int)sizeof(path)
            ? dlopen(path, RTLD_LAZY | RTLD_NOLOAD) : NULL;
        if (handle) {
            original_extractor = (extractor_function)dlsym(handle, extractor_symbol);
            archive_descriptor = dlsym(handle, "_Z17GetFileDescriptorP10ZipArchive");
            mapping_entry = dlsym(handle, mapping_symbol);
            dlclose(handle);
        }
    }
    checksum_data = dlsym(RTLD_DEFAULT, "g_compute_checksum_for_data");
    checksum_free = dlsym(RTLD_DEFAULT, "g_free");
}

static int private_directory(int descriptor) {
    struct stat metadata;
    return descriptor >= 0 && fstat(descriptor, &metadata) == 0 &&
           S_ISDIR(metadata.st_mode) && metadata.st_uid == getuid() &&
           (metadata.st_mode & 077) == 0;
}

static int open_cache(void) {
    const char *data = getenv("SAILDROID_DATA_DIR");
    if (!data)
        return -1;
    int application = open(data, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (!private_directory(application)) {
        if (application >= 0)
            close(application);
        return -1;
    }
    int code = openat(application, "code_cache", O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    close(application);
    if (!private_directory(code)) {
        if (code >= 0)
            close(code);
        return -1;
    }
    int result = -1;
    if (mkdirat(code, "shared-dex-v1", 0700) == 0 || errno == EEXIST)
        result = openat(code, "shared-dex-v1", O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    close(code);
    if (!private_directory(result)) {
        if (result >= 0)
            close(result);
        return -1;
    }
    return result;
}

static int verified_file(int cache, const char *name, const uint8_t *bytes, size_t size) {
    int descriptor = openat(cache, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (descriptor < 0)
        return -1;
    struct stat before, after;
    if (fstat(descriptor, &before) != 0 || !S_ISREG(before.st_mode) ||
        before.st_uid != getuid() || (before.st_mode & 022) != 0 ||
        before.st_size < 0 || (uint64_t)before.st_size != size)
        goto invalid;
    uint8_t buffer[65536];
    size_t offset = 0;
    while (offset < size) {
        size_t count = size - offset;
        if (count > sizeof(buffer))
            count = sizeof(buffer);
        ssize_t received = pread(descriptor, buffer, count, (off_t)offset);
        if (received < 0 && errno == EINTR)
            continue;
        if (received <= 0 || memcmp(buffer, bytes + offset, (size_t)received) != 0)
            goto invalid;
        offset += (size_t)received;
    }
    if (fstat(descriptor, &after) != 0 || before.st_size != after.st_size ||
        before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
        before.st_mtim.tv_nsec != after.st_mtim.tv_nsec ||
        before.st_ctim.tv_sec != after.st_ctim.tv_sec ||
        before.st_ctim.tv_nsec != after.st_ctim.tv_nsec)
        goto invalid;
    return descriptor;
invalid:
    close(descriptor);
    return -1;
}

static int create_file(int cache, const char *name, const uint8_t *bytes, size_t size) {
    uint64_t random;
    if (getrandom(&random, sizeof(random), 0) != sizeof(random))
        return -1;
    char temporary[112];
    snprintf(temporary, sizeof(temporary), ".%s-%ld-%016llx", name,
             (long)getpid(), (unsigned long long)random);
    int descriptor = openat(cache, temporary,
                            O_CREAT | O_EXCL | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (descriptor < 0)
        return -1;
    size_t offset = 0;
    while (offset < size) {
        ssize_t count = write(descriptor, bytes + offset, size - offset);
        if (count < 0 && errno == EINTR)
            continue;
        if (count <= 0)
            goto failed;
        offset += (size_t)count;
    }
    if (fchmod(descriptor, 0444) != 0 || fsync(descriptor) != 0 ||
        renameat(cache, temporary, cache, name) != 0)
        goto failed;
    return descriptor;
failed:
    unlinkat(cache, temporary, 0);
    close(descriptor);
    return -1;
}

static int cache_file(int cache, const char *name, const uint8_t *bytes, size_t size,
                      int *created) {
    int descriptor = verified_file(cache, name, bytes, size);
    if (descriptor >= 0)
        return descriptor;
    int lock = openat(cache, ".lock", O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK, 0600);
    struct stat metadata;
    if (lock < 0)
        return -1;
    /* A competing or interrupted cache writer must never delay app startup.
     * Every published entry is complete and replacements use a new inode. */
    if (fstat(lock, &metadata) != 0 || !S_ISREG(metadata.st_mode) ||
        metadata.st_uid != getuid() || (metadata.st_mode & 077) != 0 ||
        flock(lock, LOCK_EX | LOCK_NB) != 0) {
        close(lock);
        return -1;
    }
    descriptor = verified_file(cache, name, bytes, size);
    if (descriptor < 0) {
        descriptor = create_file(cache, name, bytes, size);
        *created = descriptor >= 0;
    }
    close(lock);
    return descriptor;
}

static int32_t share_mapping(void *archive, const void *entry, uint8_t *bytes,
                              size_t size, void *caller) {
    Dl_info owner;
    uint32_t dex_size;
    long page_size = sysconf(_SC_PAGESIZE);
    if (!mapping_entry || !archive_descriptor || !checksum_data || !checksum_free ||
        !dladdr(caller, &owner) || owner.dli_saddr != mapping_entry ||
        size < 112 || page_size <= 0 || (uintptr_t)bytes % (size_t)page_size != 0 ||
        memcmp(bytes, "dex\n", 4) != 0)
        return 0;
    memcpy(&dex_size, bytes + 32, sizeof(dex_size));
    if (dex_size != size)
        return 0;
    const char *package = getenv("SAILDROID_PACKAGE");
    if (!package || !*package || strchr(package, '/'))
        return 0;
    char prefix[PATH_MAX], archive_path[PATH_MAX], descriptor_path[64];
    int length = snprintf(prefix, sizeof(prefix), "/home/art/apps/%s/versions/", package);
    if (length <= 0 || length >= (int)sizeof(prefix))
        return 0;
    int archive_fd = archive_descriptor(archive);
    if (archive_fd < 0)
        return 0;
    snprintf(descriptor_path, sizeof(descriptor_path), "/proc/self/fd/%d", archive_fd);
    ssize_t count = readlink(descriptor_path, archive_path, sizeof(archive_path) - 1);
    if (count <= length || count >= (ssize_t)sizeof(archive_path) - 1)
        return 0;
    archive_path[count] = '\0';
    if (strncmp(archive_path, prefix, (size_t)length) != 0 || count < 4 ||
        strcmp(archive_path + count - 4, ".apk") != 0)
        return 0;
    char *checksum = checksum_data(2, bytes, size);
    if (!checksum)
        return 0;
    char name[69];
    snprintf(name, sizeof(name), "%s.dex", checksum);
    checksum_free(checksum);
    int cache = open_cache();
    int created = 0;
    int descriptor = cache >= 0 ? cache_file(cache, name, bytes, size, &created) : -1;
    if (cache >= 0)
        close(cache);
    if (descriptor < 0) {
        fprintf(stderr, "SDEXCACHE=fallback|reason=cache-unavailable|bytes=%zu\n", size);
        return 0;
    }
    void *mapped = mmap(bytes, size, PROT_READ | PROT_WRITE,
                        MAP_FIXED | MAP_PRIVATE, descriptor, 0);
    close(descriptor);
    if (mapped == MAP_FAILED) {
        fprintf(stderr, "SDEXCACHE=fallback|reason=file-map-failed|bytes=%zu\n", size);
        /* MAP_FIXED can remove the old mapping before a later mapping error.
         * Reconstruct the unpublished allocation through the original ZIP
         * extractor before allowing ART to use or destroy this MemMap. */
        if (mmap(bytes, size, PROT_READ | PROT_WRITE,
                 MAP_FIXED | MAP_PRIVATE | MAP_ANONYMOUS, -1, 0) == MAP_FAILED)
            return -1;
        return original_extractor(archive, entry, bytes, size);
    }
    fprintf(stderr, "SDEXCACHE=mapped|bytes=%zu|cache=%s|write=copy-on-write\n",
            size, created ? "created" : "reused");
    return 0;
}

int32_t sd_shared_dex_extract(void *archive, const void *entry, uint8_t *bytes,
                              size_t size) __asm__("_Z15ExtractToMemoryP10ZipArchivePK8ZipEntryPhm");
int32_t sd_shared_dex_extract(void *archive, const void *entry, uint8_t *bytes, size_t size) {
    void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    pthread_once(&symbols_once, resolve_symbols);
    if (!original_extractor) {
        errno = ENOSYS;
        return -1;
    }
    int32_t result = original_extractor(archive, entry, bytes, size);
    int saved_errno = errno;
    if (result == 0) {
        result = share_mapping(archive, entry, bytes, size, caller);
        if (result != 0)
            return result;
    }
    errno = saved_errno;
    return result;
}
