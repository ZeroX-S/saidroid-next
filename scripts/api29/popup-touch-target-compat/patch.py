from pathlib import Path
import re


SIGNATURE = '.method private blacklist deliver(IIFFJ)V'
OLD = '    invoke-direct/range {p0 .. p0}, LSdWindowSession;->top()LSdWindowSession$Window;'
NEW = '    invoke-direct {v1, v3, v4}, LSdWindowSession;->touchTarget(FF)LSdWindowSession$Window;'
TARGET_SIGNATURE = '.method private blacklist touchTarget(FF)LSdWindowSession$Window;'


def patch(text):
    matches = list(re.finditer(re.escape(SIGNATURE) + r'\n.*?^\.end method$', text,
                              re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise ValueError('Exactly one touch delivery method is required')
    selected = matches[0]
    method = selected.group()
    helper = Path(__file__).with_name('touchTarget.smali').read_text().rstrip()
    if method.count(NEW) == 2 and helper in text and OLD not in method and text.count(TARGET_SIGNATURE) == 1:
        return text
    required = ['.registers 30', 'move-object/from16 v1, p0', 'move/from16 v3, p3',
                'move/from16 v4, p4']
    if method.count(OLD) != 2 or TARGET_SIGNATURE in text or any(value not in method for value in required):
        raise ValueError('Unsupported window touch delivery layout')
    method = method.replace(OLD, NEW)
    return text[:selected.start()] + method + text[selected.end():] + '\n' + helper + '\n'
