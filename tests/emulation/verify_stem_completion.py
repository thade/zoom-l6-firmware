#!/usr/bin/env python3
"""Stock recorder stop ordering with real WAV finalizers; offline RAM files only."""
import hashlib,json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0
from verify_pad_protocol import ROOT,IMAGE,BIAS
from verify_recording_writer import WriterRig,C
from verify_firmware_workflow import put32,get32

MD=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
STATE=0x801f8c48
STREAMS=(0,2,10)

def calls(start,end):
    return {int(i.op_str[1:],16) for i in MD.disasm(IMAGE[start-BIAS:end-BIAS],start) if i.mnemonic=='bl'}

def run(case,latched_error=0,header_error=False,close_error=False,delayed=False,metadata=None):
    r=WriterRig();m=r.m;events=[];payloads={}
    r.files={};r.cursor={}
    for stream in STREAMS:
        channels=1 if stream==0 else 2
        template=WriterRig(stream,channels);template.header()
        h=stream+1
        payload=struct.pack('<%df'%(64*channels),*([0.125*(stream+1)]*(64*channels)))
        payloads[h]=payload
        r.files[h]=template.files[1]+payload;r.cursor[h]=len(r.files[h])
        put32(m,C+0x1e4c+stream*4,h)
        put32(m,C+0x454+stream*4,64)
        m.uc.mem_write(C+0x448+stream,b'\x20')
    mask=sum(1<<i for i in STREAMS)
    put32(m,C+8,mask);put32(m,C+0x444,(1<<2)|(1<<10))
    put32(m,C+0x440,mask if delayed else 0)
    put32(m,C+0x1e48,latched_error)
    m.uc.mem_write(STATE+0x2c,b'\x01')
    m.uc.mem_write(STATE+8,bytes([2,0,1,1,0]))
    for fn in calls(0x8000b698,0x8000b9b4):m.hooks[fn]=lambda a:0
    # Original predicates, stream handle/length getters, finalizer and reset.
    for fn in (0x80037dc0,0x80037d68,0x80037d98,0x80037df0,
               0x80037e98,0x80037e58,0x8000ea08,0x800380d0,0x800032b0):
        m.hooks.pop(fn,None)
    m.hooks[0x80002360]=lambda a:1
    def delay(a):
        assert not any(e[0]=='finalize' for e in events)
        events.append(['wait',get32(m,C+0x440),int(m.uc.mem_read(C+0xe8,1)[0])])
        # Explicit scheduler fixture: streams drain, then producer finishes.
        if get32(m,C+0x440):
            put32(m,C+0x440,0);m.uc.mem_write(C+0xe8,b'\x01')
        else:m.uc.mem_write(C+0xe8,b'\0')
        return 0
    m.hooks[0x80077686]=delay
    def close(a):
        events.append(['close',a[0]-1])
        return 0xffffd825 if close_error and a[0]==1 else 0
    m.hooks[0x8005c1f8]=close
    def write(a):
        if header_error and a[0]==1:
            put32(m,a[3],0);events.append(['header_write_error',0]);return 0xffffd825
        return r.write(a)
    m.hooks[0x800622b0]=write
    def observe(uc,address,size,_):
        if address==0x8000ea08:
            assert get32(m,C+0x440)==0 and m.uc.mem_read(C+0xe8,1)==b'\0'
            events.append(['finalize',uc.reg_read(UC_ARM_REG_R0)-1])
        elif address==0x800032b0:
            assert [e for e in events if e[0]=='close']==[['close',i] for i in STREAMS]
            events.append(['postprocess_begin',get32(m,C+8),get32(m,C+0x1e48)])
    m.uc.hook_add(UC_HOOK_CODE,observe)
    # Execute original post-record dispatcher, while modeling its metadata and
    # the deeper per-file processing body. This is not actual Work-file moving.
    for fn in calls(0x800032b0,0x800035c8):m.hooks[fn]=lambda a:0
    m.hooks.pop(0x8000178e,None) # Original memset.
    m.hooks[0x80022c78]=lambda a:int(a[0] in STREAMS)
    m.hooks[0x80022bd0]=lambda a:1
    m.hooks[0x80022b80]=lambda a:(metadata or {}).get(a[0],0)
    m.hooks[0x80004868]=lambda a:events.append(['postprocess_stream',a[0],a[1]]) or 0
    m.hooks[0x80022938]=lambda a:events.append(['catalogue_update',a[0]]) or 0
    # Tail branch (ordinary path with no notification flag).
    m.hooks[0x800035d0]=lambda a:events.append(['postprocess_notification']) or 0
    m.invoke(0x8000b698,[0xffffffff])
    assert [e for e in events if e[0] in ('finalize','close')]==[
        [action,i] for i in STREAMS for action in ('finalize','close')],events
    if delayed:assert len([e for e in events if e[0]=='wait'])==2,events
    selected=[i for i in STREAMS if (metadata or {}).get(i,0)<=1]
    assert [e[1] for e in events if e[0]=='postprocess_stream']==selected,events
    for stream in STREAMS:
        h=stream+1;data=r.files[h]
        assert data[512:]==payloads[h]
        if not(header_error and stream==0):
            assert struct.unpack_from('<I',data,4)[0]==len(data)-8
            assert struct.unpack_from('<I',data,508)[0]==len(payloads[h])
    assert get32(m,C+8)==0 and all(get32(m,C+0x1e4c+i*4)==0 for i in range(12))
    assert get32(m,C+0x1e48)==latched_error
    assert m.uc.mem_read(STATE+8,1)==b'\0'
    return dict(case=case,passed=True,events=events)

def main():
    results=[run('ordinary_mono_stereo_stems_and_master_finalize_close_before_postprocessing'),
             run('stock_stop_waits_for_stream_mask_and_worker_busy_before_finalizers',delayed=True),
             run('latched_file_error_does_not_block_stop_finalization_or_postprocessing',latched_error=0xffffd825),
             run('stem_header_write_error_does_not_block_close_or_postprocessing',header_error=True),
             run('stem_close_error_does_not_block_other_files_or_postprocessing',close_error=True),
             run('postprocess_dispatch_uses_separate_per_stream_metadata_gate',metadata={0:2})]
    path=ROOT/'analysis/stem_completion_verification.json'
    path.write_text(json.dumps(dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=[
          'Original stop, predicates, length/handle getters, WAV finalizer, reset and postprocessing dispatcher execute',
          'RAM file payloads are seeded; audio capture/drain scheduling and public filesystem IO are modeled',
          'Deep per-file postprocessing and metadata getters are modeled, not a complete Work-to-final path test',
          'No hardware, SD durability, live RTOS scheduling, firmware patch or device access']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path))))

if __name__=='__main__':main()
