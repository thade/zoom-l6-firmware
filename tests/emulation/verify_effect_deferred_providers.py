#!/usr/bin/env python3
"""Original effect providers through original deferred-copy consumers, offline.

The host schedules each consumer at its producer's first poll on a separate
emulated stack. No copied bytes or completion-slot values are supplied by Python.
This covers destination arithmetic and ordered delivery, not RTOS timing or
competing producers. No device access or firmware changes.
"""
import hashlib,json
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_effect_memory_providers import effect_case
from verify_pad_protocol import ROOT,IMAGE

class DeferredCopies:
    SITES=((0x8005b740,0x8005b776,0x80445308,0x80445164,4,0x80023e98),
           (0x8005b790,0x8005b7c6,0x80445310,0x804451f0,8,0x80023f30))
    RETURN=0x2103d000
    STACK=0x2103c000
    def __init__(self,r):
        self.r=r;self.pending=None;self.context=None;self.completed=0
        r.m.uc.mem_write(self.RETURN,b'\x00\xbf')
        for entry,poll,slot,buffer,unit,consumer in self.SITES:
            r.m.uc.hook_add(UC_HOOK_CODE,self.start,user_data=(slot,buffer,unit),begin=entry,end=entry)
            r.m.uc.hook_add(UC_HOOK_CODE,self.schedule,user_data=(slot,buffer,unit,consumer),begin=poll,end=poll)
        r.m.uc.hook_add(UC_HOOK_CODE,self.finish,begin=self.RETURN,end=self.RETURN)
    def start(self,u,pc,n,data):
        assert self.pending is None and self.context is None
        assert self.r.word(0x801f5f08)==0,'Expected original deferred mode'
        slot,buffer,unit=data
        destination=u.reg_read(A.UC_ARM_REG_R0);source=u.reg_read(A.UC_ARM_REG_R1)
        size=u.reg_read(A.UC_ARM_REG_R2)
        assert size and size%unit==0 and size<=0x8c
        self.pending=(slot,buffer,unit,destination,self.r.raw(source,size))
    def schedule(self,u,pc,n,data):
        if self.pending is None:return # Resume original zero-count poll.
        slot,buffer,unit,consumer=data
        assert self.context is None
        saved_slot,saved_buffer,saved_unit,destination,payload=self.pending
        assert (slot,buffer,unit)==(saved_slot,saved_buffer,saved_unit)
        assert self.r.word(slot)==destination and self.r.word(slot+4)*unit==len(payload)
        assert self.r.raw(buffer,len(payload))==payload
        self.context=u.context_save()
        u.reg_write(A.UC_ARM_REG_SP,self.STACK)
        u.reg_write(A.UC_ARM_REG_LR,self.RETURN|1)
        u.reg_write(A.UC_ARM_REG_PC,consumer|1)
    def finish(self,u,pc,n,data):
        assert self.context is not None and self.pending is not None
        slot,buffer,unit,destination,payload=self.pending
        assert self.r.raw(destination,len(payload))==payload
        assert self.r.raw(slot,8)==bytes(8)
        u.context_restore(self.context)
        u.reg_write(A.UC_ARM_REG_PC,u.reg_read(A.UC_ARM_REG_PC)|1)
        self.context=None;self.pending=None;self.completed+=1
    def idle(self):
        assert self.pending is None and self.context is None
        assert self.r.raw(0x80445308,16)==bytes(16)

def main():
    cases=[]
    for effect in range(3): # Hall/Room/Spring are the actual generic-copy providers.
        direct=effect_case(effect)
        deferred=effect_case(effect,deferred_service=DeferredCopies)
        assert deferred['deferred_copies']>0
        for field in ('parameter_calls','copy_calls','copy_inputs_sha256','copy_destinations',
                      'output_sha256','output_peak','nonzero_blocks'):
            assert deferred[field]==direct[field],(effect,field,direct[field],deferred[field])
        cases.append(dict(effect=effect,deferred=deferred,direct=direct))
    out=ROOT/'analysis/effect_deferred_providers_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),device_access=False,
        limitations=['Each parameter independently spans its valid range, not every combined state.',
            'All three generic-copy effect providers execute original staging, request and consumer instructions.',
            'Original mode setter selects deferred delivery; host schedules the consumer at the first poll.',
            'Consumer runs on a separate simulated stack; no whole audio callback, physical preemption or timing claim.',
            'No competing producers, DMA/cache/alias proof, device reservation or extra capture.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
