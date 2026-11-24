#!/usr/bin/env python3
"""Extract system from a GPT/dynamic-partition emulator image, read-only.

Layout: AOSP system/core/fs_mgr/liblp/include/liblp/metadata_format.h (API 29).
Only linear and zero extents are accepted; no device nodes, mounts or loop devices.
"""
from pathlib import Path
import argparse,struct,hashlib,json,os,subprocess

def unpack(image:Path,out:Path):
 out.mkdir(exist_ok=False,parents=True)
 with image.open('rb')as source:
  def read(at,size):
   assert 0<=at<=image.stat().st_size-size
   source.seek(at);data=source.read(size);assert len(data)==size;return data
  header=read(512,512);assert header[:8]==b'EFI PART'
  lba,count,stride=struct.unpack_from('<QII',header,72);assert count<=1024 and stride>=128
  entries=read(lba*512,count*stride);super_offset=None
  for i in range(count):
   entry=entries[i*stride:(i+1)*stride]
   if not any(entry[:16]):continue
   first,last=struct.unpack_from('<QQ',entry,32);name=entry[56:128].decode('utf-16le').rstrip('\0')
   if name=='super':super_offset=first*512;super_size=(last-first+1)*512
  assert super_offset is not None
  geometry=bytearray(read(super_offset+4096,52));magic,size=struct.unpack_from('<II',geometry);assert magic==0x616c4467 and size==52
  expected=bytes(geometry[8:40]);geometry[8:40]=b'\0'*32;assert hashlib.sha256(geometry).digest()==expected
  maximum,slots,blocksize=struct.unpack_from('<III',geometry,40);assert slots in (1,2,3) and maximum<1024*1024
  metadata_offset=super_offset+12288;head=read(metadata_offset,128);magic,major,minor,length=struct.unpack_from('<IHHI',head);assert magic==0x414c5030 and major==10 and 128<=length<=4096
  head=bytearray(read(metadata_offset,length));expected=bytes(head[12:44]);head[12:44]=b'\0'*32;assert hashlib.sha256(head).digest()==expected
  table_size=struct.unpack_from('<I',head,44)[0];assert table_size<=maximum
  tables=read(metadata_offset+length,table_size);assert hashlib.sha256(tables).digest()==bytes(head[48:80])
  def table(at,min_stride):
   offset,count,stride=struct.unpack_from('<III',head,at);assert stride>=min_stride and offset+count*stride<=len(tables)
   return [tables[offset+i*stride:offset+(i+1)*stride]for i in range(count)]
  partitions=table(80,52);extents=table(92,24);devices=table(116,64);assert len(devices)==1
  record=[]
  for partition in partitions:
   name=partition[:36].split(b'\0')[0].decode();attributes,first,count,group=struct.unpack_from('<IIII',partition,36)
   if name not in ('system','system_a'):continue
   assert first+count<=len(extents)
   target=out/(name+'.img');total=0
   with target.open('xb')as output:
    for extent in extents[first:first+count]:
     sectors,kind,data,device=struct.unpack_from('<QIQI',extent);size=sectors*512;assert device==0 and kind in (0,1)
     if kind==1:output.seek(size,1);total+=size;continue
     assert data*512+size<=super_size;position=super_offset+data*512
     while size:
      n=min(size,1024*1024);block=read(position,n)
      if block==b'\0'*n:output.seek(n,1)
      else:output.write(block)
      position+=n;size-=n;total+=n
    output.truncate(total)
   result=subprocess.run(['debugfs','-R','ls -l /',str(target)],capture_output=True,text=True)
   assert 'Filesystem not open'not in result.stderr and 'Bad magic'not in result.stderr and result.stdout.strip(),result.stderr
   (out/(name+'-root.txt')).write_text(result.stdout+result.stderr)
   record.append(dict(name=name,bytes=total,extents=count,attributes=attributes));print(result.stdout)
  assert len(record)==1
 (out/'partitions.json').write_text(json.dumps(record,indent=2)+'\n');print('API29_SYSTEM=unpacked|'+str(record))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('image',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args();unpack(args.image,args.output)
