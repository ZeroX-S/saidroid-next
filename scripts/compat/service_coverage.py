"""Enumerate service signatures and the source dispatch routes that can reach them."""
from pathlib import Path
import re

from jni_coverage import closing, without_comments


def dispatch_names(text):
    variables = set(re.findall(r'\b(\w+)\s*=\s*\w+\.getName\s*\(\s*\)', text))
    names = set()
    for variable in variables:
        names.update(re.findall(r'\b' + re.escape(variable) + r'\.equals\s*\(\s*"([^"\n]+)"\s*\)', text))
        names.update(re.findall(r'"([^"\n]+)"\.equals\s*\(\s*' + re.escape(variable) + r'\s*\)', text))
        for match in re.finditer(r'\bswitch\s*\(\s*' + re.escape(variable) + r'\s*\)\s*\{', text):
            end = closing(text, match.end() - 1, '{', '}')
            names.update(re.findall(r'\bcase\s+"([^"\n]+)"\s*:', text[match.end():end]))
    names.update(re.findall(r'"([^"\n]+)"\.equals\s*\(\s*\w+\.getName\s*\(\s*\)\s*\)', text))
    names.update(re.findall(r'\w+\.getName\s*\(\s*\)\.equals\s*\(\s*"([^"\n]+)"\s*\)', text))
    return names - {'toString', 'hashCode', 'equals', 'asBinder'}


def coverage(java_directory, inventory):
    directories = [java_directory] if isinstance(java_directory, (str, Path)) else list(java_directory)
    sources = {path.stem: (path, without_comments(path.read_text(encoding='utf-8')))
               for directory in reversed(directories) for path in Path(directory).glob('*.java')}
    rows, routes = [], []
    for source_name, (path, text) in sources.items():
        if 'InvocationHandler' not in text or 'Proxy' not in text:
            continue
        interfaces = set()
        for candidate in re.findall(r'"([\w.]+)"', text):
            name = candidate.replace('.', '/')
            definition = inventory.classes.get(name)
            if definition and definition.access & 0x200:
                interfaces.add(name)
        imports = dict((name.rsplit('.', 1)[1], name.replace('.', '/'))
                       for name in re.findall(r'\bimport\s+([\w.]+)\s*;', text))
        for candidate in re.findall(r'\b([\w.]+)\.class\b', text):
            name = imports.get(candidate, candidate.replace('.', '/'))
            definition = inventory.classes.get(name)
            if definition and definition.access & 0x200:
                interfaces.add(name)
        names = dispatch_names(text)
        handlers = {name: [str(path)] for name in names}
        # A delegated handler is reachable through its advertised handles() set.
        # A branch omitted from that set is retained as a disconnected route.
        for helper in re.findall(r'\b(\w+)\.handles\s*\(', text):
            if helper not in sources:
                routes.append(dict(source=str(path), helper=helper, reason='missing-delegate-source'))
                continue
            helper_path, helper_text = sources[helper]
            branches = dispatch_names(helper_text)
            advertised = set()
            for match in re.finditer(r'\b(?:operations|METHODS|methods)\s*=\s*[^;]+;', helper_text):
                advertised.update(re.findall(r'"([^"\n]+)"', match.group()))
            if not advertised:
                routes.append(dict(source=str(path), helper=helper, reason='dynamic-delegate-selection'))
            for name in branches & advertised:
                handlers.setdefault(name, []).append(str(helper_path))
            for name in sorted(advertised - branches):
                routes.append(dict(source=str(path), helper=helper, name=name,
                                   reason='advertised-without-dispatch-branch'))
            interface_methods = {name for interface in interfaces
                                 for name, _ in inventory.classes[interface].methods}
            for name in sorted((branches - advertised) & interface_methods - names):
                routes.append(dict(source=str(path), helper=helper, name=name,
                                   reason='dispatch-branch-not-advertised'))
        for interface in sorted(interfaces):
            definition = inventory.classes[interface]
            for (name, descriptor), flags in sorted(definition.methods.items()):
                if flags & 8 or name in ('<clinit>', '<init>'):
                    continue
                rows.append(dict(interface=interface, name=name, descriptor=descriptor,
                                 source=str(path), dispatch_sources=handlers.get(name, []),
                                 state='dispatch-name-present' if name in handlers else 'unhandled',
                                 behavior='requires-contract-test'))
    return dict(signatures=rows, route_problems=routes,
                totals=dict(interfaces=len({row['interface'] for row in rows}),
                            signatures=len(rows),
                            dispatch_names=sum(row['state'] == 'dispatch-name-present' for row in rows),
                            unhandled=sum(row['state'] == 'unhandled' for row in rows)),
                scope='Source dispatch reachability by name. Exact interface descriptors are recorded; behavior and overload handling require contract tests.')
