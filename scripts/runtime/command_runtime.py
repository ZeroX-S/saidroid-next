"""Validate the genuine, unmodified private Android10 command input."""
from pathlib import Path
import hashlib,json,subprocess
def validate_commands(directory,repo):
 m=json.loads((directory/'manifest.json').read_text())
 assert m['schema']=='saildroid-private-commands-v1' and m['commands']==['touch'] and m['source_changes']==[]
 assert m['upstream']==json.loads((repo/'native/commands/toybox-source.json').read_text())
 assert m['architecture']=='AArch64' and 'AArch64'in subprocess.check_output(['readelf','-h',str(directory/'toybox')],text=True)
 assert hashlib.sha256((directory/'toybox').read_bytes()).hexdigest()==m['binary_sha256']
 assert hashlib.sha256((directory/'NOTICE').read_bytes()).hexdigest()==m['notice_sha256']
 return dict(schema=m['schema'],commands=m['commands'],upstream='android-10.0.0_r16',binary_sha256=m['binary_sha256'],scope='All application processes; private PATH prefix, real user privileges')
