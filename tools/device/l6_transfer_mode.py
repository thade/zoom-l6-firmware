#!/usr/bin/env python3
"""Enter or exit L6 File Transfer Mode over the Editor MIDI port.

Sends only fixed messages: identity request, editor open, heartbeat and the
file-transfer session command 31 09 01/00. The sequence follows
philmillman/zoom-l6-companion (MIT) and Magicking/L6-MassStorage: identity,
editor open, then activate; exiting needs an editor session kept alive with
heartbeats, primed once first. Success is judged by the card volume appearing
or disappearing, never by the acknowledgement alone. Quit the official Editor
first so the two do not interleave sessions on the same port. macOS only
(CoreMIDI and /Volumes); the card is any mounted volume laid out as an L6 card.

Stock session states (parser 0x800301f0, executed offline): identity moves
0 -> 1 and replies, but moves 1 -> 0 silently; editor open moves 1 -> 2 and
replies; 31 09 is accepted only in state 2. So an unanswered identity request is
repeated once, and the transfer command is sent only after the editor-open reply.
Byte 23 of that reply is 01 in File Transfer Mode and 00 otherwise (observed on
hardware), which confirms each change independently of the acknowledgement.

  enter    session, 31 09 01, wait for the card volume
  exit     card must be ejected; primed session, 31 09 00, then confirm mode 00
  session  open an editor session only, so status queries work without the Editor
"""
import argparse,ctypes as C,json,queue,subprocess,sys,time
from pathlib import Path
import l6_midi_probe as midi

ENDPOINT='L6 for L6 Editor Port'
IDENTITY=bytes((0xf0,0x7e,0x00,0x06,0x01,0xf7))
EDITOR_OPEN=bytes((0xf0,0x52,0,0,0x2b,0xf7))
HEARTBEAT=bytes((0xf0,0x52,0,0,0x31,0x0b,0xf7))
TRANSFER={True:bytes((0xf0,0x52,0,0,0x31,0x09,0x01,0xf7)),False:bytes((0xf0,0x52,0,0,0x31,0x09,0x00,0xf7))}
ALLOWED={IDENTITY,EDITOR_OPEN,HEARTBEAT,*TRANSFER.values()}
EDITOR_REPLY=bytes((0xf0,0x52,0,0,0x2a))
ACK_TRANSFER=bytes((0xf0,0x52,0,0,0x00,0x09,0xf7))
MODE_BYTE=23

class EditorLink:
    def __init__(self,log):
        self.log=log;self.events=queue.Queue();self.pending=bytearray();self.client=midi.REF()
        title=midi.cfstr(None,b'L6 transfer mode',0x08000100)
        try:midi.check(midi.client_new(title,None,None,C.byref(self.client)))
        finally:midi.release(title)
        source=[s for s in midi.endpoints('Source') if s['display_name']==ENDPOINT]
        dest=[s for s in midi.endpoints('Destination') if s['display_name']==ENDPOINT]
        if len(source)!=1 or len(dest)!=1:raise RuntimeError('Cannot identify the unique L6 Editor port')
        self.destination=dest[0]['ref'];self.input=midi.REF();self.output=midi.REF()
        self.callback=midi.READ(self.receive)
        title=midi.cfstr(None,b'L6 transfer replies',0x08000100)
        try:midi.check(midi.port_new(self.client,title,self.callback,None,C.byref(self.input)))
        finally:midi.release(title)
        midi.check(midi.connect(self.input,source[0]['ref'],None))
        title=midi.cfstr(None,b'L6 transfer commands',0x08000100)
        try:midi.check(midi.out_new(self.client,title,C.byref(self.output)))
        finally:midi.release(title)
    def close(self):
        if self.client.value:midi.client_free(self.client)
    def receive(self,ptr,refcon,connection):
        count=C.c_uint32.from_address(ptr).value;pos=ptr+4
        for _ in range(min(count,4096)):
            size=C.c_uint16.from_address(pos+8).value
            self.events.put(C.string_at(pos+10,size));pos=(pos+10+size+3)&~3
    def send(self,data):
        if data not in ALLOWED:raise ValueError('only fixed transfer-mode messages may be sent')
        storage=C.create_string_buffer(1024);raw=C.create_string_buffer(data);first=midi.packet_init(storage)
        if not midi.packet_add(storage,len(storage),first,0,len(data),raw):raise RuntimeError('Cannot build MIDI packet')
        midi.check(midi.send(self.output,self.destination,storage))
        self.log.append(dict(t=time.time(),sent=data.hex(' ')))
    def reply(self,timeout):
        """Next complete SysEx message within timeout, or None."""
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:chunk=self.events.get(timeout=.02)
            except queue.Empty:continue
            for b in chunk:
                if b>=0xf8:continue
                if b==0xf0:self.pending=bytearray((b,))
                elif self.pending:
                    self.pending.append(b)
                    if b==0xf7:
                        msg=bytes(self.pending);self.pending=bytearray()
                        self.log.append(dict(t=time.time(),received=msg[:24].hex(' ')+(' …' if len(msg)>24 else '')))
                        return msg
        return None
    def expect(self,match,timeout):
        """First message satisfying match within timeout, skipping others."""
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            msg=self.reply(max(0,deadline-time.monotonic()))
            if msg and match(msg):return msg
        return None
    def open_session(self):
        """Reach session state 2; returns the editor-open reply, or None."""
        for _ in range(2):
            self.send(IDENTITY)
            if self.reply(2):break
        self.send(EDITOR_OPEN)
        reply=self.expect(lambda m:m[:5]==EDITOR_REPLY and len(m)>MODE_BYTE,2)
        return reply
    def heartbeats(self,count=12):
        time.sleep(.32)
        for i in range(count):
            self.send(HEARTBEAT)
            if i==0:self.reply(.45)
            else:time.sleep(.1)
        time.sleep(.26)

def mounted_cards():
    """Mounted volumes laid out as an L6 card (SOUND_PAD/PAD1..PAD4), whatever their name."""
    return [v for v in Path('/Volumes').glob('*') if all((v/'SOUND_PAD'/f'PAD{n}').is_dir() for n in range(1,5))]
def card_ready():
    """A card volume exists and disk arbitration can describe it (safe to inspect/eject)."""
    cards=mounted_cards()
    return bool(cards) and all(subprocess.run(['/usr/sbin/diskutil','info',str(c)],capture_output=True).returncode==0 for c in cards)

def wait_for(predicate,timeout):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return True
        time.sleep(.5)
    return predicate()

def session(log):
    """Open a session; report the transfer-mode byte. Leaves the mixer in state 2."""
    link=EditorLink(log)
    try:reply=link.open_session()
    finally:link.close()
    return dict(session=bool(reply),transfer_mode=reply[MODE_BYTE] if reply else None)

def enter(log):
    if mounted_cards():return dict(already=True,card_mounted=True)
    link=EditorLink(log)
    try:
        reply=link.open_session()
        if not reply:return dict(session=False,card_mounted=False)
        if reply[MODE_BYTE]:return dict(session=True,already=True,card_mounted=wait_for(card_ready,30))
        link.send(TRANSFER[True]);ack=link.expect(lambda m:m==ACK_TRANSFER,1)
    finally:link.close()
    return dict(session=True,acknowledged=bool(ack),card_mounted=wait_for(card_ready,30))

def exit_(log,attempts=2):
    if mounted_cards():raise SystemExit('Eject the card normally before leaving File Transfer Mode')
    result=dict(card_mounted=False,transfer_mode=None)
    for attempt in range(attempts):
        link=EditorLink(log)
        try:
            link.open_session();link.heartbeats();time.sleep(1) # prime pass
            reply=link.open_session()
            if reply and not reply[MODE_BYTE]:return dict(result,already=True,transfer_mode=0)
            link.heartbeats();ack=None
            if reply:link.send(TRANSFER[False]);ack=link.expect(lambda m:m==ACK_TRANSFER,1)
        finally:link.close()
        # USB re-enumerates. This process's CoreMIDI endpoint references stay
        # stale without a run loop, so confirm from a fresh process.
        time.sleep(3);state=dict(session=False,transfer_mode=None);deadline=time.monotonic()+40
        while time.monotonic()<deadline and not state['session']:
            try:r=subprocess.run([sys.executable,__file__,'session'],capture_output=True,text=True,timeout=30)
            except subprocess.TimeoutExpired:r=None
            if r and r.returncode==0:state=json.loads(r.stdout)
            if not state['session']:time.sleep(2)
        result.update(attempt=attempt+1,acknowledged=bool(ack),transfer_mode=state['transfer_mode'])
        if state['transfer_mode']!=1:break # resend only if the mixer still reports transfer mode
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('mode',choices=('enter','exit','session'))
    p.add_argument('--log',type=Path)
    a=p.parse_args();log=[]
    try:result=dict(enter=enter,exit=exit_,session=session)[a.mode](log)
    finally:
        if a.log:a.log.write_text(json.dumps(log,indent=1)+'\n')
    print(json.dumps(dict(mode=a.mode,**result)))
if __name__=='__main__':main()
