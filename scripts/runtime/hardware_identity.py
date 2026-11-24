"""Provision public hardware identity without changing Android userland claims.

This is a per-device build.prop input, shared by Build, SystemProperties and the
native property reader. It never reads persistent device/account identifiers.
"""
import json
import re
from pathlib import Path

FIELDS = ('manufacturer', 'brand', 'model', 'name', 'device')
SCHEMA = 'saildroid-hardware-profile-v1'
ALIASES_SCHEMA = 'saildroid-hardware-aliases-v1'
ALIASES_FILE = 'hardware-identity-aliases.json'


def checked(value):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError('Missing or padded hardware identity')
    if len(value.encode('utf-8')) >= 92 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid hardware property value')
    return value


def load_aliases(path=None):
    path = Path(__file__).with_name(ALIASES_FILE) if path is None else Path(path)
    if not path.is_file():
        return {}
    document = json.loads(path.read_text())
    if document.get('schema') != ALIASES_SCHEMA or not isinstance(document.get('aliases'), dict):
        raise ValueError('Unsupported hardware alias table')
    result = {}
    for anchor, values in document['aliases'].items():
        checked(anchor)
        if not isinstance(values, list) or not values:
            raise ValueError('Invalid hardware alias entry')
        result[anchor] = [checked(value) for value in values]
        if not all(re.fullmatch(r'[A-Za-z0-9._,-]+', value) for value in result[anchor]):
            raise ValueError('Invalid hardware alias name')
    return result


def select_identity(profile, device_aliases=None):
    if profile.get('schema') != SCHEMA:
        raise ValueError('Unsupported hardware profile')
    observed = profile['properties']
    # Sailfish adaptations can retain a system image from a sibling device.
    # Select one complete group, confirmed by the hardware adaptation, rather
    # than mixing the sibling's system model with this device's vendor name.
    # Ports whose Sailfish hardware id differs from the Android base product
    # name register the mapping in hardware-identity-aliases.json.
    if device_aliases is None:
        device_aliases = load_aliases()
    anchors = {checked(v) for v in (profile.get('hardware_device'),
                                    profile.get('boot_hardware')) if v}
    if not anchors:
        raise ValueError('Hardware profile has no device confirmation')
    for anchor in list(anchors):
        anchors.update(checked(alias) for alias in device_aliases.get(anchor, ()))
    for group in ('vendor.', ''):
        keys = ['ro.product.' + group + field for field in FIELDS]
        values = [observed.get(key, '') for key in keys]
        if not all(values):
            continue
        values = [checked(value) for value in values]
        if values[-1] not in anchors:
            continue
        if not all(re.fullmatch(r'[A-Za-z0-9._,-]+', value) for value in values[3:]):
            raise ValueError('Invalid hardware product/device name')
        return ({'ro.product.' + field: value for field, value in zip(FIELDS, values)},
                {'source_group': 'ro.product.' + group,
                 'source_keys': keys, 'confirmed_device': values[-1]})
    raise ValueError('No complete hardware identity agrees with the device')


def apply_identity(text, profile, device_aliases=None):
    from component_properties import properties
    before = properties(text)
    identity, evidence = select_identity(profile, device_aliases)
    if not set(identity) <= set(before):
        raise ValueError('Component lacks the existing hardware property fields')
    lines = []
    for line in text.splitlines():
        key = line.partition('=')[0]
        lines.append(key + '=' + identity[key] if key in identity else line)
    result = '\n'.join(lines) + '\n'
    after = properties(result)
    assert {k: v for k, v in before.items() if k not in identity} == {
        k: v for k, v in after.items() if k not in identity}
    return result, dict(schema=SCHEMA, **evidence, properties=identity,
                       changed={k: dict(before=before[k], after=v)
                                for k, v in identity.items() if before[k] != v})