#!/usr/bin/env python3
"""Rasterize the component's simple SVG mark deterministically for native GL.
The geometry and colours match package-component.py's SailDroid SVG.
"""
import struct,zlib,sys
from pathlib import Path
size=128;samples=4;rows=[]
for y in range(size):
 row=bytearray()
 for x in range(size):
  values=[0,0,0,0]
  for sy in range(samples):
   for sx in range(samples):
    px=x+(sx+.5)/samples;py=y+(sy+.5)/samples
    dx=max(28-px,px-100,0);dy=max(28-py,py-100,0)
    colour=(23,63,88,255) if dx*dx+dy*dy<=28*28 else (0,0,0,0)
    if 26<=py<=83 and 57-(py-26)*28/57<=px<=57+(py-26)*39/57:colour=(220,234,240,255)
    if 29<=px<=96 and 87<=py<=95:colour=(88,197,215,255)
    for i,v in enumerate(colour):values[i]+=v
  row.extend(round(v/(samples*samples)) for v in values)
 rows.append(b'\0'+row)
def chunk(name,data):return struct.pack('!I',len(data))+name+data+struct.pack('!I',zlib.crc32(name+data)&0xffffffff)
Path(sys.argv[1]).write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows),9))+chunk(b'IEND',b''))
