#!/usr/bin/env python3
"""Observe ordinary public capabilities before/after measured metadata changes."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--release', required=True)
p.add_argument('--expected-boot', required=True)
p.add_argument('--compare', type=Path)
a = p.parse_args()
assert re.fullmatch(r'r[0-9]+-native-candidate', a.release)
repo = Path(__file__).resolve().parents[2]
base = repo / 'build/evidence/cts-frame-repair-20261031'
built = Path('/var/tmp/saidroid-private-multicodec-capabilities-20261031')
manifest = json.loads((built / 'manifest.json').read_text())
source = repo / 'scripts/runtime/tests/media/MultiCodecCapabilitiesInstrumentation.java'
assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['source_sha256']
apk = manifest['apks'][0]
assert apk['debuggable'] is False
assert not any(json.loads(f.read_text())['status'] == 'RUNNING'
               for f in (base / 'modules').glob('*/attempt.json'))
tag = a.release.split('-')[0]
out = base / 'gates' / ('public-multicodec-' + tag)
out.mkdir()
label = 'cts' + tag[1:] + '-private-public-multicodec-snapshot'
plan = dict(label=label, module='PrivatePublicMultiCodecSnapshot',
            root='/home/art/releases/api29-' + a.release, package=apk['package'],
            test_package=apk['package'], component=apk['package'] + '/' + manifest['instrumentation'],
            arguments={}, timeout=90, expected_boot=a.expected_boot, apks=[apk],
            dynamic_configs=[], pushed_files=[], hidden_api_checks=True)
(out / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
original = built / apk['file']
assert hashlib.sha256(original.read_bytes()).hexdigest() == apk['sha256']
shutil.copyfile(original, out / original.name)
try:
    subprocess.run(['python3', str(repo / 'scripts/cts/run-instrument-vm.py'),
                    str(out / 'plan.json')], check=True, timeout=390)
finally:
    (out / original.name).unlink(missing_ok=True)
result = json.loads((out / label / 'run-result.json').read_text())
assert result['status'] == 'COMPLETED' and result['brightness'] == '0'
assert all(result[k] for k in ('boot_unchanged', 'lipstick_unchanged', 'daily_root_unchanged'))
assert not any(result.get(k) for k in ('cleanup_error', 'cleanup_timeout', 'cleanup_process_alive'))
assert all(result[k]['ready'] for k in ('compositor_before', 'compositor_after'))
events = [json.loads(l) for l in (out / label / 'instrumentation-events.jsonl').read_text().splitlines()]
tests = [e for e in events if e.get('event') == 'status' and e.get('bundle', {}).get('test')]
assert [e['code'] for e in tests] == [1, 0]
assert result['instrumentation']['code'] == -1
values = result['instrumentation']['results']
support = json.loads(values['support_snapshot'])
measured = json.loads(values['measured_snapshot'])
assert set(support) == set(measured) == {'OMX.google.vp8.encoder', 'OMX.google.vp9.encoder'}
record = dict(scope='Ordinary signed public API snapshot, not CTS', runtime=a.release,
              support=support, measured=measured, apk_sha256=apk['sha256'],
              source_sha256=manifest['source_sha256'], boot=result['boot'],
              cleanup_safe=True)
if a.compare:
    before = json.loads(a.compare.read_text())
    assert before['support'] == support and before['apk_sha256'] == apk['sha256']
    assert before['source_sha256'] == record['source_sha256'] and before['boot'] == record['boot']
    assert any(v is None for v in before['measured']['OMX.google.vp9.encoder'].values())
    assert all(value is not None for rates in measured.values() for value in rates.values())
    record['native_coding_capabilities_unchanged'] = True
    record['all_supported_sizes_have_measured_rates'] = True
output = base / ('public-multicodec-' + tag + '.json')
assert not output.exists()
output.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
