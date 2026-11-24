#!/usr/bin/env python3
"""Read only the public model fields needed for a per-phone component profile."""
from pathlib import Path
import hashlib
import json
import os
import shlex
import subprocess

assert 'ID=sailfishos' in Path('/etc/sailfish-release').read_text()
reader = Path('/usr/bin/getprop').resolve(strict=True)
info = reader.stat()
assert reader.is_file() and info.st_uid == 0 and not info.st_mode & 0o022


def read(key):
    p = subprocess.run([str(reader), key], capture_output=True, text=True,
                       check=True, timeout=4, env={'PATH': '/usr/bin:/bin'})
    return p.stdout.rstrip('\n')


hardware = {}
for line in Path('/etc/hw-release').read_text().splitlines():
    key, sep, value = line.partition('=')
    if sep and key in ('ID', 'MER_HA_DEVICE', 'NAME'):
        values = shlex.split(value)
        assert len(values) == 1
        hardware[key] = values[0]
fields = ('manufacturer', 'brand', 'model', 'name', 'device')
properties = {('ro.product.' + group + field): read('ro.product.' + group + field)
              for group in ('', 'vendor.') for field in fields}
print(json.dumps(dict(schema='saildroid-hardware-profile-v1', properties=properties,
                     hardware_device=hardware.get('MER_HA_DEVICE', hardware.get('ID')),
                     hardware_name=hardware.get('NAME'), boot_hardware=read('ro.boot.hardware'),
                     boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                     reader=str(reader), reader_sha256=hashlib.sha256(reader.read_bytes()).hexdigest()),
                 indent=2))
