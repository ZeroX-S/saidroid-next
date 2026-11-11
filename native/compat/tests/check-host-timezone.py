#!/usr/bin/env python3
"""Exercise the native timezone import and Java default-zone updates on Linux."""
import argparse
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


PRIVATE = r'''
#include <dlfcn.h>
#include <jni.h>
#include <stdlib.h>
#include <string.h>
static char timezone[92] = "UTC";
static int fail_set;
int sd_import_host_timezone_properties(void *, char [92]);
int bionic___system_property_get(const char *key, char *value) {
    if (strcmp(key, "persist.sys.timezone")) abort();
    strcpy(value, timezone);
    return strlen(value);
}
int bionic___system_property_set(const char *key, const char *value) {
    if (strcmp(key, "persist.sys.timezone")) abort();
    if (fail_set) return -1;
    strcpy(timezone, value);
    return 0;
}
void reset(void) { strcpy(timezone, "UTC"); fail_set = 0; }
const char *current(void) { return timezone; }
void fail(int value) { fail_set = value; }
JNIEXPORT jstring JNICALL Java_SdTimeZone_refreshNative(JNIEnv *env, jclass type) {
    (void)type;
    void *library = dlopen(getenv("SD_TIMEZONE_TEST_LIBRARY"), RTLD_NOW | RTLD_LOCAL);
    char value[92];
    int result = sd_import_host_timezone_properties(library, value);
    dlclose(library);
    if (result < 0) {
        (*env)->ThrowNew(env, (*env)->FindClass(env, "java/lang/IllegalStateException"), "Fixture property write failed");
        return NULL;
    }
    return result ? (*env)->NewStringUTF(env, value) : NULL;
}
JNIEXPORT jstring JNICALL Java_HostTimeZoneWatchProbe_privateZone(JNIEnv *env, jclass type) {
    (void)type;
    return (*env)->NewStringUTF(env, timezone);
}
'''

SYSTEM_PROPERTIES = r'''
package android.os;
public final class SystemProperties {
    public static String get(String key, String fallback) {
        return fallback;
    }
}
'''

SERVICES = r'''
public final class SdServices {
    public static volatile int changes;
    public static void notifyTimeZoneChanged(String identifier) { changes++; }
}
'''

WATCH = r'''
import java.nio.file.*;
import java.util.TimeZone;
import org.apache.harmony.luni.internal.util.TimezoneGetter;
public final class HostTimeZoneWatchProbe {
    public static native String privateZone();
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    public static void main(String[] arguments) throws Exception {
        System.load(System.getenv("SD_TIMEZONE_TEST_LIBRARY"));
        TimeZone.setDefault(TimeZone.getTimeZone("UTC"));
        SdTimeZone.install();
        check(TimeZone.getDefault().getID().equals("Asia/Shanghai"), "Initial Java timezone differs");
        check(TimezoneGetter.getInstance().getId().equals("Asia/Shanghai"), "Android getter differs");
        check(privateZone().equals("Asia/Shanghai"), "Initial private property differs");
        TimeZone.setDefault(TimeZone.getTimeZone("Europe/Berlin"));
        SdTimeZone.install();
        check(TimeZone.getDefault().getID().equals("Europe/Berlin"), "Repeated install reset application override");
        Path selected = Paths.get(arguments[0]);
        Path replacement = selected.resolveSibling("replacement");
        Files.createSymbolicLink(replacement, Paths.get(arguments[1]));
        Files.move(replacement, selected, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        long deadline = System.nanoTime() + 10000000000L;
        while ((SdServices.changes == 0 || !TimeZone.getDefault().getID().equals("America/New_York"))
                && System.nanoTime() < deadline) Thread.sleep(50);
        check(privateZone().equals("America/New_York"), "Changed private property differs");
        check(TimeZone.getDefault().getID().equals("America/New_York"), "Live Java timezone did not change");
        check(SdServices.changes == 1, "Timezone change notification differs");
        check(TimeZone.getDefault().getOffset(1577836800000L) == -18000000, "Winter offset differs");
        check(TimeZone.getDefault().getOffset(1593561600000L) == -14400000, "Summer offset differs");
        TimeZone.setDefault(TimeZone.getTimeZone("UTC"));
        Thread.sleep(5500);
        check(TimeZone.getDefault().getID().equals("UTC") && SdServices.changes == 1,
              "Unchanged host reset the application's explicit default");
        Files.delete(selected);
        Thread.sleep(5500);
        check(privateZone().equals("America/New_York") && SdServices.changes == 1,
              "Unavailable host input changed the private timezone");
        for (Thread thread : Thread.getAllStackTraces().keySet()) {
            if (thread.getName().equals("Saildroid timezone")) {
                check(thread.isDaemon(), "Watcher blocks process exit");
                thread.interrupt();
                thread.join(1000);
                check(!thread.isAlive(), "Watcher did not stop after interruption");
            }
        }
        System.out.println("HOST_TIMEZONE_WATCH=PASS|cases=12");
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--jni-include', type=Path, required=True)
    arguments = parser.parse_args()
    assert os.geteuid() == 0, 'Run the isolated fixtures as WSL root'
    repository = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix='saildroid-timezone-test-') as temporary:
        work = Path(temporary)
        zones = work / 'zoneinfo'
        selected = work / 'localtime'
        private_source = work / 'private.c'
        private_source.write_text(PRIVATE, encoding='utf-8', newline='\n')
        library = work / 'timezone.so'
        subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(arguments.jni_include), '-I' + str(arguments.jni_include / 'linux'),
                        '-DSD_HOST_LOCALTIME_FILE="' + str(selected) + '"',
                        '-DSD_HOST_ZONEINFO_DIRECTORY="' + str(zones) + '"',
                        str(repository / 'native/compat/api29-hardware-properties.c'),
                        str(private_source), '-o', str(library), '-ldl', '-pthread'], check=True)
        native = ctypes.CDLL(str(library))
        native.current.restype = ctypes.c_char_p
        native.sd_import_host_timezone_properties.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        value = ctypes.create_string_buffer(92)
        cases = 0
        for identifier in ('Asia/Shanghai', 'America/New_York', 'Europe/Berlin',
                           'Asia/Kolkata', 'Asia/Kathmandu', 'Pacific/Chatham', 'Etc/UTC', 'Etc/GMT+3'):
            zone = zones / identifier
            zone.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path('/usr/share/zoneinfo') / identifier, zone)
            zone.chmod(0o644)
            selected.unlink(missing_ok=True)
            selected.symlink_to(zone)
            native.reset()
            assert native.sd_import_host_timezone_properties(native._handle, value) == 1
            assert value.value.decode() == identifier and native.current().decode() == identifier
            cases += 1
        zone = zones / 'Asia/Shanghai'
        for mode, owner, expected in ((0o666, 0, 0), (0o644, 65534, 0), (0o644, 0, 1)):
            zone.chmod(mode)
            os.chown(zone, owner, owner)
            selected.unlink()
            selected.symlink_to(zone)
            native.reset()
            assert native.sd_import_host_timezone_properties(native._handle, value) == expected
            cases += 1
        native.reset()
        native.fail(1)
        assert native.sd_import_host_timezone_properties(native._handle, value) == -1
        assert native.current() == b'UTC'
        native.fail(0)
        assert native.sd_import_host_timezone_properties(native._handle, value) == 1
        cases += 2
        print('HOST_TIMEZONE_IMPORT=PASS|cases=' + str(cases), flush=True)
        sources = []
        for name, text in (('android/os/SystemProperties.java', SYSTEM_PROPERTIES),
                           ('SdServices.java', SERVICES), ('HostTimeZoneWatchProbe.java', WATCH)):
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8', newline='\n')
            sources.append(str(path))
        classes = work / 'classes'
        subprocess.run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn',
                        '-sourcepath', '', '-cp', str(arguments.framework), '-d', str(classes),
                        *sources, str(repository / 'scripts/device/SdTimeZone.java')], check=True)
        environment = dict(os.environ, SD_TIMEZONE_TEST_LIBRARY=str(library))
        subprocess.run(['java', '-cp', str(classes) + os.pathsep + str(arguments.framework),
                        'HostTimeZoneWatchProbe', str(selected), str(zones / 'America/New_York')],
                       env=environment, check=True, timeout=35)


if __name__ == '__main__':
    main()
