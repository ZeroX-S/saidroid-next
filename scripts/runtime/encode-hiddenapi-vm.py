#!/usr/bin/env python3
"""Encode canonical Android 10 flags in platform DEX without changing executable code.

Platform additions absent from Android's list are implementation-private.
The version-pinned legacy JUnit/Hamcrest boot libraries retain their ordinary
public/protected Java APIs; those are external library APIs, not Android
non-SDK internals. This tool never reads or modifies an application/test APK.
"""
from pathlib import Path
import argparse,gzip,hashlib,json,struct,subprocess,zipfile

PUBLIC_LIBRARY_INPUTS={
 'java/dex/art/core-junit-hostdex.jar':'668cc8634a093aab11495c2ad21dbec579f8efe5782bc7cbdb0b4a4b15a00488',
 'java/dex/art/hamcrest-hostdex.jar':'bf81a60dac04d058dc48cfb9e64146ec1fe2873b72476adaf423515675155474',
 'java/dex/art/junit-runner-hostdex.jar':'fe4d6e8da0ce272c89eafc5c3c560ab5daee97d13115a04720d6803ff6676bb3',
}

def public_library_members(data,members):
 def u(o):return struct.unpack_from('<I',data,o)[0]
 def string(index):
  at=u(u(60)+4*index)
  while data[at]&128:at+=1
  at+=1;return data[at:data.index(0,at)].decode('utf-8')
 public_classes={string(u(u(68)+4*u(at)))for at in range(u(100),u(100)+32*u(96),32)if u(at+4)&1}
 assert all(c.startswith(('Ljunit/','Lorg/hamcrest/'))for c in public_classes)
 return {s for s,(access,_)in members.items()if access&5 and s.split('->')[0]in public_classes}

def dex_members(data):
 def u(o):return struct.unpack_from('<I',data,o)[0]
 def h(o):return struct.unpack_from('<H',data,o)[0]
 def leb(o):
  value=0;shift=0
  while True:
   b=data[o];o+=1;value|=(b&127)<<shift
   if not b&128:return value,o
   shift+=7
   if shift>35:raise ValueError('Malformed ULEB128')
 def string(index):
  o=u(u(60)+4*index);_,o=leb(o);return data[o:data.index(0,o)].decode('utf-8',errors='surrogateescape')
 def typ(index):return string(u(u(68)+4*index))
 def proto(index):
  o=u(76)+index*12;ret=typ(u(o+4));args=u(o+8)
  return '('+(''.join(typ(h(args+4+2*i))for i in range(u(args)))if args else '')+')'+ret
 members={};code={}
 for c in range(u(96)):
  off=u(u(100)+32*c+24)
  if not off:continue
  counts=[]
  for _ in range(4):n,off=leb(off);counts.append(n)
  for group,count in enumerate(counts):
   index=0
   for _ in range(count):
    delta,off=leb(off);index+=delta;access,off=leb(off)
    if group<2:
     item=u(84)+index*8;signature=typ(h(item))+'->'+string(u(item+4))+':'+typ(h(item+2));codeoff=0
    else:
     codeoff,off=leb(off);item=u(92)+index*8;signature=typ(h(item))+'->'+string(u(item+4))+proto(h(item+2))
    assert signature not in members
    members[signature]=(access,codeoff)
    if codeoff:
     length=16+u(codeoff+12)*2
     code[signature]=hashlib.sha256(data[codeoff:codeoff+length]).hexdigest()
 return members,code

def run():
 p=argparse.ArgumentParser();p.add_argument('component',type=Path);p.add_argument('runtime_jar',type=Path);p.add_argument('flags_gzip',type=Path);p.add_argument('tool',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
 a.output.mkdir(exist_ok=False);original_flags=gzip.decompress(a.flags_gzip.read_bytes())
 assert hashlib.sha256(original_flags).hexdigest()=='f22a59c215e752777a114bd9b07b0b6b4aedfc8e49e6efca0f99681771c5bfeb','Canonical Android 10 flag snapshot differs'
 flags={}
 for line in original_flags.decode().splitlines():
  name,values=line.split(',',1);assert name not in flags;flags[name]=values
 runtime=json.loads((a.component/'runtime.json').read_text());files={n:a.component/n for n in runtime['boot_jars']};files['lib/runtime.jar']=a.runtime_jar
 sources={};all_members={};library_apis={}
 for name,source in files.items():
  with zipfile.ZipFile(source)as z:
   dexes=[n for n in z.namelist()if n.endswith('.dex')];assert dexes==['classes.dex'],(name,dexes);data=z.read('classes.dex')
  members,code=dex_members(data);sources[name]=(source,data,members,code)
  public=set()
  if name in PUBLIC_LIBRARY_INPUTS:
   assert hashlib.sha256(source.read_bytes()).hexdigest()==PUBLIC_LIBRARY_INPUTS[name], 'Unknown public library bytecode: '+name
   public=public_library_members(data,members);assert public
   library_apis[name]=dict(source_sha256=PUBLIC_LIBRARY_INPUTS[name],members=sorted(public),policy='Declared public/protected API of public classes; canonical Android flags take precedence')
  for signature in members:all_members[signature]=flags.get(signature,'whitelist'if signature in public else'blacklist')
 combined=a.output/'effective-api-flags.csv';combined.write_text(''.join(k+','+v+'\n'for k,v in sorted(all_members.items())))
 records={}
 for index,(name,(source,data,members,code))in enumerate(sources.items()):
  raw=a.output/('input-'+str(index)+'.dex');encoded=a.output/('encoded-'+str(index)+'.dex');raw.write_bytes(data)
  command=[str(a.tool),'encode','--input-dex='+str(raw),'--output-dex='+str(encoded),'--api-flags='+str(combined)]
  with(a.output/('encode-'+str(index)+'.log')).open('w')as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
  encoded_data=encoded.read_bytes();after_members,after_code=dex_members(encoded_data)
  assert members==after_members and code==after_code,'Encoding changed declarations or executable code'
  target=a.output/name;target.parent.mkdir(parents=True,exist_ok=True)
  with zipfile.ZipFile(source)as before,zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED)as after:
   for item in before.infolist():after.writestr(item,encoded_data if item.filename=='classes.dex'else before.read(item.filename))
  records[name]=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),members=len(members),canonical_members=sum(s in flags for s in members),implementation_private_members=sum(s not in flags for s in members),executable_code_unchanged=True)
  raw.unlink();encoded.unlink()
 record=dict(schema='saildroid-hiddenapi-v1',canonical_flags_sha256=hashlib.sha256(original_flags).hexdigest(),effective_flags_sha256=hashlib.sha256(combined.read_bytes()).hexdigest(),tool_sha256=hashlib.sha256(a.tool.read_bytes()).hexdigest(),unknown_policy='implementation-private-blacklist',public_library_apis=library_apis,files=records)
 (a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('HIDDENAPI=ENCODED|jars='+str(len(records))+'|members='+str(len(all_members))+'|executable_code=unchanged')
if __name__=='__main__':run()
