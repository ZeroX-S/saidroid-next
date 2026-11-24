"""Sibling system/vendor images must resolve one confirmed hardware identity."""
from pathlib import Path
import copy
import json
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware_identity import apply_identity, load_aliases, select_identity, FIELDS, SCHEMA
from component_properties import properties

profile = dict(schema=SCHEMA, hardware_device='device-xl', boot_hardware='device-xl',
               properties={})
for group, model, device in [('', 'Phone', 'device'), ('vendor.', 'Phone XL', 'device-xl')]:
    for field, value in zip(FIELDS, ('Vendor', 'vendor', model, device, device)):
        profile['properties']['ro.product.' + group + field] = value
base = ''.join('ro.product.' + field + '=SailDroid\n' for field in FIELDS)
base += 'ro.build.fingerprint=private/component/identity\nro.build.version.sdk=29\nro.hardware=component-wayland\n'
text, report = apply_identity(base, profile)
assert properties(text)['ro.product.model'] == 'Phone XL'
assert report['source_group'] == 'ro.product.vendor.'
assert properties(text)['ro.build.fingerprint'] == 'private/component/identity'
assert apply_identity(text, profile)[0] == text
for mutate in ('unconfirmed', 'partial', 'injected', 'oversized'):
    bad = copy.deepcopy(profile)
    if mutate == 'unconfirmed':
        bad['hardware_device'] = bad['boot_hardware'] = 'other'
    elif mutate == 'partial':
        del bad['properties']['ro.product.vendor.brand']
    elif mutate == 'injected':
        bad['properties']['ro.product.vendor.model'] += '\nro.build.version.sdk=99'
    else:
        bad['properties']['ro.product.vendor.model'] = 'x' * 92
    try:
        select_identity(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(mutate)
fallback = copy.deepcopy(profile)
fallback['properties'] = {k: v for k, v in profile['properties'].items() if '.vendor.' not in k}
fallback['hardware_device'] = fallback['boot_hardware'] = 'device'
assert select_identity(fallback)[0]['ro.product.model'] == 'Phone'
alias_profile = dict(schema=SCHEMA, hardware_device='fajita', boot_hardware='qcom', properties={})
for field, value in zip(FIELDS, ('OnePlus', 'OnePlus', 'ONEPLUS A6013', 'OnePlus6T', 'OnePlus6T')):
    alias_profile['properties']['ro.product.' + field] = value
try:
    select_identity(alias_profile, {})
except ValueError:
    pass
else:
    raise AssertionError('port_alias_required')
assert select_identity(alias_profile, {'fajita': ['OnePlus6T']})[0]['ro.product.device'] == 'OnePlus6T'
assert load_aliases()['fajita'] == ['OnePlus6T']
alias_text, alias_report = apply_identity(base, alias_profile)
assert properties(alias_text)['ro.product.model'] == 'ONEPLUS A6013'
assert alias_report['confirmed_device'] == 'OnePlus6T'
assert properties(alias_text)['ro.build.version.sdk'] == '29'
unrelated = copy.deepcopy(alias_profile)
unrelated['hardware_device'] = 'another-port'
try:
    select_identity(unrelated)
except ValueError:
    pass
else:
    raise AssertionError('generic_qcom_must_not_confirm_oneplus')
with tempfile.TemporaryDirectory() as d:
    table = Path(d)/'aliases.json'
    assert load_aliases(table) == {}
    for invalid in ({'schema': 'wrong', 'aliases': {}},
                    {'schema': 'saildroid-hardware-aliases-v1', 'aliases': {'fajita': []}},
                    {'schema': 'saildroid-hardware-aliases-v1', 'aliases': {'fajita': ['bad/name']}},
                    {'schema': 'saildroid-hardware-aliases-v1', 'aliases': {'fajita': ['bad\nname']}}):
        table.write_text(json.dumps(invalid))
        try:
            load_aliases(table)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid_alias_table_accepted')
print('HARDWARE_IDENTITY=passed|coherent_group|hardware_confirmation|unrelated_properties_preserved|invalid_rejected|port_alias|alias_profile_apply|alias_isolation|invalid_table')
