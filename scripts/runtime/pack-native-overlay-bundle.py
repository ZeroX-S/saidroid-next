#!/usr/bin/env python3
"""Package a v3 overlay and verify every archive member in one sequential pass."""
import argparse
import hashlib
import io
import json
import tarfile
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--overlay', required=True)
parser.add_argument('--payload-root', action='append', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
started = time.monotonic()
overlay = Path(args.overlay).resolve()
data = overlay.read_bytes()
meta = json.loads(data)
assert meta['schema'] == 'saildroid-native-overlay-v3'
roots = [Path(p).resolve() for p in args.payload_root]
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=False)

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

sources = {}
for name, row in meta['changes'].items():
    assert name and not name.startswith('/') and '..' not in Path(name).parts
    assert row == meta['install_manifest']['files'][name]
    candidates = (root / name for root in roots)
    source = next((p for p in candidates if p.is_file() and not p.is_symlink()
                   and p.stat().st_size == row['size']
                   and digest(p) == row['sha256']), None)
    assert source is not None, name
    sources[name] = source

(out / 'overlay.json').write_bytes(data)
archive = out / 'native-overlay.tar.gz'
pending = out / 'native-overlay.pending'
with tarfile.open(pending, 'w:gz') as tar:
    for name, source in sorted(sources.items()):
        row = meta['changes'][name]
        info = tarfile.TarInfo('payload/' + name)
        info.size, info.mode = row['size'], row['mode']
        info.uid = info.gid = info.mtime = 0
        with source.open('rb') as stream:
            tar.addfile(info, stream)
    info = tarfile.TarInfo('overlay.json')
    info.size, info.mode = len(data), 0o644
    info.uid = info.gid = info.mtime = 0
    tar.addfile(info, io.BytesIO(data))

seen = set()
with tarfile.open(pending, 'r|gz') as tar:
    for member in tar:
        assert member.isfile() and member.name not in seen
        seen.add(member.name)
        stream = tar.extractfile(member)
        if member.name == 'overlay.json':
            assert stream.read() == data
            continue
        assert member.name.startswith('payload/')
        name = member.name[8:]
        row = meta['changes'][name]
        assert member.size == row['size'] and member.mode == row['mode']
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
        assert h.hexdigest() == row['sha256'], name
assert seen == {'overlay.json'} | {'payload/' + name for name in sources}
pending.replace(archive)
record = dict(passed=True, path=str(archive), sha256=digest(archive),
              bytes=archive.stat().st_size, overlay_sha256=digest(overlay),
              install_manifest_sha256=hashlib.sha256((json.dumps(
                  meta['install_manifest'], indent=2) + '\n').encode()).hexdigest(),
              files=len(meta['install_manifest']['files']),
              symlinks=len(meta['install_manifest']['symlinks']),
              overlay_files=len(sources), seconds=time.monotonic() - started,
              validation='one sequential pass; every member hash and mode checked',
              sources={name: str(path) for name, path in sources.items()})
(out / 'bundle-proof.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({k: v for k, v in record.items() if k != 'sources'}, indent=2))
