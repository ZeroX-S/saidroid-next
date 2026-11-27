from pathlib import Path
import subprocess,os,json,hashlib,base64,ast
repo=Path('/media/psf/Home/WorkSpace/saidroid-next');b=repo/'build/evidence/qq-service-lifecycle305-20261103-v1';old=b;env=dict(os.environ,SSHPASS=os.environ['SSHPASS']);lock=repo/'scripts/devlock.sh';ssh=['sshpass','-e','ssh','-o','ConnectTimeout=6','root@bonito'];held=False;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();fixtures=json.loads((old/'fixtures-v2.json').read_text());results=[]
assert json.loads((b/'package.json').read_text())['passed']
def quiesce(label):
 with(b/('quiesce-'+label+'.log')).open('ab',buffering=0)as stream:q=subprocess.run(['python3',str(repo/'scripts/perf/close-owned-vm.py')],env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
 assert q.returncode==0,'Owned quiesce failed'
try:
 q=subprocess.run(['bash',str(lock),'acquire','0','lifecycle305-fixture'],env=env,text=True,capture_output=True,timeout=20);print(q.stdout,q.stderr,flush=True);assert q.returncode==0;held=True
 for root,sdk,service,expected in [('r304',29,True,'negative-control'),('r305',29,True,'pass'),('r305',34,True,'pass')]:
  quiesce('before-'+root+'-sdk'+str(sdk));fixture=next(v for v in fixtures['apks']if v['target_sdk']==sdk);apk=Path(fixture['path']);assert sha(apk)==fixture['sha256'];label='lifecycle305-v2-'+root+'-sdk'+str(sdk)+('-service'if service else'-activity');cfg=dict(prior_fixture_sha='79f0faf01afc8824ae903f771d025c76970855a49ab1560edb58f0fa95156653',service=service,root='/home/art/releases/api29-'+root+'-native-candidate',target_sdk=sdk,label=label,expected=expected,sha256=fixture['sha256'],apk=base64.b64encode(apk.read_bytes()).decode())
  body='CFG='+repr(cfg)+'\n'+(repo/'scripts/cts/display_cleanup.py').read_text()+'\n'+(b/'probe-fixture-phone.py').read_text();ast.parse(body)
  q=subprocess.run(ssh+['python3','-'],input=body,env=env,text=True,capture_output=True,timeout=120);(b/(label+'.stdout')).write_text(q.stdout);(b/(label+'.stderr')).write_text(q.stderr);print(label,q.stdout,q.stderr,flush=True)
  c=subprocess.run(['sshpass','-e','scp','-O','-r','root@bonito:/home/art/test/'+label,str(b/label)],env=env,capture_output=True,text=True,timeout=20);assert c.returncode==0,c.stderr;assert q.returncode==0,q.stderr;d=json.loads((b/label/'result.json').read_text());assert d['passed']and d['cleanup_safe'];results.append(d)
 (b/'lifecycle-fixture-v2-results.json').write_text(json.dumps(dict(passed=True,results=results),indent=2)+'\n')
finally:
 if held:
  try:quiesce('after-sdk-fixtures')
  finally:
   q=subprocess.run(['bash',str(lock),'release','lifecycle305-fixture'],env=env,text=True,capture_output=True,timeout=20);(b/'camera-fixture-release.json').write_text(json.dumps(dict(code=q.returncode,stdout=q.stdout,stderr=q.stderr),indent=2)+'\n');print(q.stdout,q.stderr,flush=True)
