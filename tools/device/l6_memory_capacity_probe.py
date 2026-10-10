#!/usr/bin/env python3
"""Read one fixed controller/core page; never accept a host-selected address."""
import argparse,json
from pathlib import Path
from l6_health_probe import sample

FIELDS=('schema','snapshot_agrees','mcr','iocr','br0','br1','br2','br3',
        'sdramcr0','sdramcr1','sdramcr2','sdramcr3','gpr16','gpr17',
        'dtcmcr','itcmcr','cpuid','digprog')

def request(kind,token):
    if kind!=1 or not 0<=token<128:raise ValueError('Invalid fixed RAM query')
    return bytes((0xf0,0x52,0,0,0x6f,1,token,0xf7))

def decode(packet):
    if len(packet)<8 or packet[:5]!=bytes((0xf0,0x52,0,0,0x6e)):return None
    if (len(packet)!=98 or packet[5]!=1 or packet[-1]!=0xf7 or
        any(b>127 for b in packet[1:-1])):raise ValueError('Invalid RAM reply')
    values=[]
    for i in range(7,97,5):
        if packet[i+4]>15:raise ValueError('RAM word exceeds uint32')
        values.append(sum(packet[i+k]<<(7*k) for k in range(5)))
    r=dict(kind=1,token=packet[6],**dict(zip(FIELDS,values)))
    if r['schema']!=1 or r['snapshot_agrees'] not in (0,1):raise ValueError('Unsupported RAM reply schema')
    r['observer_consistent']=bool(r['snapshot_agrees'])
    r['semc_enabled']=not bool(r['mcr']&3)
    r['sdram_refresh_enabled']=bool(r['sdramcr3']&1)
    r['sdram_windows']=[]
    for cs in range(4):
        br=r[f'br{cs}'];exponent=(br>>1)&31
        size=4096<<min(exponent,20);base=br&0xfffff000
        valid=bool(br&1)
        r['sdram_windows'].append(dict(chip_select=cs,enabled=valid,base=base,
          configured_bytes=size if valid else 0,size_code=exponent,
          fits_32bit_address_space=base+size<=1<<32 if valid else None))
    ps=r['sdramcr0']&1
    r['bus_width_bits']=8 if ps==0 else 16
    r['bus_width_note']='Bit 0 selects 8/16 bits in the compared RT1041/RT1042/RT1062 headers'
    r['column_bits']=8 if r['sdramcr0']&128 else (12,11,10,9)[(r['sdramcr0']>>8)&3]
    r['bank_count']=2 if r['sdramcr0']&0x4000 else 4
    r['gpr17_selected']=bool(r['gpr16']&4)
    for name in ('dtcmcr','itcmcr'):
        value=r[name];code=(value>>3)&15
        r[name+'_enabled']=bool(value&1)
        r[name+'_configured_bytes']=0 if code==0 else 1<<(code+9)
    r['exact_processor_identified']=False
    r['physical_capacity_confirmed']=False
    r['unused_memory_proven']=False
    return r

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output,query_builder=request,reply_decoder=decode,kinds=(1,1,1))
    print(json.dumps(dict(samples=rows,limitation='Controller geometry is evidence of configuration, not a physical density or free-space test.')))
if __name__=='__main__':main()
