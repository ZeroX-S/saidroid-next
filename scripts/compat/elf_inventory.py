"""Inspect ARM64 native dependencies without loading application libraries."""
import hashlib
import json
from collections import deque
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


def inspect(path):
    text = subprocess.check_output(['readelf', '--wide', '--file-header', '--dynamic',
                                    '--dyn-syms', str(path)], text=True, errors='replace')
    exports, imports, weak = set(), set(), set()
    for line in text.splitlines():
        match = re.match(r'\s*\d+:\s+\S+\s+\d+\s+\S+\s+(GLOBAL|WEAK)\s+\S+\s+(\S+)\s+(\S+)', line)
        if not match:
            continue
        binding, section, name = match.groups()
        if section == 'UND':
            (weak if binding == 'WEAK' else imports).add(name)
        else:
            exports.add(name)
    soname = re.search(r'\(SONAME\).*\[([^]]+)\]', text)
    machine = re.search(r'Machine:\s*(.+)', text)
    return dict(soname=soname.group(1) if soname else Path(path).name,
                machine=machine.group(1).strip() if machine else 'unknown',
                needed=re.findall(r'\(NEEDED\).*\[([^]]+)\]', text),
                exports=exports, imports=imports, weak_imports=weak)


def scan_applications(apks, runtime_root):
    cache = {}
    names = {}
    pending = deque()
    host_directory = Path('/usr/lib/aarch64-linux-gnu')

    def load(path, role):
        real = path.resolve()
        if real not in cache:
            with real.open('rb') as source:
                if source.read(4) != b'\x7fELF':
                    return None
            entry = inspect(real)
            if entry['machine'] != 'AArch64':
                return None
            entry.update(path=str(real), role=role,
                         sha256=hashlib.sha256(real.read_bytes()).hexdigest())
            cache[real] = entry
            pending.extend(entry['needed'])
        names[path.name] = real
        names[cache[real]['soname']] = real
        return real

    # Inspect the packaged providers once. Host inspection follows only the
    # runtime mappings and transitive DT_NEEDED names reached by these inputs.
    for folder in (runtime_root / 'lib', runtime_root / 'android-libs'):
        for path in sorted(folder.rglob('*')):
            if '.so' in path.name and path.is_file():
                load(path, 'packaged-runtime')

    runtime = json.loads((runtime_root / 'runtime.json').read_text())
    installed = '/opt/saildroid/releases/' + runtime.get('rpm_activation', {}).get('release_id', runtime_root.name)
    aliases = []
    configuration = runtime_root / 'linker-config/runtime.cfg'
    if configuration.exists():
        for line in configuration.read_text().splitlines():
            parts = line.split('#', 1)[0].split()
            if len(parts) != 2:
                continue
            name, target = parts
            if target.startswith(installed + '/'):
                candidate = runtime_root / target[len(installed) + 1:]
            elif target.startswith('/'):
                candidate = Path(target)
            else:
                candidate = names.get(target, host_directory / target)
            resolved = load(Path(candidate), 'linker-mapping') if Path(candidate).is_file() else None
            aliases.append(dict(name=name, target=target, available=resolved is not None))
            if resolved:
                names[name] = resolved

    applications = []
    with tempfile.TemporaryDirectory(prefix='saildroid-elf-scan-') as temporary:
        for apk_index, apk in enumerate(apks):
            entries = []
            with zipfile.ZipFile(apk) as archive:
                native = [item for item in archive.infolist()
                          if item.filename.startswith('lib/arm64-v8a/') and item.filename.endswith('.so')]
                for index, item in enumerate(native):
                    if item.file_size > 256 * 1024 * 1024:
                        raise ValueError('Native APK entry exceeds 256 MiB: ' + item.filename)
                    data = archive.read(item)
                    path = Path(temporary) / ('library-' + str(apk_index) + '-' + str(index) + '.so')
                    path.write_bytes(data)
                    entry = inspect(path)
                    entry.update(path=item.filename, sha256=hashlib.sha256(data).hexdigest())
                    entries.append(entry)
                    pending.extend(entry['needed'])
            applications.append(dict(input=str(apk), entries=entries))

        visited_names = set()
        while pending:
            name = pending.popleft()
            if name in names or name in visited_names:
                continue
            visited_names.add(name)
            candidate = host_directory / name
            if candidate.is_file():
                load(candidate, 'host-dependency')

        base_symbols = {name.split('@', 1)[0] for entry in cache.values() for name in entry['exports']}
        for application in applications:
            entries = application.pop('entries')
            app_names = {name for entry in entries for name in (Path(entry['path']).name, entry['soname'])}
            app_symbols = {name.split('@', 1)[0] for entry in entries for name in entry['exports']}
            symbols = base_symbols | app_symbols
            application['libraries'] = [dict(
                path=entry['path'], sha256=entry['sha256'], machine=entry['machine'], needed=entry['needed'],
                missing_libraries=sorted(set(entry['needed']) - names.keys() - app_names),
                potential_missing_symbols=sorted(name for name in entry['imports']
                                                 if name.split('@', 1)[0] not in symbols),
                weak_imports=sorted(entry['weak_imports'])) for entry in entries]

    providers = [dict(path=entry['path'], sha256=entry['sha256'], role=entry['role'],
                      soname=entry['soname'], needed=entry['needed'], exports=len(entry['exports']))
                 for entry in cache.values()]
    return dict(applications=applications, providers=providers, linker_aliases=aliases,
                scope='Static ARM64 symbol-name candidates across packaged providers and reached host dependencies. Symbol versions, namespace visibility, relocation and dlopen behavior require execution.')
