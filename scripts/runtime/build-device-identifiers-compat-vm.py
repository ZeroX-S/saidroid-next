#!/usr/bin/env python3
"""Opt-in ordinary-app identifier boundary over an exact compiled product.

Compiles only the new service plus one service-table registration, retaining all
other original class bytes/native members. Does not edit frozen product sources.
Encode runtime.jar with canonical hidden API metadata before packaging it.
"""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,zipfile,importlib.util
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','product','output']:p.add_argument(n,type=Path)
a=p.parse_args();repo=Path(__file__).resolve().parents[2];os.umask(0o022);assert not a.output.exists();a.output.mkdir(parents=True);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();product=json.loads((a.product/'manifest.json').read_text());assert sha(a.product/'runtime.jar')==product['files']['runtime.jar']
source=repo/'scripts/device/SdServices.java';assert sha(source)==product['sources']['scripts/device/SdServices.java'];text=source.read_text();needle='        register("trust", SdKeyguard.binder());';assert text.count(needle)==1
prepared=a.output/'source';prepared.mkdir();services=prepared/'SdServices.java';services.write_text(text.replace(needle,needle+'\n        register("device_identifiers", SdDeviceIdentifiers.binder());'));identifiers=repo/'scripts/runtime/device-identifiers-compat/SdDeviceIdentifiers.java';classes=a.output/'overlay-classes';classes.mkdir();java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar';commands=[]
def run(command,log):
 commands.append(command)
 with(a.output/log).open('x')as f:subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,check=True)
def dex(folder,target,log):run([str(java/'java'),'-Xmx2g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),*map(str,sorted(folder.rglob('*.class')))],log)
def entries(jar):
 with zipfile.ZipFile(jar)as z:assert len(z.namelist())==len(set(z.namelist()));return {n:z.read(n)for n in z.namelist()}
# Prove the saved baseline class tree actually reconstructs the accepted DEX.
dex(a.product/'classes',a.output/'baseline-runtime.jar','baseline-d8.log');assert entries(a.output/'baseline-runtime.jar')==entries(a.product/'runtime.jar')
run([str(java/'javac'),'--release','8','-nowarn','-cp',str(framework)+':'+str(a.product/'classes'),'-d',str(classes),str(services),str(identifiers)],'javac.log');assert {str(f.relative_to(classes))for f in classes.rglob('*.class')}=={'SdServices.class','SdDeviceIdentifiers.class'}
merged=a.output/'classes';shutil.copytree(a.product/'classes',merged);before={str(f.relative_to(merged)):sha(f)for f in merged.rglob('*.class')}
for f in classes.rglob('*.class'):shutil.copyfile(f,merged/f.relative_to(classes))
after={str(f.relative_to(merged)):sha(f)for f in merged.rglob('*.class')};assert set(after)-set(before)=={'SdDeviceIdentifiers.class'}and all(after[n]==h for n,h in before.items()if n!='SdServices.class')and before['SdServices.class']!=after['SdServices.class'];dex(merged,a.output/'runtime.jar','d8.log')
spec=importlib.util.spec_from_file_location('identifier_core_boundary',repo/'scripts/runtime/encode-hiddenapi-vm.py');encoder=importlib.util.module_from_spec(spec);spec.loader.exec_module(encoder);old,_=encoder.dex_members(entries(a.product/'runtime.jar')['classes.dex']);new,_=encoder.dex_members(entries(a.output/'runtime.jar')['classes.dex']);assert set(old)<=set(new)and all(old[n][0]==new[n][0]for n in old);added=set(new)-set(old);assert added and all(n.startswith('LSdDeviceIdentifiers;->')for n in added)
record=dict(schema='saildroid-device-identifiers-compat-v1',scope='All hosted ordinary apps; explicit original API29 identifier-access denial with no privileged/carrier/owner/AppOp/dangerous permission grant backend. No host serial/IMEI/MEID reads or Android system identity inferred from Sailfish UID.',passed=True,builder_sha256=sha(Path(__file__)),product_manifest_sha256=sha(a.product/'manifest.json'),baseline_runtime_sha256=sha(a.product/'runtime.jar'),source_manifest={'baseline_services':sha(source),'prepared_services':sha(services),'identifiers':sha(identifiers)},classfiles_before=before,classfiles_after=after,new_members=sorted(added),existing_access_and_native_declarations_preserved=True,runtime_sha256=sha(a.output/'runtime.jar'),commands=commands,phone_staged=False)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('DEVICE_IDENTIFIER_RUNTIME=compiled|only_service_table_and_one_new_class=true|existing_members_retained=true|phone_staged=false')
