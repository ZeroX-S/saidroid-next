#ifndef SAIDROID_SYSTEM_PATHS_H
#define SAIDROID_SYSTEM_PATHS_H
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

/* Native Android font readers use absolute system paths independently of Java
 * Typeface. Translate only this platform-owned font namespace in this process.
 * The compatibility library owns/frees a successful replacement string.
 */
static bool saidroid_private_font_path(const char *root, char **path) {
    if (!root || root[0] != '/' || !path || !*path) return false;
    const char *suffix = NULL;
    if (!strcmp(*path, "/system/etc/fonts.xml")) suffix = "/etc/fonts.xml";
    else if (!strcmp(*path, "/system/etc/system_fonts.xml")) suffix = "/etc/system_fonts.xml";
    else if (!strcmp(*path, "/system/etc/fallback_fonts.xml")) suffix = "/etc/fallback_fonts.xml";
    else if (!strncmp(*path, "/system/fonts/", 14)) suffix = *path + 7;
    else if (!strcmp(*path, "/system/fonts")) suffix = "/fonts";
    if (!suffix) return false;
    size_t length = strlen(root) + strlen(suffix) + 1;
    char *replacement = malloc(length);
    if (!replacement) return false;
    strcpy(replacement, root);
    strcat(replacement, suffix);
    *path = replacement;
    return true;
}

#endif
