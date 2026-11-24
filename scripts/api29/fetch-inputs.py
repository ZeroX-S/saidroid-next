#!/usr/bin/env python3
"""Fetch pinned API 28 framework, R8, and ARM64 system libraries without installation."""
from pathlib import Path
from urllib.request import Request, urlopen
import argparse, hashlib, json, os, time

ASSETS = {
 'arm64-v8a-28_r02.zip': ('https://dl.google.com/android/repository/sys-img/android/arm64-v8a-28_r02.zip', 'e209114dd0dfc2f4e0d328f5fd7367fec39ee1bd', 426760297),
 'android-all-9-robolectric-4913185-2.jar': ('https://maven-central.storage-download.googleapis.com/maven2/org/robolectric/android-all/9-robolectric-4913185-2/android-all-9-robolectric-4913185-2.jar', None, None),
 'android-all-10-robolectric-5803371.jar': ('https://maven-central.storage-download.googleapis.com/maven2/org/robolectric/android-all/10-robolectric-5803371/android-all-10-robolectric-5803371.jar', None, None),
 'r8-8.3.37.jar': ('https://dl.google.com/dl/android/maven2/com/android/tools/r8/8.3.37/r8-8.3.37.jar', '6b023243a76124fb055d66b50e2e11db9b4d9b2b', None),
}
SHA256 = {
 'arm64-v8a-28_r02.zip': '86844d2edf6ba7c7f11261f6be3fb37788c985cfcf3b8924cfe9f57a1ccbc0a9',
 'android-all-9-robolectric-4913185-2.jar': 'cf4aed5e458deb48ddc0ca92fc25156e6f478d9d5c1d948cdd1817a67ee11b32',
 'android-all-10-robolectric-5803371.jar': 'a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c',
 'r8-8.3.37.jar': '59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439',
}

def open_url(url, timeout):
 return urlopen(Request(url, headers={'User-Agent': 'saidroid-fetch-inputs/1.0'}), timeout=timeout)

def fetch(directory, skip_sysimg=False):
 directory.mkdir(parents=True, exist_ok=True); records = {}
 for name, (url, expected, size) in ASSETS.items():
  if skip_sysimg and name.endswith('.zip'):
   continue
  target = directory / name
  if expected is None:
   expected = open_url(url + '.sha1', timeout=30).read().decode().strip().split()[0]
   if len(expected) != 40: raise RuntimeError('Invalid upstream checksum')
  if not target.exists():
   temporary = target.with_suffix(target.suffix + '.part')
   with open_url(url, timeout=60) as source, temporary.open('wb') as output:
    total = 0; last = time.monotonic()
    while True:
     block = source.read(1024 * 1024)
     if not block: break
     output.write(block); total += len(block)
     if time.monotonic() - last > 15: print(name, total, flush=True); last = time.monotonic()
    output.flush(); os.fsync(output.fileno())
   temporary.rename(target)
  sha1 = hashlib.sha1(); sha256 = hashlib.sha256()
  with target.open('rb') as source:
   for block in iter(lambda: source.read(1024 * 1024), b''): sha1.update(block); sha256.update(block)
  if sha1.hexdigest() != expected or sha256.hexdigest() != SHA256[name] or (size is not None and target.stat().st_size != size):
   raise RuntimeError('Upstream integrity check failed: ' + name)
  records[name] = dict(url=url, sha1=sha1.hexdigest(), sha256=sha256.hexdigest(), size=target.stat().st_size)
  print('API28_INPUT=verified|file=' + name + '|sha256=' + sha256.hexdigest(), flush=True)
 (directory / 'inputs.json').write_text(json.dumps(dict(api=28, assets=records), indent=2) + '\n')

if __name__ == '__main__':
 parser = argparse.ArgumentParser()
 parser.add_argument('directory', type=Path)
 parser.add_argument('--skip-sysimg', action='store_true', help='Skip downloading the large ARM64 system image when only Java/preflight inputs are needed')
 args = parser.parse_args()
 fetch(args.directory, skip_sysimg=args.skip_sysimg)
