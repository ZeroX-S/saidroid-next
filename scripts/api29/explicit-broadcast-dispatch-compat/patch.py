from pathlib import Path
import re
import sys


SIGNATURE = '.method private blacklist broadcastIntent([Ljava/lang/Object;)I'
DISPATCH = 'LSdManifestReceivers;->send(Landroid/content/Intent;ILjava/lang/String;Landroid/os/Bundle;[Ljava/lang/String;I)V'
ANCHOR = '''    check-cast v6, Landroid/os/Bundle;

    const/4 v9, 0x0
'''
BRANCH = '''    invoke-virtual {v0}, Landroid/content/Intent;->getComponent()Landroid/content/ComponentName;

    move-result-object v1

    if-eqz v1, :registered_receiver_broadcast

    move-object v1, v0

    move v2, v4

    move-object v3, v5

    move-object v4, v6

    move-object v5, v10

    move v6, v11

    invoke-static/range {v1 .. v6}, ''' + DISPATCH + '''

    const/4 v0, 0x0

    return v0

    :registered_receiver_broadcast
'''


def patch_broadcast_intent(text):
    matches = list(re.finditer(re.escape(SIGNATURE) + r'\n.*?^\.end method$', text,
                              flags=re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise ValueError('Exactly one broadcastIntent method is required')
    selected = matches[0]
    method = selected.group()
    if BRANCH in method:
        return text
    if DISPATCH in method:
        raise ValueError('Unknown existing explicit-broadcast dispatch')
    required = ['.registers 18', 'check-cast v10, [Ljava/lang/String;',
                'move-result v11', 'Ordered/sticky/app-op/options broadcasts unavailable',
                'invoke-virtual/range {v1 .. v9}, LSdActivityManagerService;->deliverBroadcast(',
                'invoke-static/range {v1 .. v7}, LSdRemoteServices;->broadcast(']
    if any(value not in method for value in required) or method.count(ANCHOR) != 1:
        raise ValueError('Unsupported broadcastIntent register or dispatch layout')
    method = method.replace(ANCHOR, ANCHOR.replace('    const/4 v9, 0x0',
                                                BRANCH + '\n    const/4 v9, 0x0'))
    return text[:selected.start()] + method + text[selected.end():]


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: patch.py SdActivityManagerService.smali')
    path = Path(sys.argv[1])
    path.write_text(patch_broadcast_intent(path.read_text()))


if __name__ == '__main__':
    main()
