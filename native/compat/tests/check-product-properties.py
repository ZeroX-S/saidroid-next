"""Check live public device imports using the actual native adapter."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile


HOST = r'''
#include <stdlib.h>
#include <string.h>
int my_property_get(const char *key, char *out, const char *fallback) {
    const char *value = getenv(key);
    if (!value) value = fallback;
    size_t length = strlen(value);
    size_t copied = length < 92 ? length : 91;
    memcpy(out, value, copied);
    out[copied] = '\0';
    return length;
}
int my_property_set(const char *key, const char *value) {
    (void)key; (void)value;
    abort();
}
'''

PRIVATE = r'''
#include <stdlib.h>
#include <string.h>
static const char *keys[] = {"ro.product.manufacturer", "ro.product.brand", "ro.product.model",
                            "ro.product.name", "ro.product.device", "ro.build.version.sdk",
                            "ro.build.version.release", "ro.build.tags"};
static char values[8][92];
static int calls;
void reset(void) {
    for (int index = 0; index < 8; ++index) strcpy(values[index], "baseline");
    strcpy(values[5], "28"); strcpy(values[6], "9"); strcpy(values[7], "test-keys");
    calls = 0;
}
int bionic___system_property_set(const char *key, const char *value) {
    ++calls;
    const char *fail = getenv("SD_PRODUCT_FAIL_AT");
    if (fail && calls == atoi(fail)) return -1;
    for (int index = 0; index < 5; ++index) {
        if (!strcmp(key, keys[index])) {
            strcpy(values[index], value);
            return 0;
        }
    }
    abort();
}
const char *get(int index) { return values[index]; }
int writes(void) { return calls; }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    source = arguments.source or repository / 'native/compat/api29-hardware-properties.c'
    fields = ('manufacturer', 'brand', 'model', 'name', 'device')
    vendor = dict(zip(('ro.product.vendor.' + name for name in fields),
                      ('Xiaomi', 'Xiaomi', '21051182G', 'nabu_global', 'nabu')))
    system = dict(zip(('ro.product.' + name for name in fields),
                      ('Google', 'google', 'Pixel 3a', 'sargo', 'sargo')))
    with tempfile.TemporaryDirectory(prefix='sd-product-properties-') as temporary:
        root = Path(temporary)
        host_source = root / 'host.c'
        host_source.write_text(HOST, encoding='utf-8', newline='\n')
        private_source = root / 'private.c'
        private_source.write_text(PRIVATE, encoding='utf-8', newline='\n')
        host, private, helper = (root / name for name in ('host.so', 'private.so', 'helper.so'))
        hardware = root / 'hw-release'
        hardware.write_text('ID=nabu\nMER_HA_DEVICE=nabu\nNAME="Xiaomi Xiaomi Pad 5"\n')
        subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(host_source), '-o', str(host)], check=True)
        subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(private_source), '-o', str(private)], check=True)
        subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-DSD_HOST_PROPERTY_LIBRARY="' + str(host) + '"',
                        '-DSD_HOST_HARDWARE_FILE="' + str(hardware) + '"',
                        str(source), '-o', str(helper), '-ldl'], check=True)
        state = ctypes.CDLL(str(private))
        state.get.argtypes = [ctypes.c_int]
        state.get.restype = ctypes.c_char_p
        adapter = ctypes.CDLL(str(helper))
        try:
            read = adapter.sd_import_host_product_properties
        except AttributeError:
            raise SystemExit('DEVICE_PRODUCT_REGRESSION=FAIL|live product import absent')
        read.argtypes = [ctypes.c_void_p]
        read.restype = ctypes.c_int
        completed = []

        def exercise(label, properties, expected=None, contents='ID=nabu\nMER_HA_DEVICE=nabu\n'):
            for name in list(os.environ):
                if name.startswith('ro.product.') or name == 'SD_PRODUCT_FAIL_AT':
                    del os.environ[name]
            os.environ.update(properties)
            hardware.write_text(contents)
            hardware.chmod(0o644)
            host.chmod(0o755)
            state.reset()
            result = read(state._handle)
            actual = [state.get(index).decode() for index in range(8)]
            assert actual[5:] == ['28', '9', 'test-keys'], (label, actual)
            if expected is None:
                assert result == 0 and state.writes() == 0 and actual[:5] == ['baseline'] * 5, (label, result, actual)
            else:
                assert result == 1 and state.writes() == 5 and actual[:5] == expected, (label, result, actual)
            completed.append(label)

        values = list(vendor.values())
        exercise('vendor-group-over-sibling-system', {**system, **vendor}, values)
        current_system = {'ro.product.' + field: value for field, value in zip(fields, values)}
        exercise('complete-system-fallback', current_system, values)
        sibling_vendor = {key.replace('ro.product.', 'ro.product.vendor.'): value for key, value in system.items()}
        exercise('mismatched-vendor-system-fallback', {**sibling_vendor, **current_system}, values)
        exercise('id-anchor-fallback', vendor, values, 'ID=nabu\n')
        exercise('quoted-hardware-device', vendor, values, 'ID="nabu"\nMER_HA_DEVICE=\'nabu\'\n')
        exercise('missing-all-product-fields', {})
        exercise('unconfirmed-sibling-group', system)
        for field in fields:
            missing = dict(vendor)
            del missing['ro.product.vendor.' + field]
            exercise('missing-' + field, missing)
        exercise('maximum-model-length', {**vendor, 'ro.product.vendor.model': 'x' * 91},
                 [values[0], values[1], 'x' * 91, values[3], values[4]])
        for label, field, value in (('padded-model', 'model', ' invalid'),
                                    ('control-model', 'model', 'invalid\nname'),
                                    ('oversize-model', 'model', 'x' * 91 + 'y'),
                                    ('invalid-device-token', 'device', '../nabu'),
                                    ('invalid-product-token', 'name', 'nabu global')):
            properties = dict(vendor)
            properties['ro.product.vendor.' + field] = value
            exercise(label, properties)
        exercise('invalid-adaptation-anchor', vendor, contents='MER_HA_DEVICE=../nabu\n')
        exercise('missing-adaptation-anchor', vendor, contents='NAME="Xiaomi Pad 5"\n')
        exercise('unavailable-reader-setup', {})
        os.environ.update(vendor)
        host.chmod(0o666)
        state.reset()
        assert read(state._handle) == 0 and state.writes() == 0
        completed.append('untrusted-reader')
        host.chmod(0o755)
        hardware.write_text('ID=nabu\n')
        hardware.chmod(0o666)
        state.reset()
        assert read(state._handle) == 0 and state.writes() == 0
        completed.append('untrusted-adaptation')
        hardware.chmod(0o644)
        state.reset()
        os.environ['SD_PRODUCT_FAIL_AT'] = '3'
        assert read(state._handle) == -1 and state.writes() == 3
        bridge = (repository / 'scripts/device/sdbridge.c').read_text(encoding='utf-8')
        command = (repository / 'native/commands/private-getprop.cpp').read_text(encoding='utf-8')
        assert 'if (sd_import_host_product_properties(gh) < 0)' in bridge
        assert 'sd_import_host_product_properties(handle)>=0' in command
        completed.append('failed-import-stops-bootstrap')
        print('DEVICE_PRODUCT_REGRESSION=PASS|cases=' + str(len(completed)) + '|private_table_only=true')
        print(json.dumps(completed))


if __name__ == '__main__':
    main()
