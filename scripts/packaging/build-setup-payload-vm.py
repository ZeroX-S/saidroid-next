#!/usr/bin/env python3
"""Build setup helper/registry payload only. Never install or access a phone."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,platform,shutil,subprocess,zipfile
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--bootstrap-jar',type=Path,required=True);p.add_argument('--api',type=int,choices=(28,29),default=29);p.add_argument('--r8',type=Path);p.add_argument('--jdk',type=Path,default=Path('/tmp/jdkfull/jdk-21.0.13+9'));a=p.parse_args()
assert platform.system()=='Linux' and 'sailfishos' not in Path('/etc/os-release').read_text().lower()
assert not a.output.exists();a.output.mkdir(parents=True);repo=Path(__file__).resolve().parents[2];source_dir=Path(__file__).parent/'java/org/saildroid/setup';sources=[source_dir/n for n in ['RefreshLaunchers.java','RegistryBridge.java']];classes=a.output/'classes';classes.mkdir();r8=a.r8 or repo/'build/codex-api29/inputs/r8-8.3.37.jar';commands=[]
def run(command):
 commands.append(command)
 with(a.output/('build-'+str(len(commands))+'.log')).open('ab')as f:subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=60)
run([str(a.jdk/'bin/javac'),'--release','8','-d',str(classes),*map(str,sources)])
for name in ['RefreshLaunchers','RegistryBridge']:
 out=a.output/name;out.mkdir();run([str(a.jdk/'bin/java'),'-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api',str(a.api),'--output',str(out),str(classes/('org/saildroid/setup/'+name+'.class'))])
# Only the narrow newly introduced bridge entry is public. Existing CLI and
# framework hidden-API flags are neither changed nor exempted.
spec=importlib.util.spec_from_file_location('hiddenapi',repo/'scripts/api29/encode-hiddenapi-vm.py');encoder=importlib.util.module_from_spec(spec);spec.loader.exec_module(encoder)
raw=a.output/'RegistryBridge/classes.dex';members,code=encoder.dex_members(raw.read_bytes());public='Lorg/saildroid/setup/RegistryBridge;->refresh(Ljava/lang/String;)V';assert public in members
flags=a.output/'registry-bridge-flags.csv';flags.write_text(''.join(n+(','+'whitelist'if n==public else',blacklist')+'\n'for n in sorted(members)))
encoded=a.output/'registry-bridge-encoded.dex';tool=Path('/var/tmp/saidroid-hiddenapi-tool-20261031/hiddenapi');run([str(tool),'encode','--input-dex='+str(raw),'--output-dex='+str(encoded),'--api-flags='+str(flags)])
em,ec=encoder.dex_members(encoded.read_bytes());assert em==members and ec==code
root=a.output/'root';helper=root/'bin/saildroid-setup';helper.parent.mkdir(parents=True);shutil.copyfile(Path(__file__).with_name('saildroid-setup.py'),helper);helper.chmod(0o755)
binder_helper=root/'bin/saildroid-binder-setup.py';shutil.copyfile(Path(__file__).with_name('saildroid-binder-setup.py'),binder_helper);binder_helper.chmod(0o755)
jar=root/'share/packaging/setup-registry.jar';jar.parent.mkdir(parents=True)
def dex_info(name):
 info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16;return info
with zipfile.ZipFile(jar,'w')as z:z.writestr(dex_info('classes.dex'),(a.output/'RefreshLaunchers/classes.dex').read_bytes())
jar.chmod(0o644)
bootstrap=root/'lib/java-cli-bootstrap.jar';bootstrap.parent.mkdir()
with zipfile.ZipFile(a.bootstrap_jar)as original,zipfile.ZipFile(bootstrap,'w')as merged:
 names=original.namelist();assert 'classes.dex'in names and 'classes2.dex'not in names
 for info in original.infolist():merged.writestr(info,original.read(info.filename))
 merged.writestr(dex_info('classes2.dex'),encoded.read_bytes())
with zipfile.ZipFile(a.bootstrap_jar)as original,zipfile.ZipFile(bootstrap)as merged:assert all(original.read(n)==merged.read(n)for n in original.namelist())
bootstrap.chmod(0o644)
for source in sources:shutil.copyfile(source,jar.parent/source.name);(jar.parent/source.name).chmod(0o644)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();result=dict(passed=True,api=a.api,commands=commands,r8_sha256=sha(r8),source_sha256={s.name:sha(s)for s in sources},original_bootstrap_sha256=sha(a.bootstrap_jar),original_bootstrap_entries_byte_identical=True,new_public_bridge_members=[public],bridge_code_unchanged_by_encoding=True,hiddenapi_tool_sha256=sha(tool),files={str(p.relative_to(root)):dict(sha256=sha(p),bytes=p.stat().st_size)for p in root.rglob('*')if p.is_file()},scope='manual setup payload only; no RPM built or device accessed; host AOT bootclasspath unchanged')
(a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
