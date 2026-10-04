#!/usr/bin/env python3
"""Offline additional-file lifecycle: compiled state machine, modeled file API.

Ordinary file handles and RAM are sentinel-protected. No filesystem/card access.
"""
import hashlib,json,struct
from verify_extra_capture import ExtraRig,STATE,ELF
from verify_uncompressed_tap import packed,B
from verify_record_catalogue import getstr
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

LIFE=0x22011000

class LifeRig(ExtraRig):
    def __init__(self):
        super().__init__();m=self.m
        self.life_layout=struct.unpack('<4I',self.raw(self.syms['life_layout'],16))
        self.disk={};self.opened={};self.next_handle=100
        self.calls=[];self.counts={};self.inject=None;self.corruption=None
        for h in range(1,8):self.files[h]=bytearray(('ordinary_take_file_%d'%h).encode()*31)
        self.ordinary={h:bytes(self.files[h]) for h in range(1,8)}
        self.original_ram=self.raw(0x8077ca30,0x4000)
        self.original_header_state=self.raw(0x801f8edc,128)
        m.hooks.update({0x8005ffe8:self.open_file,0x800622b0:self.write_file,
            0x80060620:self.read_file,0x8005c1f8:self.close_file,
            0x8005f168:self.seek_file,0x8005ef40:self.info_file})
    def hit(self,op):
        self.counts[op]=self.counts.get(op,0)+1;self.calls.append(op)
        if self.inject and self.inject[:2]==(op,self.counts[op]):return self.inject[2]
    def life(self,name,*args):
        argv=[LIFE] if name=='life_verified_path' else [LIFE,STATE,*args]
        return self.m.invoke(self.syms[name],argv)
    def phase(self):return struct.unpack('<I',self.raw(LIFE,4))[0]
    def path(self):return getstr(self.m,LIFE+self.life_layout[1])
    def assert_ordinary(self):
        assert {h:bytes(self.files[h]) for h in range(1,8)}==self.ordinary
        assert self.raw(0x8077ca30,0x4000)==self.original_ram
        assert self.raw(0x801f8edc,128)==self.original_header_state
    def open_file(self,a):
        out,p,flags,attrs=a[:4];path=getstr(self.m,p)
        assert path.startswith('A:\\SOUND_PAD\\PAD') and path.endswith('.WAV')
        put32(self.m,out,0)
        if self.hit('create' if flags else 'reopen'):return 0xffffd825
        if flags:
            assert flags==0x501 and attrs==0x80
            if path in self.disk:return 0xffffd75b
            self.disk[path]=bytearray()
        else:
            assert attrs==0x100
            if path not in self.disk:return 0xffffd75a
        h=self.next_handle;self.next_handle+=1;self.opened[h]=[path,0,flags]
        put32(self.m,out,h);return 0
    def write_file(self,a):
        h,p,n,out=a[:4];path,pos,flags=self.opened[h];assert flags
        op='initial_header' if pos==0 and not self.disk[path] else 'final_header' if pos==0 else 'audio'
        failure=self.hit(op)
        if failure=='error':put32(self.m,out,0);return 0xffffd825
        actual=n-1 if failure=='short' else n
        f=self.disk[path];f.extend(bytes(max(0,pos+actual-len(f))))
        f[pos:pos+actual]=self.raw(p,actual);self.opened[h][1]+=actual
        put32(self.m,out,actual);return 0
    def read_file(self,a):
        h,p,n,out=a[:4];path,pos,flags=self.opened[h];assert not flags
        failure=self.hit('read_header' if pos==0 else 'read_audio')
        if failure=='error':put32(self.m,out,0);return 0xffffd825
        n-=1 if failure=='short' else 0
        data=bytes(self.disk[path][pos:pos+n]);self.m.uc.mem_write(p,data)
        self.opened[h][1]+=len(data);put32(self.m,out,len(data));return 0
    def seek_file(self,a):
        h,offset,mode=a[:3];assert offset==0 and mode==2
        if self.hit('seek'):return 0xffffd825
        self.opened[h][1]=0;return 0
    def info_file(self,a):
        h,out=a[:2]
        if self.hit('info'):return 0xffffd825
        path,pos,flags=self.opened[h]
        self.m.uc.mem_write(out,struct.pack('<4I',len(self.disk[path]),pos,0,0));return 0
    def close_file(self,a):
        path,pos,flags=self.opened.pop(a[0]);op='close_write' if flags else 'close_read'
        failure=self.hit(op)
        if flags and self.corruption:
            f=self.disk[path]
            if self.corruption=='header':f[24]^=1
            elif self.corruption=='sample':f[600]^=1
            elif self.corruption=='truncate':del f[-1:]
            elif self.corruption=='append':f.extend(b'\0')
        return 0xffffd825 if failure else 0
    def feed(self,blocks=12):
        expected=[]
        for i in range(blocks):
            left=[(j+i)/256 for j in range(64)];right=[-(j+i)/512 for j in range(64)]
            assert self.capture([v*2**31 for v in left],[v*2**31 for v in right])==0
            expected.extend(v for pair in zip(left,right) for v in pair)
        return packed(expected)
    def finish(self):
        assert self.life('life_stop_quiesced')==0
        for _ in range(100):
            result=self.life('life_step')
            if result!=10:return result
        raise AssertionError('Lifecycle did not finish within bounded steps')
    def validate(self,expected):
        path=self.path();data=bytes(self.disk[path])
        assert data[0:4]==b'RIFF' and data[8:12]==b'WAVE'
        assert struct.unpack_from('<I',data,4)[0]==len(data)-8
        assert data[504:508]==b'data' and struct.unpack_from('<I',data,508)[0]==len(expected)
        assert struct.unpack_from('<HHIIHH',data,20)==(3,2,48000,384000,8,32)
        assert data[512:]==expected
        assert not self.opened and self.life('life_verified_path')==LIFE+self.life_layout[1]
        self.assert_ordinary()


def main():
    results=[]
    def passed(case,**kw):results.append(dict(case=case,passed=True,**kw))
    for pad in range(4):
        r=LifeRig();assert r.life('life_prepare',pad,1)==0
        assert r.phase()==1 and not r.life('life_verified_path')
        assert r.capture([0]*64,[0]*64)==2
        assert r.life('life_start_quiesced')==0
        assert r.life('life_start_quiesced')==12
        expected=r.feed();assert r.finish()==0;r.validate(expected)
        assert r.path()==f'A:\\SOUND_PAD\\PAD{pad+1}\\OD_00000001.WAV'
        assert r.life('life_step')==0 and r.life('life_prepare',pad,2)==11
    passed('unique_file_prepare_arm_start_drain_finalize_close_readback_in_all_four_pad_folders')
    r=LifeRig();old='A:\\SOUND_PAD\\PAD1\\OD_00000001.WAV';r.disk[old]=bytearray(b'OLD BACKING')
    assert r.life('life_prepare',0,1)==0 and r.path().endswith('00000002.WAV')
    r.life('life_start_quiesced');expected=r.feed(1);assert r.finish()==0;r.validate(expected)
    assert r.disk[old]==b'OLD BACKING'
    passed('exclusive_creation_skips_collision_without_modifying_existing_backing')
    r=LifeRig()
    for i in range(32):r.disk[f'A:\\SOUND_PAD\\PAD1\\OD_{i:08X}.WAV']=bytearray(b'old')
    snapshot={k:bytes(v) for k,v in r.disk.items()}
    assert r.life('life_prepare',0,0)==14 and snapshot==r.disk and not r.opened
    assert not r.life('life_verified_path')
    passed('collision_search_is_bounded_and_failure_never_yields_assignment_path')
    r=LifeRig();r.disk['A:\\SOUND_PAD\\PAD1\\OD_FFFFFFFF.WAV']=bytearray(b'old')
    assert r.life('life_prepare',0,0xffffffff)==14
    passed('filename_serial_exhaustion_does_not_wrap')
    r=LifeRig();assert r.life('life_prepare',4,1)==12 and not r.calls
    passed('invalid_pad_rejected_before_file_IO')
    r=LifeRig();r.life('life_prepare',0,1);r.life('life_start_quiesced')
    assert r.finish()==13 and not r.life('life_verified_path') and not r.opened
    passed('empty_recording_is_closed_but_not_eligible')
    failures=[]
    cases=[('create','error'),('initial_header','error'),('initial_header','short'),
           ('audio','error'),('audio','short'),('seek','error'),
           ('final_header','error'),('final_header','short'),('close_write','error'),
           ('reopen','error'),('info','error'),('read_header','error'),('read_header','short'),
           ('read_audio','error'),('read_audio','short'),('close_read','error')]
    for op,kind in cases:
        r=LifeRig();r.inject=(op,1,kind)
        outcome=r.life('life_prepare',0,1)
        if outcome==0:
            r.life('life_start_quiesced');r.feed();outcome=r.finish()
        assert outcome!=0 and r.phase()==7 and not r.life('life_verified_path')
        assert not r.opened;r.assert_ordinary()
        assert r.life('life_prepare',0,2)==11
        if op.startswith('close_'):assert struct.unpack('<I',r.raw(LIFE+12,4))[0]==1
        failures.append(op+':'+kind)
    passed('sixteen_file_failures_block_eligibility_and_leave_ordinary_state_unchanged',cases=failures)
    for corruption in ('header','sample','truncate','append'):
        r=LifeRig();r.corruption=corruption;r.life('life_prepare',0,1)
        r.life('life_start_quiesced');r.feed();assert r.finish()==15
        assert not r.opened and not r.life('life_verified_path');r.assert_ordinary()
    passed('reopen_verification_detects_header_payload_length_and_trailing_data_corruption')
    for phase in (1,2,3,4,5):
        r=LifeRig();r.life('life_prepare',0,1)
        if phase>=2:r.life('life_start_quiesced');r.feed(1)
        if phase>=3:r.life('life_stop_quiesced')
        while r.phase()<phase:assert r.life('life_step')==10
        assert r.life('life_cancel_quiesced')==16
        assert not r.opened and not r.life('life_verified_path')
        assert r.call('extra_drain')==4 and r.capture([0]*64,[0]*64)==4
        r.assert_ordinary()
    passed('quiesced_cancellation_at_each_live_phase_closes_file_and_disables_future_capture_or_drain')
    # Stop/start hook ordering itself remains an external contract. This test
    # verifies the callable boundary doesn't admit samples before arm/start.
    r=LifeRig();r.life('life_prepare',0,1)
    assert r.life('life_step')==11 and r.life('life_stop_quiesced')==12
    r.life('life_start_quiesced');r.feed(20);r.life('life_stop_quiesced')
    assert r.capture([0]*64,[0]*64)==2
    sizes=[]
    while True:
        before=len(r.calls);status=r.life('life_step');sizes.append(r.calls[before:])
        if status!=10:break
        assert not r.life('life_verified_path')
    assert status==0
    assert all(x.count('audio')<=1 and x.count('read_audio')<=1 for x in sizes)
    passed('incremental_drain_and_readback_withhold_eligibility_until_final_success')
    # Independently parse the new header with the original firmware WAV parser.
    r=LifeRig();r.life('life_prepare',0,1);r.life('life_start_quiesced')
    r.feed(3);assert r.finish()==0
    m=r.m;out=0x21033000
    assert m.invoke(0x8005ffe8,[out,LIFE+r.life_layout[1],0,0x100])==0
    handle=struct.unpack('<I',r.raw(out,4))[0]
    def parser_seek(a):
        h,offset,mode=a[:3];path,pos,flags=r.opened[h]
        offset=offset if offset<2**31 else offset-2**32
        assert mode in (0,1,2)
        r.opened[h][1]=(pos if mode==0 else len(r.disk[path]) if mode==1 else 0)+offset
        return 0
    m.hooks[0x8005f168]=parser_seek
    put32(m,m.stack,0x21034000)
    assert m.invoke(0x8000f0b0,[handle,0,0x21033100,0])==0
    assert r.raw(0x21033100,24)==bytes(r.disk[r.path()][12:36])
    assert struct.unpack('<Q',r.raw(0x21034000,8))[0]==192
    assert m.invoke(0x8005c1f8,[handle])==0
    passed('original_WAV_parser_accepts_private_header_and_recovers_stereo_float_format_and_frame_count')
    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        lifecycle_state_bytes=r.life_layout[0],
        limitations=['Public filesystem operations modeled with in-memory files',
          'Start/stop/cancel require externally quiesced producer and consumer; installed fence unbound',
          'Private float WAV header accepted by original WAV parser; full pad-loader/device playback unverified',
          'Readback uses exact header/length plus rolling 32-bit FNV-1a payload checksum, not cryptographic equivalence',
          'No pad catalogue/assignment/persistence mutation; verified path is eligibility only',
          'Failed files retained unassigned; uncertain-close instance quarantined without automatic retry',
          'No SD durability, scheduling, resource placement, split-file support or installed firmware'])
    out=ROOT/'analysis/extra_lifecycle_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))

if __name__=='__main__':main()
