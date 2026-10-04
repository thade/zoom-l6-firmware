#!/usr/bin/env python3
"""Original reload producer, assignment worker and full reload callback.

Private ARM emulator, bytearray files; filesystem drivers, settings input,
RTOS and prefetch/conversion effects are explicitly modeled. No hardware I/O.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP,UC_ARM_REG_R0
from verify_stock_pad_adapter import StockRig,CONFIG
from verify_record_catalogue import putstr,getstr
from verify_overdub_prototype import ELF,Emulator
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT,IMAGE
BUSY_WORD=0x807348cc

def consume_event(words,busy=1):
    """Independent UI CPU: actual event branch, modeled downstream UI work."""
    m=Emulator();m.hooks[0x80076950]=lambda a:1
    m.hooks[0x800763d8]=lambda a:0;m.hooks[0x8001e4d8]=lambda a:0
    for fn in (0x80002ce8,0x80009840,0x80009930,0x80006b18,0x8000a5d8,0x800075a8):
        m.hooks[fn]=lambda a:0
    m.hooks[0x8000ac90]=lambda a:1
    put32(m,BUSY_WORD,busy);m.uc.mem_write(0x21008000,struct.pack('<5I',*words))
    m.invoke(0x8002d568,[0x21008000])
    return int.from_bytes(m.uc.mem_read(BUSY_WORD,4),'little')

class ReloadRig(StockRig):
    def __init__(self,names=None):
        super().__init__();m=self.m
        self.messages=[];self.events_reload=[];self.classification=[];self.prefetch=[]
        self.settings_result=0;self.queue_result=0;self.deliver=True;self.event_result=0
        self.expected=[];self.assignment_returns=[];self.callback_returns=[]
        self.before_event=None;self.before_prefetch=None
        m.hooks[0x80076950]=lambda a:1
        m.hooks[0x80006410]=lambda a:self.settings_result
        m.hooks[0x8006e4b8]=self.event
        m.hooks[0x800483f8]=self.enqueue
        m.hooks[0x800483a8]=self.dequeue
        m.hooks[0x800369a8]=self.fill
        put32(m,0x801f8f3c,0x6543)
        # Lower-level fixture effects are inherited from StockRig. Actual reload,
        # catalogue lookup, validation and loader control flow are not stubbed.
        def classify(uc,a,n,u):
            sp=uc.reg_read(UC_ARM_REG_SP)
            self.classification.append(struct.unpack('<4I',m.uc.mem_read(sp+8,16)))
        def returned(uc,a,n,u):
            self.callback_returns.append(uc.reg_read(UC_ARM_REG_R0))
        m.uc.hook_add(UC_HOOK_CODE,classify,begin=0x8004a2e6,end=0x8004a2e6)
        m.uc.hook_add(UC_HOOK_CODE,returned,begin=0x800362b6,end=0x800362b6)
        for addr in (0x80049e38,0x80049ec0,0x80049f42,0x80049fc8):
            m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:self.assignment_returns.append(uc.reg_read(UC_ARM_REG_R0)),begin=addr,end=addr)
        names=names or ['BACKING.WAV']*4
        template=self.take(800)
        data=bytes(self.files[template])
        for pad,name in enumerate(names):
            path=f'A:\\SOUND_PAD\\PAD{pad+1}\\{name}'
            self.files[path]=bytearray(data)
            putstr(m,0x21005000,name)
            assert m.invoke(0x80008dd8,[pad,0x21005000,1])==0
            putstr(m,CONFIG+0x798+pad*0x20a,path)
            self.expected.append(path)
    def word(self,a):return int.from_bytes(self.m.uc.mem_read(a,4),'little')
    def enqueue(self,a):
        assert a[0]==0x6543
        raw=bytes(self.m.uc.mem_read(a[1],32));assert int.from_bytes(raw[:4],'little')==0x80049da1
        self.events_reload.append(('send',self.word(BUSY_WORD),self.queue_result))
        if self.deliver:self.messages.append(raw)
        return self.queue_result
    def dequeue(self,a):
        assert a[0]==0x6543
        if not self.messages:return stop(self.m)
        self.m.uc.mem_write(a[1],self.messages.pop(0));return 0
    def event(self,a):
        words=struct.unpack('<5I',self.m.uc.mem_read(a[0],20))
        if self.before_event:self.before_event(self)
        self.events_reload.append(('event',*words,self.word(BUSY_WORD)))
        return self.event_result
    def fill(self,a):
        self.prefetch.append(tuple(a[:4]))
        if self.before_prefetch:self.before_prefetch(self)
        return 0
    def submit(self):return self.m.invoke(0x80008d68,[])
    def dispatch(self):return self.m.invoke(0x80036290,[])
    def run(self):self.submit();self.dispatch()
    def consume(self):
        self.ui=[]
        self.m.hooks[0x8001e4d8]=lambda a:0
        self.m.hooks[0x80018350]=lambda a:self.ui.append(('stop',a[0])) or 0
        self.m.hooks[0x8000ac90]=lambda a:0
        self.m.hooks[0x80006b18]=lambda a:self.ui.append(('save',self.word(BUSY_WORD))) or 0
        self.m.hooks[0x8000a5d8]=lambda a:self.ui.append(('refresh',self.word(BUSY_WORD))) or 0
        event=self.events_reload[-1][1:6]
        self.m.uc.mem_write(0x21008000,struct.pack('<5I',*event))
        self.m.invoke(0x8002d568,[0x21008000])

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=ReloadRig();r.run()
    assert r.paths()==r.expected and r.assignment_returns==[0]*4 and r.classification==[(4,4,4,4)]
    assert [x[0] for x in r.prefetch]==list(range(4))
    assert r.events_reload[-1]==('event',1,4,26,0,0,1)
    assert r.callback_returns==[0] and r.word(BUSY_WORD)==1
    assert all(r.snapshot(p)[0]==0 for p in range(4))
    passed('original_reload_producer_worker_and_callback_load_four_configured_catalogue_paths_then_emit_one_event',
           completion_event=[1,4,26,0,0],busy_after_callback=1)

    r=ReloadRig();r.settings_result=0xffffffff
    r.m.hooks[0x80008e40]=lambda a:0xffffffff
    r.run()
    # Explicitly no selected fallback cursor in this negative control.
    assert not r.assignment_returns and not r.prefetch
    assert r.classification==[(0,0,0,0)] and r.events_reload[-1]==('event',1,4,26,0,0,1)
    assert r.callback_returns==[0] and r.word(BUSY_WORD)==1
    passed('settings_read_failure_still_emits_same_event_and_returns_same_worker_value')

    r=ReloadRig();r.reject_load=True;r.run()
    assert r.assignment_returns==[0]*4 and r.classification==[(4,4,4,4)]
    assert r.paths()==['NO ASSIGN']*4 and not r.prefetch
    assert r.events_reload[-1]==('event',1,4,26,0,0,1)
    passed('late_WAV_loader_rejection_is_classified_as_success_despite_all_four_pads_becoming_unassigned')

    r=ReloadRig();r.fail=('open',2,'error');r.run()
    assert r.assignment_returns==[0]*4 and r.paths()[0]=='NO ASSIGN'
    assert r.paths()[1:]==r.expected[1:] and r.classification==[(4,4,4,4)]
    passed('late_file_open_failure_also_bypasses_assignment_return_and_requires_state_readback')

    r=ReloadRig();r.files[r.expected[0]][0:4]=b'NOPE'
    # Stock parser is a fixture; use a format field the real validator checks.
    fmt=r.files[r.expected[0]].find(b'fmt ')
    struct.pack_into('<I',r.files[r.expected[0]],fmt+12,44100)
    r.run();assert r.assignment_returns[0]==0xffffffff
    assert r.classification[0][0]==0x01010101 and r.paths()[1:]==r.expected[1:]
    assert r.events_reload[-1]==('event',1,4,26,0,0,1)
    passed('early_format_rejection_is_visible_at_assignment_return_but_not_in_completion_event')

    r=ReloadRig()
    for pad in range(4):putstr(r.m,CONFIG+0x798+pad*0x20a,'NO ASSIGN')
    r.run();assert r.classification==[(1,1,1,1)] and not r.assignment_returns and len(r.prefetch)==4
    assert r.paths()==r.expected
    passed('unassigned_settings_paths_skip_direct_load_but_fallback_can_assign_catalogue_candidates')

    r=ReloadRig()
    for pad in range(4):putstr(r.m,CONFIG+0x798+pad*0x20a,f'A:\\MISSING\\X{pad}.WAV')
    r.run();assert r.classification==[(3,3,3,3)] and not r.assignment_returns
    assert r.events_reload[-1]==('event',1,4,26,0,0,1)
    passed('missing_catalogue_names_are_distinct_internal_results_but_same_external_completion_event')

    r=ReloadRig();r.settings_result=0xffffffff
    r.run();assert r.classification==[(0,0,0,0)] and len(r.prefetch)==4
    assert r.paths()==r.expected
    passed('settings_failure_can_still_enter_fallback_and_load_catalogue_candidates',
           limitation='Synthetic initialized catalogue has candidate index zero; lookup/validator/loader execute stock')

    r=ReloadRig();r.event_result=0xffffffff;r.run()
    assert r.paths()==r.expected and r.callback_returns==[0xffffffff] and r.word(BUSY_WORD)==1
    passed('callback_return_tracks_event_enqueue_status_not_aggregate_per_pad_load_success')

    r=ReloadRig();r.queue_result=0xffffffff;r.deliver=False
    result=r.submit();assert result==0 and not r.messages and r.word(BUSY_WORD)==1
    r.dispatch();assert not r.callback_returns and not r.prefetch
    passed('failed_undelivered_submission_has_no_callback_completion_despite_normal_producer_return')

    r=ReloadRig();r.queue_result=0xffffffff;r.run()
    assert r.paths()==r.expected and len(r.callback_returns)==1
    passed('ambiguous_send_failure_can_also_have_delivered_and_completed_reload')

    r=ReloadRig();snapshots=[]
    def during(r):snapshots.append((len(r.prefetch),len(r.callback_returns),r.word(BUSY_WORD)))
    r.before_prefetch=during;r.before_event=during;r.run()
    assert snapshots==[(1,0,1),(2,0,1),(3,0,1),(4,0,1),(4,0,1)]
    passed('prefetch_and_event_publication_occur_before_callback_returns_so_event_is_not_return_fence')

    r=ReloadRig();r.submit();r.submit();r.dispatch()
    assert len(r.callback_returns)==2 and len(r.prefetch)==8 and r.word(BUSY_WORD)==1
    passed('two_queued_reloads_share_one_busy_word_and_same_event_without_unique_request_identity')

    for bad in (False,True):
        r=ReloadRig();r.reject_load=bad;r.run()
        event=r.events_reload[-1][1:6]
        assert consume_event(event,r.word(BUSY_WORD))==0
    passed('actual_UI_event_handler_clears_shared_busy_word_after_both_success_and_late_load_failure',
           event_handler='0x8002d568',branch='0x8002d74c',clear_helper='0x80008b68',
           limitation='Stop/unload/reload/save effects modeled in this independent UI CPU test')

    r=ReloadRig();observed=[]
    def consume_before_return(r):
        put32(r.m,BUSY_WORD,consume_event((1,4,26,0,0),r.word(BUSY_WORD)))
        observed.append((len(r.callback_returns),r.word(BUSY_WORD)))
    r.before_event=consume_before_return;r.run()
    assert observed==[(0,0)] and len(r.callback_returns)==1
    passed('UI_can_clear_busy_before_reload_worker_returns',
           limitation='Explicit two-CPU scheduling point; actual task priority/preemption remains unverified')

    r=ReloadRig();r.fail=('close',1,'error');r.run()
    assert r.paths()==r.expected and r.classification==[(4,4,4,4)]
    assert all(r.snapshot(p)[0]==0 for p in range(4))
    assert r.events_reload[-1]==('event',1,4,26,0,0,1)
    passed('injected_validation_close_error_is_not_detected_by_success_event_or_consistent_final_pad_snapshot',
           implication='Result readback is necessary but insufficient: retain I/O error evidence and descendant ownership')

    r=ReloadRig();r.run();before=dict(r.counts)
    r.consume()
    assert r.word(BUSY_WORD)==0 and r.paths()==r.expected and len(r.prefetch)==8
    assert r.counts['close']-before['close']==4 and r.counts['open']-before['open']==4
    assert r.ui==[('stop',p) for p in range(4)]+[('save',1),('refresh',0)]
    assert all(r.snapshot(p)[0]==0 for p in range(4))
    passed('completion_event_consumer_stops_unloads_and_reloads_all_pads_again_before_save_and_busy_clear',
           route=['0x8002d568','0x8002d74c','0x80008b68','0x80002ce8','0x80009840','0x80009930'],
           additional_opens=4,additional_closes=4,total_prefetch_calls=8,
           limitation='Stop bodies, prefetch/conversion, save and UI refresh effects modeled; loader/unloader/file control flow executes stock')

    r=ReloadRig();r.run();r.fail=('close',r.counts['close']+1,'error');r.consume()
    assert r.word(BUSY_WORD)==0 and r.paths()==r.expected
    assert all(r.snapshot(p)[0]==0 for p in range(4))
    passed('second_UI_reload_also_ignores_injected_unload_close_error_and_clears_busy')

    r=ReloadRig();r.submit();r.submit();paused=[]
    def after_first(uc,a,n,u):
        if not paused:
            paused.append(True);r.m.reached_return=True;uc.emu_stop()
    hook=r.m.uc.hook_add(UC_HOOK_CODE,after_first,begin=0x800362b6,end=0x800362b6)
    r.dispatch();assert len(r.callback_returns)==1 and len(r.messages)==1
    r.consume();assert r.word(BUSY_WORD)==0 and len(r.messages)==1
    r.m.uc.hook_del(hook)
    passed('first_reload_UI_completion_clears_busy_while_second_reload_is_still_queued',
           limitation='Worker paused after first return; UI then runs on same fixture with a fresh execution context; paused task is not resumed')

    out=ROOT/'analysis/pad_reload_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Original producer, worker, full reload, catalogue, validator and loader control flow; synthetic files and settings result',
      'Prefetch/conversion and filesystem/RTOS effects remain models; return does not join unknown asynchronous descendants',
      'Actual UI event branch and busy-clear helper execute; UI framework/RTOS scheduling and message delivery are modeled',
      'No installed ticket transport, storage lifetime hook, global exclusion or device change']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
