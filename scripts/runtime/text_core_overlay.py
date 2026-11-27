"""Compile optional Android10 text adapters against matching ICU class declarations.

The native LocaleData ABI remains the private legacy ABI. Explicit source and
matching ICU63 class inputs prevent javac from silently using another field type
or inlining the old ICU resource location. Unchanged nested class bytes survive.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import zipfile

FAMILIES = {
    'decimal-compat': {'java/text/DecimalFormat.java',
                       'java/text/DecimalFormatSymbols.java',
                       'libcore/icu/LocaleData.java'},
    'date-format': {'java/text/DateFormatSymbols.java',
                    'java/text/SimpleDateFormat.java'},
}


def verify_source_family(source, family):
    directory = source / family
    provenance = json.loads((directory / 'sources.json').read_text())
    assert set(provenance['files']) == FAMILIES[family]
    repo = source.parents[2]
    for name, entry in provenance['files'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == entry['sha256']
        assert hashlib.sha256((repo / entry['baseline_source']).read_bytes()).hexdigest() == entry['baseline_sha256']
    return provenance


def build_text_overlays(output, source, baseline, platform_icu, java, framework,
                        decimal_compat=False, date_format=False):
    enabled = [name for name, flag in [('decimal-compat', decimal_compat),
                                      ('date-format', date_format)] if flag]
    if not enabled:
        return {}, {}
    assert platform_icu, 'Android10 text adapters require matching ICU63 class inputs'
    assert 'android/icu/text/DecimalFormat_ICU58_Android.class' in platform_icu
    provenance = {name: verify_source_family(source, name) for name in enabled}
    compile_root = output / 'text-overlay'
    compile_root.mkdir()
    classes = compile_root / 'classes'
    classes.mkdir()
    # ICU_BASE_NAME is a compile-time constant. The legacy class tree contains
    # ICU58; merely adding a newer framework JAR afterward leaves stale literals.
    boot = compile_root / 'compile-boot.jar'
    with zipfile.ZipFile(boot, 'x', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(baseline.rglob('*.class')):
            name = str(file.relative_to(baseline))
            if not name.startswith('android/icu/'):
                archive.writestr(name, file.read_bytes())
        for name, data in sorted(platform_icu.items()):
            archive.writestr(name, data)
    sources = [source / family / name for family in enabled
               for name in sorted(provenance[family]['files'])]
    subprocess.run([str(java.with_name('javac')), '-source', '8', '-target', '8',
                    '-nowarn', '-bootclasspath', str(boot) + ':' + str(framework),
                    '-d', str(classes), *map(str, sources)], check=True)
    expected = {name[:-5] + '.class' for family in enabled
                for name in provenance[family]['files']}
    generated = {str(file.relative_to(classes)): file
                 for file in classes.rglob('*.class')}
    assert expected <= generated.keys()
    for name in generated.keys() - expected:
        assert any(name.startswith(main[:-6] + '$') for main in expected), name
        original = baseline / name
        assert original.is_file(), 'Unexpected new nested text class: ' + name
        before = subprocess.run([str(java.with_name('javap')), '-p', '-c', '-s',
                                 str(original)], capture_output=True, text=True,
                                check=True).stdout
        after = subprocess.run([str(java.with_name('javap')), '-p', '-c', '-s',
                                str(generated[name])], capture_output=True,
                               text=True, check=True).stdout
        assert before == after, 'Unexpected nested text behavior change: ' + name
    return {name: generated[name] for name in expected}, provenance
