"""Verify media JNI protection and legitimate dependency initialization."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


parser = argparse.ArgumentParser()
parser.add_argument('baseline', type=Path)
parser.add_argument('candidate', type=Path)
parser.add_argument('--cc', default='gcc')
parser.add_argument('--qemu')
parser.add_argument('--sysroot', type=Path)
parser.add_argument('--library-path', type=Path)
args = parser.parse_args()
assert (args.qemu is None) == (args.sysroot is None)

runner_source = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

static int dependency_calls;
static int own_calls;
static int delegated_calls;
void fixture_onload(int owner) {
    if (owner == 1) ++dependency_calls;
    else if (owner == 2) ++own_calls;
    else if (owner == 3) ++delegated_calls;
    else assert(0);
}

int main(int argc, char **argv) {
    assert(argc == 4);
    int inherited_expected = atoi(argv[3]);
    void *linker = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL);
    if (!linker) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    void *(*open_guest)(const char *, int) = dlsym(linker, "bionic_dlopen");
    void *(*symbol_guest)(void *, const char *) = dlsym(linker, "bionic_dlsym");
    int (*close_guest)(void *) = dlsym(linker, "bionic_dlclose");
    const char *(*error_guest)(void) = dlsym(linker, "bionic_dlerror");
    int (*add_path)(const char *) = dlsym(linker, "bionic_add_library_path");
    assert(open_guest && symbol_guest && close_guest && error_guest && add_path);
    assert(add_path(argv[2]) == 0);

    void *leaf = open_guest("leaf.so", RTLD_NOW);
    assert(leaf);
    int (*value)(void) = symbol_guest(leaf, "dependency_value");
    assert(value && value() == 73);
    int (*imported_onload)(void) = symbol_guest(leaf, "call_dependency_onload");
    assert(imported_onload && imported_onload() == 0x10006);
    assert(dependency_calls == 1);

    int (*inherited)(void *, void *) = symbol_guest(leaf, "JNI_OnLoad");
    assert((inherited != NULL) == inherited_expected);
    if (inherited) {
        assert(inherited(NULL, NULL) == 0x10006);
        assert(dependency_calls == 2);
    } else {
        assert(error_guest() && !error_guest());
        assert(dependency_calls == 1);
    }

    void *own = open_guest("own.so", RTLD_NOW);
    assert(own);
    int (*initialize)(void *, void *) = symbol_guest(own, "JNI_OnLoad");
    assert(initialize && initialize(NULL, NULL) == 0x10006);
    assert(own_calls == 1 && dependency_calls == 1 + inherited_expected);
    value = symbol_guest(own, "dependency_value");
    assert(value && value() == 73);

    void *client = open_guest("delegated-client.so", RTLD_NOW);
    assert(client);
    initialize = symbol_guest(client, "JNI_OnLoad");
    assert(initialize && initialize(NULL, NULL) == 0x10006);
    assert(delegated_calls == 1);
    void *delegated = open_guest("delegated.so", RTLD_NOW);
    assert(delegated);
    initialize = symbol_guest(delegated, "JNI_OnLoad");
    assert(initialize && initialize(NULL, NULL) == 0x10006);
    assert(delegated_calls == 2);
    assert(close_guest(delegated) == 0 && close_guest(client) == 0);
    assert(close_guest(own) == 0 && close_guest(leaf) == 0);
    printf("JNI_ENTRYPOINT=PASS|inherited_media=%d|own_calls=%d|media_calls=%d|delegated_calls=%d|transitive_symbol=73\n",
           inherited_expected, own_calls, dependency_calls, delegated_calls);
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='saildroid-jni-entrypoint-') as temporary:
    folder = Path(temporary)
    (folder / 'config').mkdir()

    def library(name, body, *dependencies):
        source = folder / (name + '.c')
        source.write_text(body)
        command = [args.cc, '-shared', '-fPIC', '-nostdlib', '-Wl,--hash-style=both',
                   '-Wl,-soname,' + name + '.so', '-o', str(folder / (name + '.so')), str(source)]
        if dependencies:
            command.extend(['-Wl,--no-as-needed', *map(str, dependencies)])
        subprocess.run(command, check=True, timeout=60)

    library('libmedia_jni', 'extern void fixture_onload(int);\n'
            'int JNI_OnLoad(void *vm, void *reserved) { (void)vm; (void)reserved; fixture_onload(1); return 0x10006; }\n'
            'int dependency_value(void) { return 73; }\n')
    library('middle', 'extern int dependency_value(void); int middle(void) { return dependency_value(); }\n',
            folder / 'libmedia_jni.so')
    library('leaf', 'extern int JNI_OnLoad(void *, void *);\n'
            'int call_dependency_onload(void) { return JNI_OnLoad((void *)0, (void *)0); }\n',
            folder / 'middle.so')
    library('own', 'extern void fixture_onload(int);\n'
            'int JNI_OnLoad(void *vm, void *reserved) { (void)vm; (void)reserved; fixture_onload(2); return 0x10006; }\n',
            folder / 'middle.so')
    library('delegated', 'extern void fixture_onload(int);\n'
            'int JNI_OnLoad(void *vm, void *reserved) { (void)vm; (void)reserved; fixture_onload(3); return 0x10006; }\n')
    library('delegated-client', 'int delegated_client(void) { return 75; }\n', folder / 'delegated.so')
    source = folder / 'runner.c'
    source.write_text(runner_source)
    subprocess.run([args.cc, '-O2', '-Wall', '-Wextra', '-Werror', '-rdynamic',
                    str(source), '-ldl', '-o', str(folder / 'runner')], check=True, timeout=60)
    environment = dict(os.environ, SAILDROID_STRICT_LINK='1',
                       BIONIC_TRANSLATION_CONFIG_DIR=str(folder / 'config'))
    if args.library_path:
        environment['LD_LIBRARY_PATH'] = str(args.library_path.resolve())
    prefix = [args.qemu, '-L', str(args.sysroot)] if args.qemu else []
    results = []
    for name, linker, expected in (('baseline', args.baseline, 1), ('candidate', args.candidate, 0)):
        result = subprocess.run(prefix + [str(folder / 'runner'), str(linker.resolve()), str(folder), str(expected)],
                                env=environment, capture_output=True, text=True, timeout=15)
        row = dict(label=name, exit=result.returncode, output=result.stdout, error=result.stderr[-3000:])
        results.append(row)
        print(json.dumps(row), flush=True)
        assert result.returncode == 0, row
    print(json.dumps(dict(passed=True, results=results)), flush=True)
