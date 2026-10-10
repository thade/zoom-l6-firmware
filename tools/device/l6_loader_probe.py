#!/usr/bin/env python3
"""Read-only identity of the isolated application startup-loader trial."""
FIELDS=('schema','source','destination','bytes','helper')

def request(token=0):
    if not 0<=token<=127:raise ValueError('token must be 7-bit')
    return bytes((0xf0,0x52,0,0,0x6f,3,token,0xf7))

def decode(packet):
    if len(packet)<6 or packet[:6]!=bytes((0xf0,0x52,0,0,0x6e,3)):return None
    if len(packet)!=33 or packet[-1]!=0xf7 or any(x>127 for x in packet[6:-1]):
        raise ValueError('invalid loader reply length or encoding')
    values=[]
    for at in range(7,32,5):
        part=packet[at:at+5]
        if part[4]>15:raise ValueError('loader word exceeds 32 bits')
        values.append(sum(v<<(7*i) for i,v in enumerate(part)))
    if values[0]!=1:raise ValueError('unsupported loader schema')
    return dict(zip(FIELDS,values),token=packet[6],installed_flash_readback=False,
        capture_enabled=False,observation='fixed application-RAM scatter record')

def main():
    import argparse,json
    from pathlib import Path
    from l6_health_probe import sample
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output,query_builder=lambda kind,token:request(token),
        reply_decoder=decode,kinds=(3,),reply_matcher=lambda d,k,t:d['token']==t)
    print(json.dumps(rows[0]))

if __name__=='__main__':main()
