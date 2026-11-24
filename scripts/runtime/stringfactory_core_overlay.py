"""Optional Android10 UTF8 decoder over the unchanged StringFactory native ABI."""
from pathlib import Path
import hashlib
import json
import subprocess


CLASSES = {'java/lang/StringFactory.class'}


def verify_source_family(source):
    directory = source / 'stringfactory-compat'
    record = json.loads((directory / 'sources.json').read_text())
    assert set(record['files']) == {'java/lang/StringFactory.java'}
    repo = source.parents[2]
    for name, entry in record['files'].items():
        text = (directory / name).read_text()
        baseline = (repo / entry['baseline_source']).read_text()
        assert hashlib.sha256(text.encode()).hexdigest() == entry['sha256']
        assert hashlib.sha256(baseline.encode()).hexdigest() == entry['baseline_sha256']
        start = '        if (canonicalCharsetName.equals("UTF-8")) {'
        end = '        } else if (canonicalCharsetName.equals("ISO-8859-1")) {'
        old = baseline[baseline.index(start):baseline.index(end)]
        new = text[text.index(start):text.index(end)]
        table_start = text.index('    private static final int[] TABLE_UTF8_NEEDED')
        table_end = text.index('    };', table_start) + len('    };')
        table = text[table_start:table_end]
        assert hashlib.sha256(old.encode()).hexdigest() == entry['old_block_sha256']
        assert hashlib.sha256(new.encode()).hexdigest() == entry['new_block_sha256']
        assert hashlib.sha256(table.encode()).hexdigest() == entry['table_sha256']
        anchor = ('    // TODO: Implement this method natively.\n'
                  '    public static String newStringFromBytes(byte[] data, int offset, int byteCount, Charset charset)')
        assert text == baseline.replace(old, new).replace(anchor, table + '\n\n' + anchor)
    return record


def build_stringfactory_overlay(output, source, baseline, java, framework, enabled=False):
    if not enabled:
        return {}, None
    record = verify_source_family(source)
    classes = output / 'stringfactory-overlay'
    classes.mkdir()
    subprocess.run([str(java.with_name('javac')), '-source', '8', '-target', '8',
                    '-nowarn', '-bootclasspath', str(baseline) + ':' + str(framework),
                    '-d', str(classes),
                    str(source / 'stringfactory-compat/java/lang/StringFactory.java')], check=True)
    generated = {str(path.relative_to(classes)): path for path in classes.rglob('*.class')}
    assert generated.keys() == CLASSES
    return generated, record
