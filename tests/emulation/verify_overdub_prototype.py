#!/usr/bin/env python3
"""Execute the compiled ARM overdub prototype and selected stock L6 routines.

Entirely offline. Files are bytearrays; no SD, USB, MIDI, or flash access.
Real stock filesystem wrappers and catalogue code execute; driver I/O, RTOS,
audio selection, grouped persistence, qualification and exclusion are models.
"""
import copy
import hashlib
import json
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR
from verify_pad_protocol import Machine, IMAGE, BIAS, REGS, RETURN, STACK, ROOT
from verify_firmware_workflow import VOLUME, TABLE, put32
from verify_record_catalogue import BASE, STRIDE, putstr, getstr

STATE, PORT, JOB = 0x21010000, 0x21001000, 0x21002000
ELF = ROOT/'src/overdub/overdub.elf'
STATUS = ['ok','skipped','busy','invalid','io','wav','catalogue','assign','persist','cancelled','fault']


class Emulator(Machine):
    def __init__(self,cpu_model=None,mclass=False):
        self.uc=Uc(UC_ARCH_ARM,UC_MODE_THUMB | (UC_MODE_MCLASS if mclass else 0))
        if cpu_model is not None:self.uc.ctl_set_cpu_model(cpu_model)
        self.uc.mem_map(0x80000000,0x1000000)
        self.uc.mem_map(0x20000000,0x40000)
        self.uc.mem_map(0x21000000,0x40000)
        self.uc.mem_map(0x10000000,0x10000)
        self.uc.mem_write(0x80001000,IMAGE[0x200:0xb5ce4])
        self.hooks={};self.installed=set();self.reached_return=False
        with ELF.open('rb') as f:
            elf=ELFFile(f)
            for seg in elf.iter_segments():
                if seg['p_type']=='PT_LOAD' and seg['p_filesz']:
                    self.uc.mem_write(seg['p_vaddr'],seg.data())
            self.symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        self.layout=struct.unpack('<11I',self.uc.mem_read(self.symbols['od_layout'],44))

    def invoke(self,address,args):
        for addr in {RETURN,*self.hooks}-self.installed:
            self.uc.hook_add(UC_HOOK_CODE,self._hook,begin=addr,end=addr)
            self.installed.add(addr)
        self.uc.reg_write(UC_ARM_REG_SP,getattr(self,'stack',STACK))
        self.uc.reg_write(UC_ARM_REG_LR,RETURN|1)
        for reg,value in zip(REGS,args):self.uc.reg_write(reg,value)
        self.reached_return=False
        self.uc.emu_start(address|1,RETURN+2,count=100000000)
        assert self.reached_return,f'Instruction limit or unexpected exit at {self.uc.reg_read(UC_ARM_REG_PC):08x}'
        return self.uc.reg_read(REGS[0])


class Rig:
    def __init__(self):
        self.m=getattr(self,'emulator_factory',Emulator)();m=self.m
        self.files={};self.handles={};self.events=[];self.counts={};self.fail=None
        self.locked=False;self.pads=[];self.durable=[];self.wrong_readback=False
        self.restore_fails=False;self.mutate_shared=False;self.copy_corruption=False
        self.segment_unknown=False;self.busy=False
        self.state_size,self.job_size,self.pad_size,self.port_size,*_=m.layout
        self.mode_offset=m.layout[9]
        for pad in range(4):
            base=BASE+pad*STRIDE
            for fn in (0x8002a2e0,0x8002a428,0x8002a2c8):m.invoke(fn,[base])
            putstr(m,base+0x14,f'A:\\SOUND_PAD\\PAD{pad+1}')
            raw=bytearray(self.pad_size)
            raw[self.mode_offset:self.mode_offset+24]=struct.pack('<6I',pad,0x3f800000,pad+7,8,9,10)
            self.pads.append(bytes(raw))
        self.durable=copy.deepcopy(self.pads)
        for i in range(24):m.uc.mem_write(0x801f9270+i*0x2c4,b'\xff')
        m.uc.mem_write(VOLUME+0x206,b'\x01')
        m.uc.mem_write(VOLUME+0x20c,struct.pack('<H',512))
        put32(m,VOLUME+0x258,TABLE)
        for fn in (0x8001bf88,0x8002b130,0x8002b110,0x8002b100,
                   0x80035180,0x80035190,0x800351b0,0x80035168,
                   0x80032810,0x80001848,0x8001d9b0):m.hooks[fn]=lambda a:0
        m.hooks[0x800670b0]=lambda a:VOLUME
        m.hooks.update({0x800604e8:self.open,0x80060818:self.read,
                        0x800624a8:self.write,0x8005c388:self.close,
                        0x80008f00:lambda a:0})
        ports=[0x8005ffe8,0x80060620,0x800622b0,0x8005c1f8,0x8005ef40,
               0x80008ee8,0x80008dd8]
        for i,fn in enumerate((self.enter,self.leave,self.qualify,self.snapshot,
                               self.assign,self.restore,self.save,self.checkpoint)):
            addr=0x21000000+i*0x10;m.hooks[addr]=fn;ports.append(addr)
        m.uc.mem_write(PORT,struct.pack('<15I',*(a|1 for a in ports)))

    def hit(self,op,**data):
        self.counts[op]=self.counts.get(op,0)+1
        self.events.append({'op':op,**data})
        return self.fail and self.fail[:2]==(op,self.counts[op])

    def sync(self,h):
        path,pos=self.handles[h]
        put32(self.m,h+0x21c,len(self.files[path]));put32(self.m,h+0x22c,pos)

    def open(self,a):
        h,ptr,flags,attr=a[:4];path=getstr(self.m,ptr)
        if self.hit('open',path=path,flags=flags):return 0xffffd825
        if flags==0:
            assert attr==0x100
            if path not in self.files:return 0xffffd75a
        else:
            assert flags==0x501 and attr==0x80 and path.startswith('A:\\SOUND_PAD\\PAD')
            if path in self.files:return 0xffffd75b
            self.files[path]=bytearray()
        self.handles[h]=[path,0]
        self.m.uc.mem_write(h,bytes([0x40,flags&3]))
        put32(self.m,h+0x230,VOLUME);self.sync(h)
        return 0

    def read(self,a):
        h,ptr,n,out=a[:4];path,pos=self.handles[h]
        bad=self.hit('read',path=path,requested=n)
        if bad and self.fail[2]=='error':put32(self.m,out,0);return 0xffffd825
        data=bytes(self.files[path][pos:pos+n])
        if bad:data=data[:-1]
        self.m.uc.mem_write(ptr,data);put32(self.m,out,len(data))
        self.handles[h][1]+=len(data);self.sync(h)
        return 0 if data else 0xffffd759

    def write(self,a):
        h,ptr,n,out=a[:4];path,pos=self.handles[h]
        assert path.startswith('A:\\SOUND_PAD\\PAD'), 'Attempt to modify original recording'
        bad=self.hit('write',path=path,requested=n)
        if bad and self.fail[2]=='error':put32(self.m,out,0);return 0xffffd825
        data=bytes(self.m.uc.mem_read(ptr,n-(1 if bad else 0)))
        self.files[path][pos:pos+len(data)]=data
        self.handles[h][1]+=len(data);put32(self.m,out,len(data));self.sync(h)
        return 0

    def close(self,a):
        h=a[0];path,_=self.handles.pop(h)
        if self.copy_corruption and path.startswith('A:\\SOUND_PAD') and len(self.files[path])>1000:
            self.files[path][-8]^=1;self.copy_corruption=False
        self.m.uc.mem_write(h,b'\xff')
        return 0xffffd825 if self.hit('close',path=path) else 0

    def enter(self,a):
        if self.busy or self.locked:return 1
        self.locked=True;self.hit('enter');return 0

    def leave(self,a):
        assert self.locked;self.locked=False;self.hit('leave');return 0

    def qualify(self,a):
        path=getstr(self.m,a[0]);self.hit('qualify',path=path)
        if self.mutate_shared:
            putstr(self.m,JOB+self.m.layout[10],'A:\\RECORDER\\OVERWRITTEN\\MASTER.WAV')
            self.mutate_shared=False
        return int(self.segment_unknown or path.replace('MASTER.WAV','MASTER_01.WAV') in self.files)

    def snapshot(self,a):
        if self.hit('snapshot',pad=a[0]):return 1
        self.m.uc.mem_write(a[1],self.pads[a[0]]);return 0

    def assign(self,a):
        pad,ptr,prior=a[:3];path=getstr(self.m,ptr)
        assert self.locked and path in self.files
        # This proposed adapter stands in for audio selection + parameter
        # preservation. It is deliberately NOT labelled a verified stock ABI.
        raw=bytearray(self.m.uc.mem_read(prior,self.pad_size))
        raw[:522]=bytes(522);enc=(path+'\0').encode('utf-16le');raw[:len(enc)]=enc
        if self.wrong_readback:raw[self.mode_offset]^=1
        self.pads[pad]=bytes(raw)
        return 1 if self.hit('assign',pad=pad,path=path) else 0

    def restore(self,a):
        if self.restore_fails:return 1
        self.pads[a[0]]=bytes(self.m.uc.mem_read(a[1],self.pad_size))
        self.hit('restore',pad=a[0]);return 0

    def save(self,a):
        # Even a failed save may have changed persistent state. Rollback must
        # restore and save again; this model does not simulate power loss.
        self.durable=copy.deepcopy(self.pads)
        return 1 if self.hit('save') else 0

    def checkpoint(self,a):return 1 if self.hit('checkpoint') else 0

    def take(self,n):
        path=f'A:\\RECORDER\\TAKE{n:03}\\MASTER.WAV'
        template=ROOT/'analysis/overdub_test/pass2/261002_181142/MASTER.WAV'
        with template.open('rb') as f:header=bytearray(f.read(910))
        assert header[902:906]==b'data'
        samples=struct.pack('<ff',n/100,-n/100)*1024
        struct.pack_into('<I',header,4,len(header)+len(samples)-8)
        struct.pack_into('<I',header,906,len(samples))
        self.files[path]=header+samples
        self.files[path.replace('MASTER.WAV','TRACK03_ST.WAV')]=bytearray(b'untouched clean stem fixture')
        return path

    def promote(self,path,*,target=-1,closed=1,post=1,parts=1):
        self.m.uc.mem_write(JOB,bytes(self.job_size))
        self.m.uc.mem_write(JOB,struct.pack('<iIII',target,closed,post,parts))
        putstr(self.m,JOB+self.m.layout[10],path)
        originals={p:bytes(b) for p,b in self.files.items() if p.startswith('A:\\RECORDER')}
        r=self.m.invoke(self.m.symbols['od_promote'],[STATE,PORT,JOB])
        assert r<len(STATUS),hex(r)
        assert not self.locked
        assert all(bytes(self.files[p])==b for p,b in originals.items())
        assert not self.handles,self.handles
        return STATUS[r]

    def history(self):
        count=struct.unpack('<I',self.m.uc.mem_read(STATE,4))[0]
        return [getstr(self.m,STATE+self.m.layout[4]+i*522) for i in range(count)]

    def padpaths(self):
        return [p[:522].decode('utf-16le').split('\0')[0] for p in self.pads]


def main():
    results=[]
    def passed(case,**data):results.append({'case':case,'passed':True,**data})
    rig=Rig();paths=[]
    for n in range(1,7):
        path=rig.take(n);paths.insert(0,path)
        assert rig.promote(path)=='ok'
        assert rig.history()==paths[:4]
        for pad,source in enumerate(paths[:4]):assert rig.files[rig.padpaths()[pad]]==rig.files[source]
        assert rig.pads==rig.durable
    passed('six_passes_rotate_latest_four',source_history=rig.history(),pad_files=rig.padpaths())
    saved=copy.deepcopy(rig.pads);assert rig.promote(paths[0])=='skipped' and rig.pads==saved
    passed('duplicate_completion_does_not_rotate')

    whole=Rig();path=whole.take(1)
    whole.files[path]=bytearray((ROOT/'analysis/overdub_test/pass2/261002_181142/MASTER.WAV').read_bytes())
    digest=hashlib.sha256(whole.files[path]).hexdigest()
    assert whole.promote(path)=='ok'
    assert hashlib.sha256(whole.files[whole.padpaths()[0]]).hexdigest()==digest
    passed('complete_actual_recorded_master',bytes=len(whole.files[path]),sha256=digest)

    for name,kw in [('pad_recording',{'target':0}),('master_close_failed',{'closed':0}),
                    ('postprocess_incomplete',{'post':0}),('segmented_job',{'parts':2})]:
        r=Rig();p=r.take(1);before=copy.deepcopy(r.pads)
        assert r.promote(p,**kw)==('skipped' if name=='pad_recording' else 'invalid')
        assert r.pads==before and r.history()==[]
        passed(name)
    for name in ('segment_on_card','qualification_unknown','missing_master','bad_riff',
                 'bad_format','empty_data','chunk_overflow','name_traversal','exclusive_collision',
                 'catalogue_full','file_info_failure','busy','corrupted_copy','owned_path','odd_metadata'):
        r=Rig();p=r.take(1);expected='invalid';before=copy.deepcopy(r.pads)
        if name=='segment_on_card':r.files[p.replace('MASTER.WAV','MASTER_01.WAV')]=bytearray(b'split')
        if name=='qualification_unknown':r.segment_unknown=True
        if name=='missing_master':del r.files[p];expected='io'
        if name=='bad_riff':r.files[p][4]^=1;expected='wav'
        if name=='bad_format':r.files[p][22]=1;expected='wav'
        if name=='empty_data':r.files[p]=r.files[p][:910];struct.pack_into('<I',r.files[p],4,902);struct.pack_into('<I',r.files[p],906,0);expected='wav'
        if name=='chunk_overflow':struct.pack_into('<I',r.files[p],906,0xffffffff);expected='wav'
        if name=='name_traversal':p='A:\\RECORDER\\..\\MASTER.WAV'
        if name=='exclusive_collision':r.files['A:\\SOUND_PAD\\PAD1\\OD00000001.WAV']=bytearray(b'keep me');expected='io'
        if name=='catalogue_full':r.m.hooks[0x80008ee8]=lambda a:1000;expected='catalogue'
        if name=='file_info_failure':r.m.hooks[0x8005f0a0]=lambda a:0xffffd825;expected='io'
        if name=='busy':r.busy=True;expected='busy'
        if name=='corrupted_copy':r.copy_corruption=True;expected='io'
        if name=='owned_path':r.mutate_shared=True;expected='ok'
        if name=='odd_metadata':
            r.files[p][902:902]=b'JUNK'+struct.pack('<I',3)+b'abc\0'
            struct.pack_into('<I',r.files[p],4,len(r.files[p])-8);expected='ok'
        actual=r.promote(p);assert actual==expected,(name,actual)
        if expected!='ok':assert r.pads==before and r.history()==[]
        if name=='exclusive_collision':assert r.files['A:\\SOUND_PAD\\PAD1\\OD00000001.WAV']==b'keep me'
        passed(name,status=actual)

    # Connect the core to the ORIGINAL recording-shutdown instruction sequence.
    # A single emulated call-site redirect replaces the candidate BL in RAM only.
    # Source-path capture, completion status and RTOS/audio effects remain models.
    decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    callees={int(i.op_str[1:],16) for i in decoder.disasm(
        IMAGE[0x8000b698-BIAS:0x8000b9b4-BIAS],0x8000b698) if i.mnemonic=='bl'}
    for target,active,post_enabled,master_failure in [(-1,1,1,False),(-1,1,1,True),
                                                     (0,1,1,False),(-1,0,1,False),(-1,1,0,False)]:
        r=Rig();m=r.m;path=r.take(1);events=[]
        m.uc.mem_write(JOB,bytes(r.job_size))
        m.uc.mem_write(JOB,struct.pack('<iIII',target,1,0,1))
        putstr(m,JOB+m.layout[10],path);put32(m,0x21003000,0xffffffff)
        m.uc.mem_write(0x801f8c48+0x2c,bytes([active]))
        m.uc.mem_write(0x801f8c48+8,bytes([2,0,1,post_enabled,0]))
        saved_hooks=dict(m.hooks)
        for fn in callees:m.hooks[fn]=lambda a:0
        for fn in (0x80037dc0,0x80037d68,0x80002360,0x80037df0):m.hooks[fn]=lambda a:1
        m.hooks[0x80037e98]=lambda a:0x1000+a[0]
        m.hooks[0x80037e58]=lambda a:8192
        def finalize(a):events.append(('finalize',a[0]-0x1000));return 0
        def close_stream(a):
            if a[0]>=0x80000000:return saved_hooks.get(0x8005c1f8,lambda a:0)(a)
            stream=a[0]-0x1000;events.append(('close',stream))
            if stream==10 and master_failure:put32(m,JOB+4,0);return 0xffffd825
            return 0
        def postprocess(a):
            events.append(('postprocess',a[0]))
            put32(m,JOB+8,1)
            # Restore the real filesystem close wrapper before running the core.
            m.hooks.pop(0x8005c1f8,None)
            return 0x1234
        m.hooks[0x8000ea08]=finalize;m.hooks[0x8005c1f8]=close_stream
        m.hooks[0x800032b0]=postprocess
        # Hook at the BL itself, not at its target: the bridge calls the original
        # postprocessor target without recursing into this redirect.
        def redirect(uc,addr,size,_):
            events.append(('hook',addr))
            uc.reg_write(UC_ARM_REG_LR,0x8000b97d)
            uc.reg_write(UC_ARM_REG_PC,m.symbols['od_emulator_after_postprocess'])
        m.uc.hook_add(UC_HOOK_CODE,redirect,begin=0x8000b978,end=0x8000b978)
        m.invoke(0x8000b698,[target&0xffffffff])
        result=struct.unpack('<I',m.uc.mem_read(0x21003000,4))[0]
        expected=0xffffffff if not active or not post_enabled else (1 if target>=0 else 3 if master_failure else 0)
        assert result==expected,(target,active,post_enabled,master_failure,result)
        if active and post_enabled:
            assert events[:24]==[(op,i) for i in range(12) for op in ('finalize','close')]
            assert events[24][0]=='hook' and events[25][0]=='postprocess'
        assert bool(r.history())==(expected==0)
        passed('stock_stop_bridge',target=target,active=active,post_enabled=post_enabled,
               master_close_failed=master_failure,result='not_called' if result==0xffffffff else STATUS[result])

    # Sweep every driver open/read/write/close call in a one-pad promotion,
    # not merely the first call: validation, copy and verification each fail.
    baseline=Rig();assert baseline.promote(baseline.take(1))=='ok'
    injected=0
    for op in ('open','read','write','close'):
        for at in range(1,baseline.counts[op]+1):
            for kind in (('error','short') if op in ('read','write') else ('error',)):
                r=Rig();p=r.take(1);before=copy.deepcopy(r.pads);r.fail=(op,at,kind)
                result=r.promote(p)
                assert result in ('io','fault'),(op,at,kind,result)
                assert r.pads==before and r.history()==[]
                if op=='close':assert r.promote(p)=='fault'
                injected+=1
    passed('all_one_pad_io_call_failures',injected_cases=injected,baseline_counts=baseline.counts)

    for name in ('assignment_failure','wrong_readback','save_failure','rollback_failure',
                 'cancelled','catalogue_insert_failure','later_pad_copy_failure'):
        r=Rig()
        for n in range(1,4):assert r.promote(r.take(n))=='ok'
        before=copy.deepcopy(r.pads);history=r.history();r.events=[];r.counts={}
        if name=='assignment_failure':r.fail=('assign',3,'error')
        if name=='wrong_readback':r.wrong_readback=True
        if name=='save_failure':r.fail=('save',1,'error')
        if name=='rollback_failure':r.fail=('assign',2,'error');r.restore_fails=True
        if name=='cancelled':r.fail=('checkpoint',2,'error')
        if name=='catalogue_insert_failure':
            # Pad1 inserts through real stock code, then pad2 has no free slot.
            # Exercise a partially extended catalogue with unchanged selection.
            r.m.hooks[0x8002aaa8]=lambda a:0xffffffff if a[0]==BASE+STRIDE else 20
        if name=='later_pad_copy_failure':
            # First pad copies three blocks; fail at pad2's first write.
            r.fail=('write',4,'error')
        p=r.take(4);actual=r.promote(p)
        expected={'assignment_failure':'assign','wrong_readback':'assign','save_failure':'persist',
                  'rollback_failure':'fault','cancelled':'cancelled','catalogue_insert_failure':'catalogue',
                  'later_pad_copy_failure':'io'}[name]
        assert actual==expected,(name,actual)
        assert r.history()==history
        if name!='rollback_failure':assert r.pads==before and r.durable==before
        else:assert r.promote(p)=='fault'
        if name in ('cancelled','catalogue_insert_failure','later_pad_copy_failure'):
            assert not any(e['op']=='assign' for e in r.events)
        passed(name,status=actual)

    report={'firmware_sha256':hashlib.sha256(IMAGE).hexdigest(),
            'prototype_elf_sha256':hashlib.sha256(ELF.read_bytes()).hexdigest(),
            'struct_sizes':{'state':rig.state_size,'job':rig.job_size,'pad_snapshot':rig.pad_size},
            'passed_groups':len(results),'results':results,
            'executed_original_code':['filesystem open/read/write/close/info wrappers',
                                      'file-info driver', 'pad catalogue initialization/insertion/count',
                                      'recording shutdown branches with an emulator-only hook redirect'],
            'modelled_boundaries':['SD driver effects and RTOS primitives','recording completion qualification',
                                  'scheduler exclusion and cooperative yield','audio assignment/readback/rollback',
                                  'grouped persistence'],
            'limitations':['No device I/O or flashable image; ELF address is emulator-only.',
                           'Session history is RAM-only. No reboot or power-loss atomicity.',
                           'Partial/unselected copies and catalogue entries are retained on failure.',
                           'One complete actual recorded master plus short synthetic float32 fixtures.',
                           'No whole-device hook integration, timing, watchdog, memory-placement or audio test.']}
    out=ROOT/'analysis/overdub_prototype_verification.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed_groups':len(results),'injected_io_cases':injected,'report':str(out),
                      'state_bytes':rig.state_size},indent=2))


if __name__=='__main__':main()
