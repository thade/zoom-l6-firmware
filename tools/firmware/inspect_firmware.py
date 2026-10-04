#!/usr/bin/env python3
"""Read-only inspection of the stock L6 image. Does not produce flashable files.
Optional disassembly requires capstone==5.0.9; all outputs go to analysis/.
"""
import collections, hashlib, json, re, struct
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'Reference/L6_v1.10_E/L6.BIN'
OUT = ROOT / 'analysis'
OUT.mkdir(exist_ok=True)
b = SOURCE.read_bytes()
EXPECTED_SHA256 = '64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'
if hashlib.sha256(b).hexdigest() != EXPECTED_SHA256:
 raise SystemExit('This inspection map is specific to the supplied stock L6 v1.10 image.')
BIAS = 0x80000e00
u32 = lambda o: struct.unpack_from('<I', b, o)[0]
strings = [(m.start(), m.group().decode()) for m in re.finditer(rb'[ -~]{5,}', b) if len(set(m.group())) > 4]
wide = [(m.start(), m.group().decode('utf-16le')) for m in re.finditer(rb'(?:[ -~]\x00){5,}', b)]
(OUT/'strings.tsv').write_text('file_offset\truntime_address_main_mapping_only\ttext\n' + '\n'.join(f'{o:#x}\t{o+BIAS:#x}\t{s}' for o,s in strings+wide))
report = {
 'source':str(SOURCE.relative_to(ROOT)), 'size':len(b), 'sha256':hashlib.sha256(b).hexdigest(),
 'main_descriptor':{'offset':u32(0x78),'length':u32(0x7c)},
 'boot_descriptor':{'offset':u32(0x6c),'length':u32(0x70)},
 'payload_checksum':{'stored_big_endian_at_0x1fc':struct.unpack_from('>I',b,0x1fc)[0], 'sum_bytes_0x200_to_eof':sum(b[0x200:])&0xffffffff},
 'main_mapping':{'file_offset':0x200,'runtime_address':0x80001000,'initial_sp':u32(0x200),'reset_vector':u32(0x204)},
 'regions':[{'name':'main_reserved_span','start':0x200,'end_exclusive':0x285200,'length_trailer':u32(0x2851f8),'version_trailer':b[0x2851fc:0x285200].decode()},
 {'name':'panel_candidate','start':0x285200,'end_exclusive':0x295200,'length_trailer':u32(0x2951f8),'version_trailer':b[0x2951fc:0x295200].decode(),'initial_sp':u32(0x285200),'reset_vector':u32(0x285204)},
 {'name':'audio_guide_candidate','start':0x295200,'end_exclusive':0x395200,'language':b[0x295200:0x295203].decode()}],
 'erased_runs':[{'start':m.start(),'end_exclusive':m.end()} for m in re.finditer(rb'\xff{8192,}',b)]
}
assert u32(0x78) + u32(0x7c) == len(b)
assert report['payload_checksum']['stored_big_endian_at_0x1fc'] == report['payload_checksum']['sum_bytes_0x200_to_eof']
assert u32(0x2851f8) + 0x200 == 0xb5ce4
assert u32(0x2951f8) + 0x285200 == 0x288680
report['task_entries'] = []
for name_offset in [0xa0ec8,0xa0ef8,0xa0f10,0xa0f28,0xa0f40,0xa1078,0xa10a8,0xa10c0]:
 name_start=u32(name_offset)-BIAS
 name=b[name_start:b.index(b'\0',name_start)].decode()
 entry=u32(name_offset-4)&~1
 report['task_entries'].append({'name':name,'address':entry,'file_offset':entry-BIAS,'descriptor_name_offset':name_offset})
symbols=[('Reset_Handler',0x80001414),('__RecPlayCtl_PlayStart',0x8004b890),('__RecPlayCtl_PlayStop',0x8004b910),('__RecPlayCtl_RecStart',0x8004b9a0),('__RecPlayCtl_RecStop',0x8004ba40)]
symbols += [(t['name']+'_task',t['address']) for t in report['task_entries']]
(OUT/'symbols.csv').write_text('name,runtime_address,file_offset\n'+'\n'.join(f'{name},{addr:#x},{addr-BIAS:#x}' for name,addr in symbols)+'\n')
try:
 from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
 md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True
 ins=list(md.disasm_lite(b[0x600:0xa0000],0x80001400))
 # Heuristic constant references, not a complete CFG or data-flow analysis.
 refs=[];pending={}
 for addr,size,mn,op in ins:
  if mn=='movw':
   m=re.fullmatch(r'(\w+), #(0x[0-9a-f]+|[0-9]+)',op)
   if m:pending[m[1]]=(addr,int(m[2],0))
  elif mn=='movt':
   m=re.fullmatch(r'(\w+), #(0x[0-9a-f]+|[0-9]+)',op)
   if m and m[1] in pending:
    a,lo=pending[m[1]];value=(int(m[2],0)<<16)|lo
    if addr-a<=24:refs.append((a,addr,value))
  elif mn=='adr':
   m=re.fullmatch(r'(\w+), #(0x[0-9a-f]+|[0-9]+)',op)
   if m:refs.append((addr,addr,((addr+4)&~3)+int(m[2],0)))
 targets=[(o,s) for o,s in strings+wide if re.search(r'(RecPlayCtl|Sampler|StreamUpdate|StreamFile|AFTERSAMPLERREC|Checksum|L6\.BIN|SOUND_PAD|MASTER)',s)]
 hits=[]
 for o,s in targets:
  pointers=[m.start() for m in re.finditer(re.escape(struct.pack('<I',o+BIAS)),b[:0xb5ce4])]
  hit={'file_offset':o,'address':o+BIAS,'label':s,'constant_references':[a for a,end,v in refs if v==o+BIAS],'pointer_offsets':pointers}
  hits.append(hit)
 report['label_references_heuristic']=hits
 # Preserve only bounded, relevant windows; mixed data may decode as instructions.
 ranges=[('reset',0x614,0x69e),('record_play_control',0x4aa90,0x4ad28),('factory_flash_checksum_routine_not_update_validator',0x22cc8,0x22e30),('sampler_assignment_worker',0x35490,0x354b8),('recorder_worker',0x33dc8,0x33e3e),('assignment_completion_event',0x2c968,0x2c980)]
 with (OUT/'disassembly.txt').open('w') as f:
  f.write('Main mapping: runtime = file offset + 0x80000e00. ARM little-endian Thumb.\n')
  for name,start,end in ranges:
   f.write(f'\n{name}: file {start:#x}..{end:#x}\n')
   for a,size,mn,op in md.disasm_lite(b[start:end],start+BIAS):f.write(f'{a:08x}  {mn:12} {op}\n')
 with (OUT/'label_references.txt').open('w') as f:
  for h in hits:f.write(f"{h['label']} at file {h['file_offset']:#x}, runtime {h['address']:#x}; constants {[hex(x) for x in h['constant_references']]}; pointers {[hex(x) for x in h['pointer_offsets']]}\n")
except ImportError:
 report['disassembly_note']='Install capstone==5.0.9 for optional disassembly/reference scanning.'
(OUT/'firmware_inventory.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='label_references_heuristic'},indent=2))
