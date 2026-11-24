"""Compare a runtime's declared members with the pinned public SDK surface."""
import importlib.util
from pathlib import Path


def api28_members():
    source = Path(__file__).resolve().parents[1] / 'api28/encode-platform-dex.py'
    specification = importlib.util.spec_from_file_location('sdk28_encoder', source)
    encoder = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(encoder)
    return encoder.api28_public_members()


def audit(inventory, members=None):
    expected = api28_members() if members is None else set(members)
    owners = set()
    missing, inaccessible = [], []
    inherited = 0
    for signature in sorted(expected):
        owner, member = signature.split('->', 1)
        owner = owner[1:-1]
        owners.add(owner)
        if '(' in member:
            start = member.index('(')
            kind, name, descriptor = 'method', member[:start], member[start:]
        else:
            name, descriptor = member.split(':', 1)
            kind = 'field'
        resolved = inventory.resolve(kind, owner, name, descriptor)
        if resolved is None:
            missing.append(signature)
        elif not resolved[1] & 5:
            inaccessible.append(signature)
        elif resolved[0].name != owner:
            inherited += 1
    return dict(api=28, passed=not missing and not inaccessible,
                sdk='Official API28 revision 6 public/protected declarations',
                expected_members=len(expected), resolved_members=len(expected) - len(missing),
                resolved_via_inheritance=inherited, declaring_classes=len(owners),
                missing_classes=sorted(owners - inventory.classes.keys()),
                missing_members=missing, inaccessible_members=inaccessible,
                scope='Declared Java signatures and public/protected access. Hidden-API policy, JNI and behavior have separate checks.')
