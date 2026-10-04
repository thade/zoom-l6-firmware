#!/usr/bin/env python3
"""macOS L6 endpoint inventory, passive reply capture, and fixed read-only queries.

Does not send arbitrary bytes, assignments, playback/record commands, handshakes,
or firmware operations. Queries require an already connected official editor.
Captures device output only; cannot spy on another app's outgoing MIDI messages.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import queue
import struct
import time
from decode_l6_sysex import decode

M = C.CDLL('/System/Library/Frameworks/CoreMIDI.framework/CoreMIDI')
F = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
PTR=C.c_void_p; REF=C.c_uint32; STATUS=C.c_int32
READ=C.CFUNCTYPE(None,PTR,PTR,PTR)

def api(lib,name,args,result=STATUS):
    fn=getattr(lib,name);fn.argtypes=args;fn.restype=result;return fn

cfstr=api(F,'CFStringCreateWithCString',[PTR,C.c_char_p,C.c_uint32],PTR)
cftext=api(F,'CFStringGetCString',[PTR,C.c_char_p,C.c_long,C.c_uint32],C.c_bool)
release=api(F,'CFRelease',[PTR],None)
client_new=api(M,'MIDIClientCreate',[PTR,PTR,PTR,C.POINTER(REF)])
client_free=api(M,'MIDIClientDispose',[REF])
getstr=api(M,'MIDIObjectGetStringProperty',[REF,PTR,C.POINTER(PTR)])
port_new=api(M,'MIDIInputPortCreate',[REF,PTR,READ,PTR,C.POINTER(REF)])
connect=api(M,'MIDIPortConnectSource',[REF,REF,PTR])
out_new=api(M,'MIDIOutputPortCreate',[REF,PTR,C.POINTER(REF)])
send=api(M,'MIDISend',[REF,REF,PTR])
packet_init=api(M,'MIDIPacketListInit',[PTR],PTR)
packet_add=api(M,'MIDIPacketListAdd',[PTR,C.c_size_t,PTR,C.c_uint64,C.c_size_t,PTR],PTR)

def check(code):
    if code: raise RuntimeError(f'CoreMIDI returned {code}; no device operation can be assumed successful')

def name(ref,prop):
    out=PTR()
    check(getstr(ref,PTR.in_dll(M,prop),C.byref(out)))
    try:
        buf=C.create_string_buffer(2048)
        if not cftext(out,buf,len(buf),0x08000100):raise RuntimeError('Cannot decode MIDI endpoint name')
        return buf.value.decode('utf8')
    finally:release(out)

def endpoints(kind):
    count=api(M,'MIDIGetNumberOf'+kind+'s',[],C.c_size_t)
    get=api(M,'MIDIGet'+kind,[C.c_size_t],REF)
    return [{'ref':get(i),'name':name(get(i),'kMIDIPropertyName'),
             'display_name':name(get(i),'kMIDIPropertyDisplayName')} for i in range(count())]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',help='Exact display name of the L6 source')
    p.add_argument('--destination',help='Exact display name of matching L6 destination')
    p.add_argument('--query-pads',action='store_true',help='Only fixed file-count and current-assignment queries')
    p.add_argument('--seconds',type=float,default=12)
    p.add_argument('--output',type=Path,default=Path('analysis/l6_live_capture.jsonl'))
    a=p.parse_args()
    if not 1 <= a.seconds <= 120:p.error('Capture duration must be 1..120 seconds')
    if a.query_pads and not (a.source and a.destination):p.error('Queries require exact source and destination')
    title=cfstr(None,b'L6 firmware research: read-only probe',0x08000100)
    client=REF();check(client_new(title,None,None,C.byref(client)));release(title)
    try:
        sources=endpoints('Source');destinations=endpoints('Destination')
        inventory={'sources':sources,'destinations':destinations}
        print(json.dumps(inventory),flush=True)
        if not a.source:return
        source=next((s for s in sources if s['display_name']==a.source),None)
        if not source or 'L6' not in source['display_name']:raise ValueError('Exact L6 source not found')
        events=queue.Queue();pending=bytearray()
        def receive(ptr,refcon,connection):
            try:
                count=C.c_uint32.from_address(ptr).value
                if count>4096:raise ValueError('Unexpected packet count')
                pos=ptr+4 # SDK declares MIDIPacketList with 4-byte packing.
                for _ in range(count):
                    stamp=C.c_uint64.from_address(pos).value
                    size=C.c_uint16.from_address(pos+8).value
                    data=C.string_at(pos+10,size)
                    events.put({'direction':'device_to_host','timestamp':time.time(),'midi_timestamp':stamp,'hex':data.hex(' ')})
                    pos=(pos+10+size+3)&~3 # ARM MIDIPacketNext alignment from SDK.
            except Exception as exc:events.put({'capture_error':str(exc)})
        callback=READ(receive)
        port=REF();title=cfstr(None,b'L6 passive device reply listener',0x08000100)
        check(port_new(client,title,callback,None,C.byref(port)));release(title)
        check(connect(port,source['ref'],None))
        out=REF();destination=None
        if a.query_pads:
            destination=next((d for d in destinations if d['display_name']==a.destination),None)
            if not destination or 'L6' not in destination['display_name']:raise ValueError('Exact L6 destination not found')
            title=cfstr(None,b'L6 fixed read-only pad queries',0x08000100)
            check(out_new(client,title,C.byref(out)));release(title)
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open('x') as log:
            def write(row):
                log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
            write({'kind':'metadata','inventory':inventory,'source':a.source,'query_pads':a.query_pads,
                   'note':'RX is device output; TX entries are only this probe, never a spy on editor TX'})
            start=time.monotonic();next_query=start+1;queries=[(pad,sub) for pad in range(4) for sub in (0,2)] if a.query_pads else []
            received=0;sent=0
            while time.monotonic()-start<a.seconds:
                if queries and time.monotonic()>=next_query:
                    pad,sub=queries.pop(0)
                    data=bytes([0xf0,0x52,0,0,0x46,sub,pad,0xf7])
                    storage=C.create_string_buffer(1024);raw=C.create_string_buffer(data)
                    first=packet_init(storage)
                    if not packet_add(storage,len(storage),first,0,len(data),raw):raise RuntimeError('Packet construction failed')
                    check(send(out,destination['ref'],storage))
                    row={'direction':'probe_to_device','timestamp':time.time(),'hex':data.hex(' '),'decoded':decode(data)}
                    write(row);print(json.dumps(row),flush=True);sent+=1;next_query=time.monotonic()+0.5
                try:row=events.get(timeout=0.05)
                except queue.Empty:continue
                write(row)
                if 'hex' not in row:print(json.dumps(row),flush=True);continue
                for byte in bytes.fromhex(row['hex']):
                    if byte>=0xf8:continue
                    if byte==0xf0:pending.clear();pending.append(byte)
                    elif pending:
                        pending.append(byte)
                        if byte==0xf7:
                            message=bytes(pending);pending.clear()
                            full={'kind':'sysex','direction':'device_to_host','timestamp':row['timestamp'],'hex':message.hex(' ')}
                            try:full['decoded']=decode(message)
                            except ValueError as exc:full['decode_note']=str(exc)
                            write(full);print(json.dumps(full,ensure_ascii=False),flush=True);received+=1
                        elif len(pending)>8192:
                            write({'capture_error':'SysEx exceeded listener limit'});pending.clear()
            print(json.dumps({'sent_read_only_queries':sent,'received_sysex':received,'capture':str(a.output)}),flush=True)
    finally:
        client_free(client)

if __name__=='__main__':main()
