#!/usr/bin/env python3
"""Bounded live test: list two known silent fixtures, select each, then clear pad 1.

Only uses the verified editor endpoint, command 46 read queries, and command 31/05
assignment of the two exact fixture names (or clearing). Never plays or records.
Requires the official editor to be connected. No arbitrary packet sender.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import queue
import time
import l6_midi_probe as midi
from decode_l6_sysex import decode

FIXTURES = ('L6_TEST_A.WAV', 'L6_TEST_B.WAV')
ENDPOINT = 'L6 for L6 Editor Port'

def pack7(raw):
    result=bytearray()
    for i in range(0,len(raw),7):
        chunk=raw[i:i+7]
        result.append(sum((v>>7)<<(6-j) for j,v in enumerate(chunk)))
        result.extend(v&127 for v in chunk)
    return bytes(result)

class Session:
    def __init__(self,path):
        self.log=path.open('x'); self.client=midi.REF(); self.pending=bytearray();self.events=queue.Queue()
        title=midi.cfstr(None,b'L6 authorised silent fixture test',0x08000100)
        try:midi.check(midi.client_new(title,None,None,C.byref(self.client)))
        finally:midi.release(title)
        source=[s for s in midi.endpoints('Source') if s['display_name']==ENDPOINT]
        dest=[s for s in midi.endpoints('Destination') if s['display_name']==ENDPOINT]
        if len(source)!=1 or len(dest)!=1:raise RuntimeError('Cannot identify unique L6 editor endpoints')
        self.destination=dest[0]['ref']; self.input=midi.REF();self.output=midi.REF()
        self.callback=midi.READ(self.receive)
        title=midi.cfstr(None,b'L6 fixture responses',0x08000100)
        try:midi.check(midi.port_new(self.client,title,self.callback,None,C.byref(self.input)))
        finally:midi.release(title)
        midi.check(midi.connect(self.input,source[0]['ref'],None))
        title=midi.cfstr(None,b'L6 bounded fixture selection',0x08000100)
        try:midi.check(midi.out_new(self.client,title,C.byref(self.output)))
        finally:midi.release(title)

    def write(self,row):
        self.log.write(json.dumps(row,ensure_ascii=False)+'\n');self.log.flush()

    def receive(self,ptr,refcon,connection):
        try:
            count=C.c_uint32.from_address(ptr).value
            if count>4096:raise ValueError('Invalid packet count')
            pos=ptr+4
            for _ in range(count):
                size=C.c_uint16.from_address(pos+8).value
                self.events.put((time.time(),C.string_at(pos+10,size)))
                pos=(pos+10+size+3)&~3
        except Exception as exc:self.events.put((time.time(),exc))

    def send(self,data):
        decoded=decode(data)
        assert decoded['pad_index']==0
        assert decoded['interpretation'] in ('request_file_count','request_listed_filename','request_assigned_filename','select_existing_file','clear_assignment')
        if decoded['interpretation']=='select_existing_file':assert decoded['filename'] in FIXTURES
        storage=C.create_string_buffer(1024);raw=C.create_string_buffer(data)
        first=midi.packet_init(storage)
        if not midi.packet_add(storage,len(storage),first,0,len(data),raw):raise RuntimeError('Cannot build MIDI packet')
        sent_at=time.time()
        midi.check(midi.send(self.output,self.destination,storage))
        self.write({'direction':'test_to_device','timestamp':sent_at,'hex':data.hex(' '),'decoded':decoded})
        return sent_at

    def wait(self,predicate,after,timeout=3):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:stamp,chunk=self.events.get(timeout=min(0.05,max(0,deadline-time.monotonic())))
            except queue.Empty:continue
            if isinstance(chunk,Exception):raise chunk
            self.write({'direction':'device_to_host','timestamp':stamp,'packet_hex':chunk.hex(' ')})
            for byte in chunk:
                if byte>=0xf8:continue
                if byte==0xf0:self.pending.clear();self.pending.append(byte)
                elif self.pending:
                    self.pending.append(byte)
                    if byte==0xf7:
                        packet=bytes(self.pending);self.pending.clear()
                        try:d=decode(packet)
                        except ValueError:d={'interpretation':'unknown','hex':packet.hex(' ')}
                        self.write({'kind':'sysex','direction':'device_to_host','timestamp':stamp,'decoded':d,'hex':packet.hex(' ')})
                        if stamp>=after and predicate(d):return d
                    elif len(self.pending)>8192:raise RuntimeError('Unexpected large response')
        raise TimeoutError('No matching device reply within bounded timeout')

    def query(self,sub,index=None):
        data=bytes([0xf0,0x52,0,0,0x46,sub,0]+([] if index is None else [index>>7,index&127])+[0xf7])
        at=self.send(data)
        return self.wait(lambda d:d.get('command')=='0x45' and d.get('subcommand')==sub and d.get('pad_index')==0,at)

    def assign(self,index,name):
        assert name in FIXTURES or name==''
        payload=pack7(name.encode('utf-16le'))
        data=bytes([0xf0,0x52,0,0,0x31,5,0,index>>7,index&127,len(payload)&127,len(payload)>>7])+payload+b'\xf7'
        self.send(data)
        # Assignment runs on a worker. Read back its result; no blind success claim.
        for _ in range(10):
            time.sleep(0.25)
            result=self.query(2)
            if result.get('filename')==name:return result
        raise RuntimeError('Assignment did not reach the expected filename')

    def close(self):
        midi.client_free(self.client);self.log.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exercise',action='store_true',help='Authorised selection A, selection B, then restore no assignment')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();session=None;changed=False;report={'exercise':a.exercise,'steps':[]}
    try:
        session=Session(a.output)
        count=session.query(0)['count'];report['count']=count
        assert count==2,f'Expected exactly two fixture files, found {count}'
        catalogue=[session.query(1,index) for index in range(count)]
        assert {d['filename'] for d in catalogue}==set(FIXTURES),catalogue
        report['catalogue']=catalogue
        before=session.query(2);report['before']=before
        assert before.get('filename') in ('',*FIXTURES), 'Refusing to alter a non-test assignment'
        print(json.dumps({'count':count,'names':[d['filename'] for d in catalogue],'assigned':before.get('filename')}),flush=True)
        if a.exercise:
            changed=True
            for name in FIXTURES:
                entry=next(d for d in catalogue if d['filename']==name)
                result=session.assign(entry['file_index'],name)
                report['steps'].append({'expected':name,'readback':result,'passed':True})
                print(json.dumps({'selected':name,'verified':True}),flush=True)
            result=session.assign(0,'')
            report['restored_none']=result['interpretation']=='no_file_assigned_reply'
            assert report['restored_none'];changed=False
        report['passed']=True
    except Exception as exc:
        report['error']=str(exc);report['passed']=False
        raise
    finally:
        if session:
            if changed:
                try:report['cleanup_readback']=session.assign(0,'')
                except Exception as exc:report['cleanup_error']=str(exc)
            session.close()
        a.output.with_suffix('.summary.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report),flush=True)

if __name__=='__main__':main()
