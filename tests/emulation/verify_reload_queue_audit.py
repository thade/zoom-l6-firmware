#!/usr/bin/env python3
"""Native queue allocation, dispatch and event-loss audit, entirely offline.
Original instructions execute; allocator backing, task creation, synchronization,
and kernel FIFO copying/wakeup are fixtures. No stock image is modified.
"""
from collections import deque
import hashlib,json,struct
from unicorn.arm_const import UC_ARM_REG_R4,UC_ARM_REG_R5
from verify_overdub_prototype import Emulator,ELF
from verify_pad_protocol import ROOT,IMAGE,BIAS,STACK
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_pad_reload import consume_event
from verify_reload_ownership import Protocol,WORKER,UI,ACCEPTED
from verify_work_ownership import OK,BUSY

UI_SLOT=0x801f8f28;WORK_SLOT=0x801f8f3c
BUFFER=0x20020000;REDUCE=0x808cc524
PLAIN=(1,4,26,0,0);A=(1,4,26,101,102);B=(1,4,26,201,202)
def packed(words):return struct.pack('<'+'I'*len(words),*words)

def string(addr):return IMAGE[addr-BIAS:addr-BIAS+80].split(b'\0')[0].decode()

class QueueRig:
    def __init__(self):
        self.m=Emulator();self.allocations=[];self.tasks=[];self.queues={};self.next=0x21000000
        m=self.m
        m.hooks[0x80076c60]=self.task
        m.hooks[0x80076318]=lambda a:0x5555
        m.hooks[0x8006de78]=self.allocate
        for fn in (0x80073ec8,0x80073f18):m.hooks[fn]=lambda a:0
        assert m.invoke(0x80048248,[])==0
        for offset in range(4,0x24,4):
            handle=self.word(0x801f8f1c+offset)
            depth,width=struct.unpack('<2I',m.uc.mem_read(handle+0x3c,8))
            self.queues[handle]=dict(depth=depth,width=width,items=deque())
        self.ui=self.word(UI_SLOT);self.worker=self.word(WORK_SLOT)
        m.hooks[0x800763d8]=self.send
        m.hooks[0x80076710]=self.receive
        m.hooks[0x80076950]=lambda a:1
    def word(self,a):return int.from_bytes(self.m.uc.mem_read(a,4),'little')
    def allocate(self,a):
        ptr=self.next;self.next+=(a[0]+15)&~15
        assert self.next<=0x21040000
        self.allocations.append((ptr,a[0]));return ptr
    def task(self,a):
        self.tasks.append(dict(entry=hex(a[0]),name=string(a[1]),stack_words=a[2],parameter=a[3],creation_priority=a[4],handle_slot=hex(a[5])))
        put32(self.m,a[5],0x7000+len(self.tasks)*0x100);return 1
    def sync(self,h):put32(self.m,h+0x38,len(self.queues[h]['items']))
    def send(self,a):
        if a[0] not in self.queues:return 1 # semaphore release fixture
        q=self.queues[a[0]]
        if len(q['items'])>=q['depth']:return 0
        q['items'].append(bytes(self.m.uc.mem_read(a[1],q['width'])))
        self.sync(a[0]);return 1
    def receive(self,a):
        q=self.queues[a[0]]
        if not q['items']:return 0
        self.m.uc.mem_write(a[1],q['items'].popleft());self.sync(a[0]);return 1
    def seed(self,events):
        self.queues[self.ui]['items']=deque(packed(e) for e in events);self.sync(self.ui)
    def events(self):return [struct.unpack('<5I',p) for p in self.queues[self.ui]['items']]
    def event(self,e):
        self.m.uc.mem_write(BUFFER,packed(e));return self.m.invoke(0x8006e4b8,[BUFFER,0])
    def compact(self,events):
        self.m.uc.mem_write(REDUCE,b''.join(packed(e) for e in events))
        n=self.m.invoke(0x8001fd08,[len(events)])
        return [struct.unpack('<5I',self.m.uc.mem_read(REDUCE+i*20,20)) for i in range(n)]

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    r=QueueRig();m=r.m
    assert len(r.tasks)==35 and len(r.allocations)==8
    assert [(q['depth'],q['width']) for q in r.queues.values()]==[(64,16),(64,16),(4096,20),(1,16),(1,16),(8,16),(512,32),(512,32)]
    assert r.queues[r.ui]['width']==20 and r.queues[r.worker]['width']==32
    assert (r.ui,81920+80) in r.allocations and (r.worker,16384+80) in r.allocations
    before=list(r.allocations);assert m.invoke(0x80048248,[])==0 and r.allocations==before
    passed('original_initializer_and_queue_allocator_create_exact_widths_depths_and_80_byte_headers',queues=[dict(handle=hex(h),depth=q['depth'],width=q['width']) for h,q in r.queues.items()])
    main_task=next(t for t in r.tasks if t['name']=='Main')
    assign_task=next(t for t in r.tasks if t['name']=='SamplerFileAssign')
    assert main_task['entry']=='0x8006dd71' and main_task['stack_words']==0x2000
    assert assign_task['entry']=='0x80036291' and assign_task['stack_words']==0x1000
    passed('task_table_identifies_assignment_worker_and_main_UI_owner',main=main_task,assignment=assign_task,stack_units='words; original task creator shifts r2 left by two at 0x80076c66')

    raw=bytes(range(48));m.uc.mem_write(BUFFER,raw)
    assert m.invoke(0x800483f8,[r.worker,BUFFER])==0
    assert r.queues[r.worker]['items'][0]==raw[:32]
    m.uc.mem_write(BUFFER+0x100,b'?'*48)
    assert m.invoke(0x800483a8,[r.worker,BUFFER+0x100])==0
    assert bytes(m.uc.mem_read(BUFFER+0x100,48))==raw[:32]+b'?'*16
    passed('existing_worker_queue_copies_only_32_bytes_so_48_byte_packet_is_truncated')

    assert r.event(A)==0 and r.event(B)==0
    assert r.events()==[A,B]
    m.uc.mem_write(BUFFER,b'?'*36)
    assert m.invoke(0x80020690,[BUFFER])==0
    assert bytes(m.uc.mem_read(BUFFER,36))==packed(A)+b'?'*16
    assert r.events()==[B]
    passed('original_event_sender_and_receiver_preserve_two_ticket_words_within_20_bytes')

    r=QueueRig();callback=0x20030000;received=[]
    r.m.hooks[callback]=lambda a:received.append(bytes(r.m.uc.mem_read(a[0],28))) or 0
    raw=packed((callback|1,0x524c4431,101,102,1,0,0,0))
    r.m.uc.mem_write(BUFFER,raw)
    assert r.m.invoke(0x800483f8,[r.worker,BUFFER])==0
    def dequeue(a):
        if not r.queues[r.worker]['items']:return stop(r.m)
        return 0 if r.receive(a) else 0xffffffff
    r.m.hooks[0x800483a8]=dequeue
    r.m.invoke(0x80036290,[])
    assert received==[raw[4:]]
    passed('original_assignment_worker_invokes_replacement_callback_with_28_inline_argument_bytes',limitation='Decoder callback is a capture fixture; no compact compiled decoder in this audit')

    for start,reg in ((0x8002c256,UC_ARM_REG_R5),(0x8002c39a,UC_ARM_REG_R4),(0x8002c3d2,UC_ARM_REG_R4),(0x8002c406,UC_ARM_REG_R4),(0x8002c43e,UC_ARM_REG_R4)):
        r=QueueRig();r.seed([A]);seen=[]
        def handler(a):seen.append(tuple(struct.unpack('<5I',r.m.uc.mem_read(a[0],20))));return stop(r.m)
        r.m.hooks[0x8002d568]=handler
        r.m.uc.reg_write(reg,STACK+4);r.m.invoke(start,[])
        assert seen==[A]
    assert consume_event(A)==0 and consume_event(B)==0
    passed('all_five_original_main_event_loop_branches_route_tagged_reload_to_same_handler',limitation='Entered at loop boundaries with initialized message-buffer register; startup bodies not executed; handler effects separately fixture-tested')

    r=QueueRig()
    assert r.compact([PLAIN,PLAIN])==[PLAIN]
    assert r.compact([A,B])==[A,B]
    assert r.compact([A,A,B])==[A,B]
    passed('backlog_filter_merges_identical_reload_events_but_preserves_distinct_ticket_pairs')

    # Negative control: this is valid filter input, not a claim that stock input
    # devices generate this particular event combination during normal use.
    other=(2,3,26,0,0)
    assert r.compact([A,B,other])==[other]
    assert r.compact([A,B,(0,6,26,0,0)])==[(0,6,26,0,0)]
    passed('other_event_classes_can_remove_earlier_tagged_reloads_by_code_alone',reachability='Constructed adversarial input; normal production of these same-code combinations is not established')

    r=QueueRig();r.seed([PLAIN]*4094+[A,B]);assert r.event((1,4,27,0,0))==0
    assert r.events()==[PLAIN,A,B,(1,4,27,0,0)]
    passed('actual_full_4096_event_send_path_drains_filters_and_requeues_20_byte_ticket_events')

    r=QueueRig();r.seed([PLAIN,PLAIN,A,B]);assert r.m.invoke(0x80020360,[])==1
    assert r.events()==[PLAIN,A,B]
    passed('explicit_UI_backlog_cleanup_also_uses_duplicate_filter_outside_full_queue_path')

    r=QueueRig();r.seed([A,B,(1,4,27,0,0)])
    r.m.invoke(0x80020548,[1,4,26,0])
    assert r.events()==[(1,4,27,0,0)]
    passed('targeted_removal_matches_first_three_words_and_ignores_reload_tickets',reachability='Routine exercised with reload tuple; not an assertion that recovered callers request this tuple')

    r=QueueRig();r.seed([A,B,(1,4,27,0,0)])
    r.m.invoke(0x80020438,[]);assert r.events()==[]
    passed('original_whole_queue_flush_discards_tagged_reloads',caller='0x8002c4a2 in startup/mode-5 path; no cancellation acknowledgement')

    # Build real compiled ownership branches, then route their inline ticket
    # candidates through the original flush. Losing transport must not retire
    # either branch or permit publication.
    p=Protocol();r=QueueRig();owners=[];events=[]
    for _ in range(2):
        status,owner=p.begin();assert status==OK;owners.append(owner)
        w=p.envelope(owner,WORKER)
        assert p.rl('sent',owner,WORKER,ACCEPTED)==OK
        assert p.rl('producer_return',owner)==OK and p.on('claim',w)==OK
        assert p.rl('prepare_ui',owner)==OK
        _,_,child,_=struct.unpack('<4I',p.envelope(owner,UI))
        assert p.rl('sent',owner,UI,ACCEPTED)==OK and p.on('complete',w)==OK
        events.append((1,4,26,owner,child))
    r.seed(events);r.m.invoke(0x80020438,[]);assert not r.events()
    assert all(p.finish(o)==BUSY for o in owners)
    assert p.word()==2 and p.promotion()[0]==BUSY
    passed('compiled_ownership_retains_both_jobs_when_original_flush_loses_their_UI_tickets',limitation='Two independent emulator CPUs couple only packet bytes; no native cancellation adapter yet')

    r=QueueRig();r.seed([A,B]);r.queues[r.ui]['depth']=2
    # Kernel failure here is forced at depth two, below stock compaction threshold.
    assert r.event(PLAIN)==0xffffffff and r.events()==[A,B]
    passed('event_transport_returns_send_failure_and_does_not_prove_delivery',limitation='Synthetic reduced capacity exercises kernel failure return below stock 4096 threshold')

    out=ROOT/'analysis/reload_queue_audit_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Offline original control flow with modeled heap backing, task creation, critical sections and kernel FIFO data copying; no complete RTOS scheduling',
      'Compact worker/UI formats are candidate layouts; no compiled decoder or installed patch is provided by this audit',
      'Constructed cross-class and targeted-removal cases demonstrate routine semantics, not normal event-production reachability',
      'Live task-handle reuse, queue reset/cancellation ownership and public I/O errors remain unresolved',
      'No device communication, firmware patching, flashing or SD writes']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))
if __name__=='__main__':main()
