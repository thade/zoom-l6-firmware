#!/usr/bin/env python3
"""Query a fixed marker executed from consumed DSP startup input."""
FIELDS=('schema','marker','zero_or','ccr','dsp_source','dsp_destination','dsp_bytes','dsp_helper',
        'code_source','code_destination','code_bytes','code_helper','zero_destination','zero_bytes')

def request(token=0):
    if not 0<=token<=127:raise ValueError('token must be 7-bit')
    return bytes((0xf0,0x52,0,0,0x6f,4,token,0xf7))

def decode(packet):
    if len(packet)<6 or packet[:6]!=bytes((0xf0,0x52,0,0,0x6e,4)):return None
    if len(packet)!=78 or packet[-1]!=0xf7 or any(x>127 for x in packet[6:-1]):
        raise ValueError('invalid source-reuse reply length or encoding')
    values=[]
    for at in range(7,77,5):
        part=packet[at:at+5]
        if part[4]>15:raise ValueError('source-reuse word exceeds 32 bits')
        values.append(sum(v<<(7*i) for i,v in enumerate(part)))
    if values[0]!=1:raise ValueError('unsupported source-reuse schema')
    return dict(zip(FIELDS,values),token=packet[6],installed_flash_readback=False,
        capture_enabled=False,observation='executed fixed marker and read fixed application-RAM records')

def main():
    import argparse,json
    from pathlib import Path
    from l6_health_probe import sample
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output,query_builder=lambda kind,token:request(token),
        reply_decoder=decode,kinds=(4,),reply_matcher=lambda d,k,t:d['token']==t)
    print(json.dumps(rows[0]))
if __name__=='__main__':main()
