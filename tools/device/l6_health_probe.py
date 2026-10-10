#!/usr/bin/env python3
"""Fixed read-only queries for experiment 04, requiring connected L6 Editor.

No assignments, playback/record commands, memory addresses, arbitrary packets,
card operations or firmware writes. Works only with the diagnostic trial.
"""
import argparse,json,queue,time
from pathlib import Path

HEAP_FIELDS=('heap_sentinel','free_bytes','minimum_free_bytes','allocations','frees',
    'ticks','volume_flags','host0_event','host1_event','card0_flags','card1_flags',
    'card0_capacity_sectors','card1_capacity_sectors')
SD_FIELDS=('epoch_before','reads','writes','skipped','last_result','last_ticks',
    'maximum_ticks','epoch_after','ticks')

def request(kind,token):
    if kind not in (1,2,3) or not 0<=token<128:raise ValueError('Invalid fixed diagnostic query')
    return bytes((0xf0,0x52,0,0,0x7d,kind,token,0xf7))

def decode(packet):
    if len(packet)<8 or packet[:5]!=bytes((0xf0,0x52,0,0,0x7c)):return None
    kind,token=packet[5:7]
    if kind not in (1,2,3) or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):raise ValueError('Invalid diagnostic reply')
    names=HEAP_FIELDS if kind==1 else SD_FIELDS
    if len(packet)!=8+5*len(names):raise ValueError('Diagnostic reply length does not match schema 1')
    values=[]
    for p in range(7,len(packet)-1,5):
        if packet[p+4]>15:raise ValueError('Diagnostic word exceeds uint32')
        values.append(sum(packet[p+i]<<(7*i) for i in range(5)))
    result=dict(kind=kind,token=token,**dict(zip(names,values)))
    if kind==1:result['heap_initialized']=result['heap_sentinel']==0x8095ffd0
    else:
        result['packet_unit']=kind-1
        result['observer_consistent']=result['epoch_before']==result['epoch_after'] and not result['epoch_before']&1
        result['physical_completion_proven']=False
    return result

def sample(log,*,query_builder=request,reply_decoder=decode,kinds=(1,2,3),
           reply_matcher=None,token_builder=None,interval_s=0):
    if not 0<=interval_s<=1:raise ValueError('Diagnostic interval must be between zero and one second')
    # Use the existing bounded CoreMIDI receive/client plumbing; replace its
    # mutation-capable send/query interface with only the three fixed queries.
    import ctypes as C
    import l6_midi_probe as midi
    from l6_pad_fixture_test import Session
    class HealthSession(Session):
        def send_query(self,kind,token):
            data=query_builder(kind,token);storage=C.create_string_buffer(1024);raw=C.create_string_buffer(data)
            first=midi.packet_init(storage)
            if not midi.packet_add(storage,len(storage),first,0,len(data),raw):raise RuntimeError('Cannot build MIDI packet')
            sent=time.time();midi.check(midi.send(self.output,self.destination,storage))
            self.write(dict(direction='probe_to_device',timestamp=sent,hex=data.hex(' ')))
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                try:stamp,chunk=self.events.get(timeout=0.05)
                except queue.Empty:continue
                if isinstance(chunk,Exception):raise chunk
                for b in chunk:
                    if b>=0xf8:continue
                    if b==0xf0:self.pending.clear();self.pending.append(b)
                    elif self.pending:
                        self.pending.append(b)
                        if b==0xf7:
                            packet=bytes(self.pending);self.pending.clear();d=reply_decoder(packet)
                            matches=(reply_matcher(d,kind,token) if d and reply_matcher else
                                     d and d['kind']==kind and d['token']==token)
                            if d and stamp>=sent and matches:
                                self.write(dict(direction='device_to_probe',timestamp=stamp,hex=packet.hex(' '),decoded=d));return d
                        elif len(self.pending)>8192:raise RuntimeError('Unexpected oversized reply')
            raise TimeoutError('No diagnostic reply: verify trial firmware and connected official L6 Editor')
        # Do not expose the inherited general send, selection or assignment API.
        def send(self,*args):raise RuntimeError('Health probe sends fixed diagnostic queries only')
        query=assign=send
    # Keep cleanup active even if endpoint/port setup fails partway through
    # the existing transport constructor.
    s=HealthSession.__new__(HealthSession)
    try:
        HealthSession.__init__(s,log)
        rows=[]
        for i,kind in enumerate(kinds):
            if i and interval_s:time.sleep(interval_s)
            rows.append(s.send_query(kind,token_builder(kind) if token_builder else kind))
        return rows
    finally:
        if getattr(s,'client',None) and s.client.value:midi.client_free(s.client)
        if getattr(s,'log',None):s.log.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New local JSONL log; existing files are never overwritten')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output)
    print(json.dumps(dict(samples=rows,limitation='SD durations include native waiting and scheduling; observations do not establish physical completion.')))
if __name__=='__main__':main()
