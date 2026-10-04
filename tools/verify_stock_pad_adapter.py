#!/usr/bin/env python3
"""Offline original pad control flow + compiled adapters. No hardware access."""
import hashlib
import json
import struct
from verify_overdub_prototype import Rig, STATE, PORT, JOB, STATUS, ELF
from verify_pad_protocol import ROOT, IMAGE
from verify_firmware_workflow import VOLUME, put32
from verify_record_catalogue import putstr, getstr

SETTINGS='A:\\SOUND_PAD\\L6PADSETTING.ZST'
CONFIG=0x80440dc8
TEMP=0x21004000


class StockRig(Rig):
    def __init__(self):
        super().__init__();m=self.m
        self.reject_load=False;self.reject_once_pad=None;self.parses={}
        for pad in range(4):
            putstr(m,CONFIG+0x798+pad*0x20a,'NO ASSIGN')
            m.uc.mem_write(CONFIG+0xfc4+pad,bytes([pad%3]))
            m.uc.mem_write(CONFIG+0xfc8+pad,bytes([49+pad]))
            m.uc.mem_write(CONFIG+0x329+pad,bytes([60+pad]))
        # Keep original control, parameter, path and sampler-state instructions.
        # Intercept only external audio-engine work and RTOS primitives here.
        for fn in (0x80076950,0x800763d8,0x80002d08,0x8000efe8,
                   0x800368a8,0x800367b8,0x80036818,0x800367e8,0x800368d8,
                   0x80036800,0x80036938,0x80036950,0x800368f0,0x80036908,
                   0x80036920,0x800366f8,0x80036860,0x80002ae0,0x80002b20,
                   0x80002b10,0x80002af8,0x80002b18,0x800368c0,0x800369a8):
            m.hooks[fn]=lambda a:0
        m.hooks[0x8000f0b0]=self.parse_wav
        m.hooks[0x8005ec30]=self.tell
        # The actual stock format validator and sample-loader control flow run.
        for index,name in ((10,'snapshot'),(11,'assign'),(12,'restore'),(13,'save')):
            put32(m,PORT+index*4,m.symbols['od_stock_'+name]|1)

    def open(self,a):
        path=getstr(self.m,a[1])
        if path!=SETTINGS:return super().open(a)
        h,_,flags,attr=a[:4]
        if self.hit('settings_open',flags=flags):return 0xffffd825
        if flags in (0,1):
            if path not in self.files:return 0xffffd75a
        elif flags==0x101:self.files.setdefault(path,bytearray())
        else:raise AssertionError(flags)
        self.handles[h]=[path,0];self.m.uc.mem_write(h,bytes([0x40,flags&3]))
        put32(self.m,h+0x230,VOLUME);self.sync(h);return 0

    def write(self,a):
        h,ptr,n,out=a[:4];path,pos=self.handles[h]
        if path!=SETTINGS:return super().write(a)
        bad=self.hit('settings_write',requested=n)
        if bad and self.fail[2]=='error':put32(self.m,out,0);return 0xffffd825
        data=bytes(self.m.uc.mem_read(ptr,n-(1 if bad else 0)))
        self.files[path][pos:pos+len(data)]=data;self.handles[h][1]+=len(data)
        put32(self.m,out,len(data));self.sync(h);return 0

    def close(self,a):
        h=a[0]
        if self.handles[h][0]!=SETTINGS:return super().close(a)
        self.handles.pop(h);self.m.uc.mem_write(h,b'\xff')
        return 0xffffd825 if self.hit('settings_close') else 0

    def parse_wav(self,a):
        h,_,out,_,length=a[:5];path,_=self.handles[h]
        self.parses[path]=self.parses.get(path,0)+1
        # Reject a reload after successful prevalidation to reproduce a stock
        # late failure. Parsing is a boundary model, not original RIFF parser.
        if self.reject_load and self.parses[path]%2==0:return 1
        if self.reject_once_pad is not None and f'\\PAD{self.reject_once_pad}\\' in path and self.parses[path]%2==0:
            self.reject_once_pad=None;return 1
        b=self.files[path]
        fmt=b.find(b'fmt ');data=b.find(b'data')
        if fmt<0 or data<0:return 1
        channels=struct.unpack_from('<H',b,fmt+10)[0]
        rate=struct.unpack_from('<I',b,fmt+12)[0]
        bits=struct.unpack_from('<H',b,fmt+22)[0]
        raw=bytearray(24)
        struct.pack_into('<H',raw,10,channels);struct.pack_into('<I',raw,12,rate)
        struct.pack_into('<H',raw,22,bits);self.m.uc.mem_write(out,bytes(raw))
        if length:self.m.uc.mem_write(length,struct.pack('<Q',len(b)-data-8))
        self.handles[h][1]=data+8;self.sync(h);return 0

    def tell(self,a):put32(self.m,a[1],self.handles[a[0]][1]);return 0

    def snapshot(self,pad):
        self.m.uc.mem_write(TEMP,bytes(self.pad_size))
        result=self.m.invoke(self.m.symbols['od_stock_snapshot'],[pad,TEMP])
        return result,bytes(self.m.uc.mem_read(TEMP,self.pad_size))

    def paths(self):
        return [getstr(self.m,CONFIG+0x798+pad*0x20a) for pad in range(4)]

    def promote(self,path):
        self.m.uc.mem_write(JOB,bytes(self.job_size))
        self.m.uc.mem_write(JOB,struct.pack('<iIII',-1,1,1,1))
        putstr(self.m,JOB+self.m.layout[10],path)
        originals={p:bytes(b) for p,b in self.files.items() if p.startswith('A:\\RECORDER')}
        result=self.m.invoke(self.m.symbols['od_promote'],[STATE,PORT,JOB])
        assert all(bytes(self.files[p])==b for p,b in originals.items())
        # Loaded samples retain file handles by design. All other handles close.
        active={struct.unpack('<I',self.m.uc.mem_read(0x807348d0+pad*0x22c+4,4))[0] for pad in range(4)}-{0}
        assert set(self.handles)==active,(self.handles,active)
        assert not self.locked
        return STATUS[result]

    def save(self):return self.m.invoke(self.m.symbols['od_stock_save'],[])


def main():
    results=[]
    def passed(case,**data):results.append({'case':case,'passed':True,**data})
    r=StockRig();expected=[]
    preserved_tail=bytes(range(256))*4
    r.m.uc.mem_write(0x80445524+0xc34,preserved_tail)
    parameters=[bytes(r.m.uc.mem_read(CONFIG+x,4)) for x in (0xfc4,0xfc8,0x329)]
    for n in range(1,7):
        path=r.take(n);expected.insert(0,path)
        assert r.promote(path)=='ok'
        assert r.history()==expected[:4]
        for pad,src in enumerate(expected[:4]):
            assert r.snapshot(pad)[0]==0
            assert r.files[r.paths()[pad]]==r.files[src]
        assert [bytes(r.m.uc.mem_read(CONFIG+x,4)) for x in (0xfc4,0xfc8,0x329)]==parameters
        assert r.files[SETTINGS][96:96+0xc34]==r.m.uc.mem_read(CONFIG+0x798,0xc34)
        assert r.files[SETTINGS][96+0xc34:]==preserved_tail
    passed('six_passes_with_stock_assignment_and_saved_settings',pads=r.paths(),settings_bytes=len(r.files[SETTINGS]))

    # Stock assignment's return value misses a late load failure; adapter catches it.
    for adapter in (False,True):
        r=StockRig();p=r.take(1);dest='A:\\SOUND_PAD\\PAD1\\OD_TEST.WAV'
        r.files[dest]=bytearray(r.files[p]);putstr(r.m,TEMP,dest)
        assert r.m.invoke(0x80008dd8,[0,TEMP,0])==0
        r.reject_load=True
        if adapter:
            _,prior=r.snapshot(0);r.m.uc.mem_write(TEMP+0x400,prior);putstr(r.m,TEMP,dest)
            result=r.m.invoke(r.m.symbols['od_stock_assign'],[0,TEMP,TEMP+0x400])
            assert result==1
        else:
            # Machine.invoke supports four register arguments; fifth stack value
            # is zero from the untouched stack fixture for the stock call.
            result=r.m.invoke(0x8004b760,[TEMP,0,0,1])
            assert result==0
        assert r.paths()[0]=='NO ASSIGN'
        passed('late_load_failure_'+('adapter_rejects' if adapter else 'stock_returns_success'),result=result)

    r=StockRig();r.reject_load=True
    assert r.promote(r.take(1))=='assign'
    assert r.history()==[] and r.paths()==['NO ASSIGN']*4
    passed('late_load_failure_restores_empty_pad')

    r=StockRig();assert r.promote(r.take(1))=='ok';previous=r.paths();history=r.history()
    r.reject_once_pad=2
    assert r.promote(r.take(2))=='assign'
    assert r.paths()==previous and r.history()==history and r.snapshot(0)[0]==0
    passed('late_second_pad_failure_restores_existing_first_pad')

    for kind in ('short','error','close'):
        r=StockRig();assert r.promote(r.take(1))=='ok';previous=r.paths();saved=bytes(r.files[SETTINGS]);history=r.history()
        r.counts={};r.fail=('settings_close',1,'error') if kind=='close' else ('settings_write',2,kind)
        assert r.promote(r.take(2))=='persist'
        assert r.paths()==previous and r.history()==history,(kind,r.paths(),previous,r.history(),history)
        def meaningful(data):
            # Stock UTF-16 setters leave unused bytes after the terminator.
            # Ignore only that padding; compare every other settings byte.
            b=bytearray(data)
            for pad in range(4):
                start=96+pad*522
                end=next(i for i in range(start,start+522,2) if b[i:i+2]==b'\0\0')+2
                b[end:start+522]=bytes(start+522-end)
            return b
        assert meaningful(r.files[SETTINGS])==meaningful(saved)
        passed('settings_failure_rolls_back_'+kind)

    # Convenience save's comparison cache masks a retry after failed disk output.
    r=StockRig();putstr(r.m,CONFIG+0x798,'A:\\SOUND_PAD\\PAD1\\CHANGED.WAV')
    r.fail=('settings_write',1,'error')
    assert r.m.invoke(0x80006b18,[])!=0
    first=r.counts['settings_write'];r.fail=None
    assert r.m.invoke(0x80006b18,[])==0 and r.counts['settings_write']==first
    assert r.save()==0 and r.counts['settings_write']>first
    passed('forced_verified_save_avoids_false_success_on_retry')

    for kind in ('short','close'):
        r=StockRig();r.fail=('settings_write',2,'short') if kind=='short' else ('settings_close',1,'error')
        result=r.m.invoke(0x8004b598,[0x80445524])
        assert result==0
        passed('stock_settings_writer_ignores_'+kind,result=result)

    r=StockRig();assert r.promote(r.take(1))=='ok'
    r.m.uc.mem_write(0x807348d0,b'\x00\x00\x00\x00')
    assert r.snapshot(0)[0]==1
    passed('snapshot_rejects_path_without_loaded_sample')
    r=StockRig();assert r.promote(r.take(1))=='ok'
    putstr(r.m,0x807348d0+0x20,'A:\\SOUND_PAD\\PAD1\\WRONG.WAV')
    assert r.snapshot(0)[0]==1
    passed('snapshot_rejects_runtime_path_mismatch')

    r=StockRig();p=r.take(1)
    assert r.m.invoke(0x800075a8,[1])==0
    assert struct.unpack('<I',r.m.uc.mem_read(0x801f8ed8,4))[0]==1
    assert r.promote(p)=='ok'
    assert struct.unpack('<I',r.m.uc.mem_read(0x801f8ed8,4))[0]==0
    passed('stock_assignment_clears_outer_busy_boolean_not_nestable')

    report={'passed_groups':len(results),'results':results,
            'firmware_sha256':hashlib.sha256(IMAGE).hexdigest(),'elf_sha256':hashlib.sha256(ELF.read_bytes()).hexdigest(),
            'real_stock_execution':['pad format-validator and loader control flow','settings/path/loaded-state getters and setters',
                                    'pad unload and sample-handle lifetime','settings cache copying','filesystem wrappers and catalogue routines'],
            'modelled':['RIFF parser output','physical audio engine and prefetch','SD driver effects','RTOS exclusion and record completion'],
            'limitations':['No hardware or patched image','No power-loss atomicity; settings file updates in place',
                           'Runtime flags/path readback do not demonstrate audible playback','Scheduling exclusion remains a required unimplemented device binding']}
    path=ROOT/'analysis/stock_pad_adapter_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed_groups':len(results),'report':str(path)},indent=2))


if __name__=='__main__':main()
