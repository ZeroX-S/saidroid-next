"""Optional restoration of the existing deprecated Runtime loader SDK guard."""
from pathlib import Path
import hashlib
import json
import subprocess


CLASSES = {'java/lang/Runtime.class'}


def verify_source_family(source):
    directory = source / 'runtime-load-compat'
    record = json.loads((directory / 'sources.json').read_text())
    assert set(record['files']) == {'java/lang/Runtime.java'}
    repo = source.parents[2]
    for name, entry in record['files'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == entry['sha256']
        baseline = (repo / entry['baseline_source']).read_text()
        assert hashlib.sha256(baseline.encode()).hexdigest() == entry['baseline_sha256']
        before = '        //checkTargetSdkVersionForLoad("java.lang.Runtime#loadLibrary(String, ClassLoader)");'
        after = '        checkTargetSdkVersionForLoad("java.lang.Runtime#loadLibrary(String, ClassLoader)");'
        assert entry['changed_line_before'] == before and entry['changed_line_after'] == after
        assert baseline.count(before) == 1
        wrapper_before = entry['native_load_before']
        wrapper_after = entry['native_load_after']
        assert baseline.count(wrapper_before) == 1
        assert (directory / name).read_text() == baseline.replace(before, after).replace(
            wrapper_before, wrapper_after)
    return record


def build_runtime_load_overlay(output, source, baseline, java, framework, enabled=False):
    if not enabled:
        return {}, None
    record = verify_source_family(source)
    classes = output / 'runtime_load-overlay'
    classes.mkdir()
    subprocess.run([str(java.with_name('javac')), '-source', '8', '-target', '8',
                    '-nowarn', '-bootclasspath', str(baseline) + ':' + str(framework),
                    '-d', str(classes),
                    str(source / 'runtime-load-compat/java/lang/Runtime.java')], check=True)
    generated = {str(path.relative_to(classes)): path for path in classes.rglob('*.class')}
    assert generated.keys() == CLASSES
    return generated, record
