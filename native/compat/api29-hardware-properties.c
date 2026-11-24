#define _GNU_SOURCE
#include <dlfcn.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#ifndef SD_HOST_PROPERTY_LIBRARY
#define SD_HOST_PROPERTY_LIBRARY "/usr/lib64/libhybris-common.so.1"
#endif

#ifndef SD_HOST_HARDWARE_FILE
#define SD_HOST_HARDWARE_FILE "/etc/hw-release"
#endif

#ifndef SD_HOST_LOCALTIME_FILE
#define SD_HOST_LOCALTIME_FILE "/etc/localtime"
#endif

#ifndef SD_HOST_ZONEINFO_DIRECTORY
#define SD_HOST_ZONEINFO_DIRECTORY "/usr/share/zoneinfo"
#endif

static pthread_mutex_t timezone_lock = PTHREAD_MUTEX_INITIALIZER;

/* Timed resolves the selected zone through /etc/localtime. Its intermediate
 * link is user-owned on Sailfish, while the resolved TZif data is system-owned.
 * Keep the IANA identifier so fractional offsets and daylight saving rules are
 * selected from the component's timezone database. */
int sd_import_host_timezone_properties(void *private_libc, char timezone[92]) {
    char path[PATH_MAX], directory[PATH_MAX];
    struct stat info;
    timezone[0] = '\0';
    if (!realpath(SD_HOST_LOCALTIME_FILE, path) ||
        !realpath(SD_HOST_ZONEINFO_DIRECTORY, directory))
        return 0;
    size_t prefix = strlen(directory);
    if (strncmp(path, directory, prefix) || path[prefix] != '/' ||
        stat(path, &info) || !S_ISREG(info.st_mode) ||
        info.st_uid != 0 || (info.st_mode & 022))
        return 0;
    const char *identifier = path + prefix + 1;
    if (!strncmp(identifier, "posix/", 6) || !strncmp(identifier, "right/", 6))
        identifier += 6;
    size_t length = strlen(identifier);
    if (!length || length >= 92)
        return 0;
    for (size_t index = 0; index < length; ++index) {
        unsigned char byte = (unsigned char)identifier[index];
        if (!((byte >= 'A' && byte <= 'Z') || (byte >= 'a' && byte <= 'z') ||
              (byte >= '0' && byte <= '9') || strchr("/_+-", byte)))
            return 0;
    }
    FILE *file = fopen(path, "rb");
    if (!file)
        return 0;
    char magic[4];
    size_t count = fread(magic, 1, sizeof(magic), file);
    fclose(file);
    if (count != sizeof(magic) || memcmp(magic, "TZif", sizeof(magic)))
        return 0;
    int (*set_private)(const char *, const char *) =
        dlsym(private_libc, "bionic___system_property_set");
    int (*get_private)(const char *, char *) =
        dlsym(private_libc, "bionic___system_property_get");
    if (!set_private || !get_private)
        return -1;
    pthread_mutex_lock(&timezone_lock);
    char previous[92] = {0};
    int size = get_private("persist.sys.timezone", previous);
    int result = -1;
    if (size >= 0 && size < (int)sizeof(previous) &&
        strnlen(previous, sizeof(previous)) == (size_t)size) {
        const char *environment = getenv("TZ");
        if (!strcmp(previous, identifier) && environment &&
            !strcmp(environment, identifier)) {
            result = 1;
        } else if (!set_private("persist.sys.timezone", identifier)) {
            if (!setenv("TZ", identifier, 1)) {
                tzset();
                fprintf(stderr, "SDTIMEZONE=imported|source=host-localtime|id=%s\n", identifier);
                result = 1;
            } else {
                set_private("persist.sys.timezone", previous);
            }
        }
    }
    if (result == 1)
        memcpy(timezone, identifier, length + 1);
    pthread_mutex_unlock(&timezone_lock);
    return result;
}

/* The component's Android properties describe its private userland. Hardware
 * service readiness belongs to the running phone, rather than build.prop.
 * Import only this non-secret, read-only host fact through libhybris's native
 * property reader. The setter handle is the private translator's property
 * table; no host property setter or external command is used. */
int sd_import_host_hardware_properties(void *private_libc) {
    int (*set_private)(const char *, const char *) =
        dlsym(private_libc, "bionic___system_property_set");
    struct stat info;
    if (!set_private || stat(SD_HOST_PROPERTY_LIBRARY, &info) ||
        !S_ISREG(info.st_mode) || info.st_uid != 0 || (info.st_mode & 022)) {
        fputs("SDHARDWARE_PROPERTIES=unavailable|reason=trusted-reader-missing\n", stderr);
        return 0;
    }
    void *library = dlopen(SD_HOST_PROPERTY_LIBRARY, RTLD_NOW | RTLD_LOCAL);
    int (*get_host)(const char *, char *, const char *) =
        library ? dlsym(library, "my_property_get") : NULL;
    if (!get_host) {
        fputs("SDHARDWARE_PROPERTIES=unavailable|reason=host-reader-missing\n", stderr);
        if (library) dlclose(library);
        return 0;
    }
    const char *key = "hwservicemanager.ready";
    char value[92] = {0};
    int count = get_host(key, value, "");
    if (count <= 0 || count >= (int)sizeof(value) ||
        strnlen(value, sizeof(value)) != (size_t)count) {
        fputs("SDHARDWARE_PROPERTIES=unavailable|reason=host-value-absent\n", stderr);
        dlclose(library);
        return 0;
    }
    if (strcmp(value, "true") && strcmp(value, "false")) {
        fputs("SDHARDWARE_PROPERTIES=unavailable|reason=host-value-invalid\n", stderr);
        dlclose(library);
        return 0;
    }
    int result = set_private(key, value);
    fprintf(stderr, "SDHARDWARE_PROPERTIES=%s|property=%s|source=host-libhybris|value=%s\n",
            result ? "error" : "imported", key, value);
    dlclose(library);
    return result ? -1 : 1;
}

static int valid_product_value(const char *value, int product_token) {
    size_t length = strnlen(value, 92);
    if (!length || length >= 92 || value[0] == ' ' || value[length - 1] == ' ')
        return 0;
    for (size_t index = 0; index < length; ++index) {
        unsigned char byte = (unsigned char)value[index];
        if (byte < 32 || byte == 127)
            return 0;
        if (product_token && !((byte >= 'A' && byte <= 'Z') ||
                               (byte >= 'a' && byte <= 'z') ||
                               (byte >= '0' && byte <= '9') ||
                               strchr("._,-", byte)))
            return 0;
    }
    return 1;
}

static int read_hardware_device(char device[92]) {
    struct stat info;
    if (stat(SD_HOST_HARDWARE_FILE, &info) || !S_ISREG(info.st_mode) ||
        info.st_uid != 0 || (info.st_mode & 022) || info.st_size > 16384)
        return 0;
    FILE *file = fopen(SD_HOST_HARDWARE_FILE, "r");
    if (!file)
        return 0;
    char line[512], identifier[92] = {0};
    int valid = 1;
    while (fgets(line, sizeof(line), file)) {
        if (!strchr(line, '\n') && !feof(file)) {
            valid = 0;
            break;
        }
        char *separator = strchr(line, '=');
        if (!separator)
            continue;
        *separator = '\0';
        if (strcmp(line, "ID") && strcmp(line, "MER_HA_DEVICE"))
            continue;
        char *value = separator + 1;
        value[strcspn(value, "\r\n")] = '\0';
        size_t length = strlen(value);
        if (length >= 2 && ((value[0] == '"' && value[length - 1] == '"') ||
                            (value[0] == '\'' && value[length - 1] == '\''))) {
            value[length - 1] = '\0';
            ++value;
        }
        if (!valid_product_value(value, 1)) {
            valid = 0;
            break;
        }
        strcpy(!strcmp(line, "MER_HA_DEVICE") ? device : identifier, value);
    }
    valid = valid && !ferror(file);
    fclose(file);
    if (!device[0])
        strcpy(device, identifier);
    return valid && device[0];
}

/* Read one complete, adaptation-confirmed group before modifying the private
 * table. The application's Build and native SystemProperties then share the
 * current device's public identity, including sibling-image adaptations. */
int sd_import_host_product_properties(void *private_libc) {
    int (*set_private)(const char *, const char *) =
        dlsym(private_libc, "bionic___system_property_set");
    struct stat info;
    char device[92] = {0};
    if (!set_private || stat(SD_HOST_PROPERTY_LIBRARY, &info) ||
        !S_ISREG(info.st_mode) || info.st_uid != 0 || (info.st_mode & 022) ||
        !read_hardware_device(device)) {
        fputs("SDPRODUCT_PROPERTIES=unavailable|reason=trusted-host-input-missing\n", stderr);
        return 0;
    }
    void *library = dlopen(SD_HOST_PROPERTY_LIBRARY, RTLD_NOW | RTLD_LOCAL);
    int (*get_host)(const char *, char *, const char *) =
        library ? dlsym(library, "my_property_get") : NULL;
    if (!get_host) {
        fputs("SDPRODUCT_PROPERTIES=unavailable|reason=host-reader-missing\n", stderr);
        if (library) dlclose(library);
        return 0;
    }
    const char *fields[] = {"manufacturer", "brand", "model", "name", "device"};
    const char *groups[] = {"ro.product.vendor.", "ro.product."};
    char values[5][92] = {{0}};
    const char *selected = NULL;
    for (size_t group = 0; group < sizeof(groups) / sizeof(groups[0]); ++group) {
        int complete = 1;
        for (size_t field = 0; field < sizeof(fields) / sizeof(fields[0]); ++field) {
            char key[64];
            snprintf(key, sizeof(key), "%s%s", groups[group], fields[field]);
            memset(values[field], 0, sizeof(values[field]));
            int count = get_host(key, values[field], "");
            if (count <= 0 || count >= (int)sizeof(values[field]) ||
                strnlen(values[field], sizeof(values[field])) != (size_t)count ||
                !valid_product_value(values[field], field >= 3)) {
                complete = 0;
                break;
            }
        }
        if (complete && !strcmp(values[4], device)) {
            selected = groups[group];
            break;
        }
    }
    if (!selected) {
        fputs("SDPRODUCT_PROPERTIES=unavailable|reason=unconfirmed-product-group\n", stderr);
        dlclose(library);
        return 0;
    }
    for (size_t field = 0; field < sizeof(fields) / sizeof(fields[0]); ++field) {
        char key[64];
        snprintf(key, sizeof(key), "ro.product.%s", fields[field]);
        if (set_private(key, values[field])) {
            fprintf(stderr, "SDPRODUCT_PROPERTIES=error|property=%s\n", key);
            dlclose(library);
            return -1;
        }
    }
    fprintf(stderr, "SDPRODUCT_PROPERTIES=imported|source=%s|manufacturer=%s|model=%s|device=%s\n",
            selected, values[0], values[2], values[4]);
    dlclose(library);
    return 1;
}
