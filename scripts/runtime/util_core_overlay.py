"""Compile optional API29 array/null and timezone behavior corrections.

The original public, package and native declarations remain available. Only
explicitly changed nested implementations are replaced; other generated nested
classes must have identical instructions before retaining their original bytes.
"""
from pathlib import Path
import hashlib
import json
import subprocess

FAMILIES = {
    'util-compat': {
        'sources': {'java/util/Arrays.java', 'java/util/Objects.java'},
        'classes': {'java/util/Arrays.class', 'java/util/Objects.class'},
    },
    'zoneinfo-compat': {
        'sources': {'libcore/util/ZoneInfo.java'},
        'classes': {'libcore/util/ZoneInfo.class', 'libcore/util/ZoneInfo$WallTime.class'},
    },
}


def verify_source_family(source, family):
    directory = source / family
    record = json.loads((directory / 'sources.json').read_text())
    assert set(record['files']) == FAMILIES[family]['sources']
    repo = source.parents[2]
    for name, entry in record['files'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == entry['sha256']
        assert hashlib.sha256((repo / entry['baseline_source']).read_bytes()).hexdigest() == entry['baseline_sha256']
    return record


def build_util_overlays(output, source, baseline, java, framework,
                        util_compat=False, zoneinfo_compat=False):
    enabled = [name for name, flag in [('util-compat', util_compat),
                                      ('zoneinfo-compat', zoneinfo_compat)] if flag]
    if not enabled:
        return {}, {}
    records = {family: verify_source_family(source, family) for family in enabled}
    classes = output / 'util-overlay'
    classes.mkdir()
    sources = [source / family / name for family in enabled
               for name in sorted(records[family]['files'])]
    subprocess.run([str(java.with_name('javac')), '-source', '8', '-target', '8',
                    '-nowarn', '-bootclasspath', str(baseline) + ':' + str(framework),
                    '-d', str(classes), *map(str, sources)], check=True)
    expected = set().union(*(FAMILIES[family]['classes'] for family in enabled))
    generated = {str(path.relative_to(classes)): path for path in classes.rglob('*.class')}
    assert expected <= generated.keys()
    main = {name[:-5] for family in enabled for name in FAMILIES[family]['sources']}
    for name in generated.keys() - expected:
        assert any(name.startswith(prefix + '$') for prefix in main), name
        original = baseline / name
        assert original.is_file(), 'Unexpected new nested compatibility class: ' + name
        before = subprocess.run([str(java.with_name('javap')), '-p', '-c', '-s',
                                 str(original)], capture_output=True, text=True,
                                check=True).stdout
        after = subprocess.run([str(java.with_name('javap')), '-p', '-c', '-s',
                                str(generated[name])], capture_output=True,
                               text=True, check=True).stdout
        assert before == after, 'Unexpected nested compatibility change: ' + name
    return {name: generated[name] for name in expected}, records
