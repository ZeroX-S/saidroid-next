"""Optional Android10 serialization warning API over the retained native ABI."""
from pathlib import Path
import hashlib
import json
import subprocess


CLASSES = {'java/io/ObjectStreamClass.class',
           'java/io/ObjectStreamClass$DefaultSUIDCompatibilityListener.class'}


def verify_source_family(source):
    directory = source / 'objectstream-compat'
    record = json.loads((directory / 'sources.json').read_text())
    assert set(record['files']) == {'java/io/ObjectStreamClass.java'}
    repo = source.parents[2]
    for name, entry in record['files'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == entry['sha256']
        assert hashlib.sha256((repo / entry['baseline_source']).read_bytes()).hexdigest() == entry['baseline_sha256']
    return record


def build_objectstream_overlay(output, source, baseline, java, framework, enabled=False):
    if not enabled:
        return {}, None
    record = verify_source_family(source)
    classes = output / 'objectstream-overlay'
    classes.mkdir()
    subprocess.run([str(java.with_name('javac')), '-source', '8', '-target', '8',
                    '-nowarn', '-bootclasspath', str(baseline) + ':' + str(framework),
                    '-d', str(classes),
                    str(source / 'objectstream-compat/java/io/ObjectStreamClass.java')], check=True)
    generated = {str(path.relative_to(classes)): path for path in classes.rglob('*.class')}
    assert CLASSES <= generated.keys()
    for name in generated.keys() - CLASSES:
        assert name.startswith('java/io/ObjectStreamClass$'), name
        original = baseline / name
        assert original.is_file(), 'Unexpected new nested serialization class: ' + name
        before = subprocess.check_output([str(java.with_name('javap')), '-p', '-c', '-s',
                                          str(original)], text=True)
        after = subprocess.check_output([str(java.with_name('javap')), '-p', '-c', '-s',
                                         str(generated[name])], text=True)
        assert before == after, 'Unexpected nested serialization change: ' + name
    return {name: generated[name] for name in CLASSES}, record
