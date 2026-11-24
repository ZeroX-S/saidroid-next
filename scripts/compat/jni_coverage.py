"""Audit literal JNI contracts and retain dynamic/conditional sites for review."""
from pathlib import Path
import re


STRING = r'"(?:\\.|[^"\\])*"'
FUNCTION = re.compile(r'^(?:extern\s+"C"\s+)?[\w\s*:<>&]+\b(\w+)\s*\([^;{}]*\)\s*\{', re.M)
TABLE = re.compile(r'\bJNINativeMethod\s+(\w+)\s*(?:\[[^]]*\])?\s*=\s*\{')
ENTRY = re.compile(r'\{?\s*"([^"\n]+)"\s*,\s*"([^"\n]+)"\s*,\s*(?:\(void\s*\*\))?\s*(\w+)\s*[,}]')
CALL = re.compile(r'\b(FindClass|Get(?:Static)?(?:Field|Method)ID|RegisterNatives)\s*\(')
COMMENTS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/')


def without_comments(text):
    return COMMENTS.sub(lambda match: match.group() if match.group()[0] in '\"\''
                        else re.sub(r'[^\n]', ' ', match.group()), text)


def closing(text, start, left, right):
    depth = 0
    quote = None
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if quote:
            if character == quote and not escaped:
                quote = None
            escaped = character == '\\' and not escaped
            continue
        if character in ('"', "'"):
            quote = character
        elif character == left:
            depth += 1
        elif character == right:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError('Unterminated native expression')


def arguments(text):
    parts = []
    start = 0
    depth = 0
    for token in re.finditer(STRING + r'|[(){}\[\],]', text):
        value = token.group()
        if value in ('(', '{', '['):
            depth += 1
        elif value in (')', '}', ']'):
            depth -= 1
        elif value == ',' and depth == 0:
            parts.append(text[start:token.start()].strip())
            start = token.end()
    parts.append(text[start:].strip())
    return parts


def calls(text):
    for match in CALL.finditer(text):
        end = closing(text, match.end() - 1, '(', ')')
        yield match.start(), match.group(1), arguments(text[match.end():end])


def literal(expression):
    match = re.fullmatch(STRING, expression)
    return expression[1:-1] if match else None


def audit(paths, inventory, api, incomplete_prefixes=()):
    checked, unresolved, problems = [], [], []
    for path in paths:
        text = without_comments(Path(path).read_text(encoding='utf-8'))
        functions = []
        for match in FUNCTION.finditer(text):
            if match.group(1) in ('if', 'for', 'while', 'switch'):
                continue
            end = closing(text, match.end() - 1, '{', '}')
            functions.append((match.start(), end, match.group(1), text[match.end():end]))
        bindings = {}
        local_bindings = {}
        globals = set()
        for declaration in re.findall(r'\bstatic\s+jclass\s+([^;{}]+);', text):
            globals.update(re.findall(r'\b\w+\b', declaration))
        for position, operation, args in calls(text):
            if operation != 'FindClass' or not literal(args[-1]):
                continue
            before = text[max(text.rfind(';', 0, position), text.rfind('{', 0, position),
                              text.rfind('}', 0, position)) + 1:position]
            assignments = re.findall(r'(\w+)\s*=\s*(?!=)', before)
            if assignments:
                variable = assignments[-1]
                bindings.setdefault(variable, set()).add(literal(args[-1]))
                context = next((item for item in functions if item[0] <= position <= item[1]), None)
                if context:
                    local_bindings.setdefault(context[2], {}).setdefault(variable, set()).add(literal(args[-1]))

        def owner(expression, function):
            if 'FindClass' in expression:
                candidates = [literal(args[-1]) for _, operation, args in calls(expression)
                              if operation == 'FindClass' and literal(args[-1])]
                return candidates[0] if len(candidates) == 1 else None
            candidates = local_bindings.get(function, {}).get(expression, set())
            if not candidates and expression in globals:
                candidates = bindings.get(expression, set())
            if len(candidates) == 1:
                return next(iter(candidates))
            if expression in ('c', 'cls', 'clazz') and function.startswith('Java_'):
                encoded = function[5:].rsplit('_', 1)[0]
                candidates = [name for name in inventory.classes
                              if name.replace('_', '_1').replace('/', '_') == encoded]
                return candidates[0] if len(candidates) == 1 else None
            return None

        for position, operation, args in calls(text):
            context = next((item for item in functions if item[0] <= position <= item[1]), None)
            function = context[2] if context else '<global>'
            conditional = bool(context and re.search(r'\b(?:api|sdk|sdk_int)\s*[<>=!]|SDK_INT|framework_api', context[3], re.I))
            row = dict(file=str(path), line=text.count('\n', 0, position) + 1,
                       function=function, operation=operation, conditional=conditional)
            if operation == 'FindClass':
                name = literal(args[-1])
                if name is None:
                    unresolved.append(dict(row, reason='dynamic-class-name'))
                elif name not in inventory.classes and not name.startswith('['):
                    provider_missing = name.startswith(incomplete_prefixes)
                    target = dict(row, owner=name,
                                  reason='provider-not-supplied' if provider_missing else 'missing-class')
                    (unresolved if conditional or provider_missing else problems).append(target)
                else:
                    checked.append(dict(row, owner=name))
                continue
            if operation == 'RegisterNatives':
                args = args[-3:]
                name = owner(args[0], function)
                table_name = args[1].lstrip('&')
                declarations = [match for match in TABLE.finditer(text)
                                if match.group(1) == table_name and match.start() < position
                                and (context is None or match.start() >= context[0])]
                if name is None or not declarations:
                    unresolved.append(dict(row, reason='dynamic-registration', expression=args[0], table=table_name))
                    continue
                declaration = declarations[-1]
                end = closing(text, declaration.end() - 1, '{', '}')
                entries = ENTRY.findall(text[declaration.end() - 1:end + 1])
                if not entries:
                    unresolved.append(dict(row, owner=name, reason='macro-or-conditional-native-table'))
                for method, descriptor, symbol in entries:
                    target = dict(row, owner=name, name=method, descriptor=descriptor, symbol=symbol)
                    resolved = inventory.resolve('method', name, method, descriptor)
                    if resolved is None or not resolved[1] & 0x100:
                        target['reason'] = 'missing-native-declaration'
                        (unresolved if conditional else problems).append(target)
                    else:
                        checked.append(target)
                continue
            args = args[-3:]
            name = owner(args[0], function)
            method, descriptor = literal(args[1]), literal(args[2])
            if name is None or method is None or descriptor is None:
                unresolved.append(dict(row, reason='dynamic-lookup', expression=args[0]))
                continue
            kind = 'field' if operation.endswith('FieldID') else 'method'
            resolved = inventory.resolve(kind, name, method, descriptor)
            target = dict(row, owner=name, name=method, descriptor=descriptor)
            if resolved is None:
                provider_missing = name not in inventory.classes and name.startswith(incomplete_prefixes)
                target['reason'] = 'provider-not-supplied' if provider_missing else 'missing-member'
                (unresolved if conditional or provider_missing else problems).append(target)
            elif bool(resolved[1] & 8) != ('Static' in operation):
                target['reason'] = 'static-instance-mismatch'
                (unresolved if conditional else problems).append(target)
            else:
                checked.append(target)
    return dict(api=api, checked=checked, unresolved=unresolved, problems=problems,
                scope='Literal JNI declarations and lookups. Dynamic and SDK-conditional sites require runtime execution.')
