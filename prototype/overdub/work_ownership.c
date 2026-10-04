#include "work_ownership.h"
#define KEEP __attribute__((used, retain))
static int lock(OwnLedger *l) {
    uint32_t zero=0;
    return __atomic_compare_exchange_n(&l->lock,&zero,1,0,
                                      __ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t unlock(OwnLedger *l,int32_t result) {
    __atomic_store_n(&l->lock,0,__ATOMIC_RELEASE);return result;
}
static OwnEntry *find(OwnLedger *l,uint32_t ticket) {
    if (!ticket) return 0;
    for (uint32_t i=0;i<OD_OWNER_SLOTS;i++)
        if (l->entries[i].ticket==ticket) return &l->entries[i];
    return 0;
}
static int32_t fault(OwnLedger *l) { od_gate_fail(&l->gate);return OWN_FAULT; }
static int equal(const OwnRequest *a,const OwnRequest *b) {
    if (a->kind!=b->kind) return 0;
    for (uint32_t i=0;i<4;i++) if (a->args[i]!=b->args[i]) return 0;
    return 1;
}
static int ready(const OwnEntry *e) {
    return !e->children && e->producer_done && e->submission &&
           (e->phase==OWN_DONE || e->phase==OWN_REJECTED);
}
/* May retire a parent which finished earlier while waiting for its children. */
static int32_t reap(OwnLedger *l,OwnEntry *e) {
    while (ready(e)) {
        OwnEntry *parent=0;
        if (e->parent) {
            parent=find(l,e->parent);
            if (!parent || !parent->children) return fault(l);
            parent->children--;
        }
        e->ticket=0;
        if (!parent) {
            if (od_gate_work_end(&l->gate)) return fault(l);
            return OWN_OK;
        }
        e=parent;
    }
    return OWN_OK;
}
static int32_t reserve(OwnLedger *l,uint32_t parent_ticket,
                       const OwnRequest *r,uint32_t *out,int promotion) {
    *out=0;
    if (!lock(l)) return OWN_BUSY;
    if (__atomic_load_n(&l->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)
        return unlock(l,OWN_FAULT);
    if (!promotion && !((r->kind>=OWN_STREAM && r->kind<=OWN_CARD) || r->kind==OWN_SCAN || r->kind==OWN_SESSION))
        return unlock(l,OWN_CONFLICT);
    OwnEntry *parent=0,*e=0;
    if (parent_ticket) {
        parent=find(l,parent_ticket);
        if (!parent) return unlock(l,OWN_STALE);
        if (parent->phase!=OWN_RUNNING && parent->phase!=OWN_EXCLUSIVE)
            return unlock(l,OWN_CONFLICT);
    }
    for (uint32_t i=0;i<OD_OWNER_SLOTS;i++)
        if (!l->entries[i].ticket) {e=&l->entries[i];break;}
    if (!e) return unlock(l,OWN_FULL);
    if (l->sequence==UINT32_MAX) return unlock(l,fault(l));
    if (!parent) {
        int32_t result=promotion ? od_gate_promote_begin(&l->gate) : od_gate_work_begin(&l->gate);
        if (result) return unlock(l,result==OD_GATE_FAULT?OWN_FAULT:OWN_BUSY);
    }
    e->parent=parent_ticket;e->children=0;e->submission=0;
    e->producer_done=0;e->wait_failed=0;
    e->phase=promotion?OWN_EXCLUSIVE:OWN_PREPARED;
    e->request.kind=promotion?OWN_PROMOTION:r->kind;
    for (uint32_t i=0;i<4;i++) e->request.args[i]=promotion?0:r->args[i];
    e->ticket=++l->sequence;
    if (parent) parent->children++;
    *out=e->ticket;
    return unlock(l,OWN_OK);
}
KEEP int32_t od_own_reserve(OwnLedger *l,const OwnRequest *r,uint32_t *out) {
    return reserve(l,0,r,out,0);
}
KEEP int32_t od_own_child(OwnLedger *l,uint32_t parent,const OwnRequest *r,uint32_t *out) {
    if (!parent) {*out=0;return OWN_STALE;}
    return reserve(l,parent,r,out,0);
}
KEEP int32_t od_own_promote(OwnLedger *l,uint32_t *out) {return reserve(l,0,0,out,1);}
KEEP int32_t od_own_exclusive_drained(OwnLedger *l,uint32_t ticket) {
    if(!lock(l))return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if(!e)return unlock(l,OWN_STALE);
    if(e->phase!=OWN_EXCLUSIVE)return unlock(l,OWN_CONFLICT);
    if(__atomic_load_n(&l->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)return unlock(l,OWN_FAULT);
    return unlock(l,e->children?OWN_BUSY:OWN_OK);
}
KEEP int32_t od_own_promote_end(OwnLedger *l,uint32_t ticket,uint32_t failed) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (e->phase!=OWN_EXCLUSIVE) return unlock(l,OWN_CONFLICT);
    if (e->children) return unlock(l,OWN_BUSY);
    if (failed) od_gate_fail(&l->gate);
    e->ticket=0;
    return unlock(l,od_gate_promote_end(&l->gate,failed)?fault(l):OWN_OK);
}
KEEP int32_t od_own_offer(OwnLedger *l,uint32_t ticket) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (e->phase!=OWN_PREPARED) return unlock(l,OWN_CONFLICT);
    if (__atomic_load_n(&l->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)
        return unlock(l,OWN_FAULT);
    e->phase=OWN_OFFERED;
    return unlock(l,OWN_OK);
}
KEEP int32_t od_own_submitted(OwnLedger *l,uint32_t ticket,uint32_t outcome) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (outcome<OWN_ACCEPTED || outcome>OWN_UNCERTAIN || e->submission ||
        e->phase<OWN_OFFERED || e->phase>OWN_DONE) return unlock(l,OWN_CONFLICT);
    if (outcome==OWN_NOT_SENT) {
        /* A caller claiming definite rejection after a worker claimed the job
         * has contradictory evidence. Keep ownership and latch a fault. */
        if (e->phase!=OWN_OFFERED) return unlock(l,fault(l));
        e->phase=OWN_REJECTED;
    } else if (e->phase==OWN_OFFERED && outcome==OWN_ACCEPTED) e->phase=OWN_QUEUED;
    e->submission=outcome;
    return unlock(l,reap(l,e));
}
KEEP int32_t od_own_producer_done(OwnLedger *l,uint32_t ticket,uint32_t wait_failed) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (!e->submission || e->producer_done) return unlock(l,OWN_CONFLICT);
    e->producer_done=1;e->wait_failed=!!wait_failed;
    return unlock(l,reap(l,e));
}
KEEP int32_t od_own_claim(OwnLedger *l,uint32_t ticket,const OwnRequest *r) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (!equal(&e->request,r)) return unlock(l,fault(l));
    if (e->phase!=OWN_OFFERED && e->phase!=OWN_QUEUED) return unlock(l,OWN_CONFLICT);
    if (__atomic_load_n(&l->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)
        return unlock(l,OWN_FAULT);
    e->phase=OWN_RUNNING;
    return unlock(l,OWN_OK);
}
KEEP int32_t od_own_complete(OwnLedger *l,uint32_t ticket) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (e->phase!=OWN_RUNNING) return unlock(l,OWN_CONFLICT);
    e->phase=OWN_DONE;
    return unlock(l,reap(l,e));
}
KEEP int32_t od_own_cancel_prepared(OwnLedger *l,uint32_t ticket) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (e->phase!=OWN_PREPARED) return unlock(l,OWN_CONFLICT);
    e->phase=OWN_REJECTED;e->submission=OWN_NOT_SENT;e->producer_done=1;
    return unlock(l,reap(l,e));
}
KEEP const uint32_t od_owner_layout[]={sizeof(OwnLedger),sizeof(OwnEntry),sizeof(OwnRequest)};

KEEP int32_t od_own_session_drained(OwnLedger *l,uint32_t ticket) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (e->request.kind!=OWN_SESSION || (e->phase!=OWN_RUNNING && e->phase!=OWN_SEALED) ||
        e->submission!=OWN_ACCEPTED || e->producer_done)
        return unlock(l,OWN_CONFLICT);
    if (__atomic_load_n(&l->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)
        return unlock(l,OWN_FAULT);
    return unlock(l,e->children?OWN_BUSY:OWN_OK);
}

KEEP int32_t od_own_seal_session(OwnLedger *l,uint32_t ticket) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (e->request.kind!=OWN_SESSION || e->phase!=OWN_RUNNING ||
        e->submission!=OWN_ACCEPTED || e->producer_done) return unlock(l,OWN_CONFLICT);
    if (__atomic_load_n(&l->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED) return unlock(l,OWN_FAULT);
    if (e->children) return unlock(l,OWN_BUSY);
    e->phase=OWN_SEALED;return unlock(l,OWN_OK);
}

KEEP int32_t od_own_finish_session(OwnLedger *l,uint32_t ticket) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (e->request.kind!=OWN_SESSION || (e->phase!=OWN_RUNNING && e->phase!=OWN_SEALED) ||
        e->submission!=OWN_ACCEPTED || e->producer_done)
        return unlock(l,OWN_CONFLICT);
    if (__atomic_load_n(&l->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)
        return unlock(l,OWN_FAULT);
    if (e->children) return unlock(l,OWN_BUSY);
    e->phase=OWN_DONE;e->producer_done=1;
    return unlock(l,reap(l,e));
}

#define STREAM_MESSAGE UINT32_C(0x4f445331)
KEEP int32_t od_own_stream_message(OwnLedger *l,uint32_t ticket,uint32_t words[4]) {
    if (!lock(l)) return OWN_BUSY;
    OwnEntry *e=find(l,ticket);
    if (!e) return unlock(l,OWN_STALE);
    if (e->request.kind!=OWN_STREAM || e->phase!=OWN_OFFERED)
        return unlock(l,OWN_CONFLICT);
    words[0]=ticket;words[1]=STREAM_MESSAGE;words[2]=0;words[3]=0;
    return unlock(l,OWN_OK);
}
KEEP int32_t od_own_stream_decode(OwnLedger *l,const uint32_t words[4],uint32_t args[4],uint32_t *ticket) {
    *ticket=0;
    if (!lock(l)) return OWN_BUSY;
    if (words[1]!=STREAM_MESSAGE || words[2] || words[3]) return unlock(l,fault(l));
    OwnEntry *e=find(l,words[0]);
    if (!e) return unlock(l,OWN_STALE);
    if (e->request.kind!=OWN_STREAM || (e->phase!=OWN_OFFERED && e->phase!=OWN_QUEUED))
        return unlock(l,OWN_CONFLICT);
    for (uint32_t i=0;i<4;i++) args[i]=e->request.args[i];
    *ticket=e->ticket;
    return unlock(l,OWN_OK);
}

/* Emulator-only replacement of worker BL 0x80036c70. Queue transport remains
 * modeled; the stock receive wrapper is intercepted by the test fixture. */
KEEP int32_t od_emulator_owned_receive(uint32_t queue,uint32_t *args) {
    int32_t result=((int32_t (*)(uint32_t,uint32_t *))0x800483a9)(queue,args);
    if (result) return result;
    OwnLedger *l=(OwnLedger *)0x21020000;
    result=od_own_stream_decode(l,args,args,(uint32_t *)0x21003810);
    if (!result) return 0;
    od_gate_fail(&l->gate);
    *(volatile int32_t *)0x21003814=result;
    return -1;
}

/* Worker-local CURRENT_TICKET is set by the modeled envelope decoder before
 * original worker BL 0x80036c7c is redirected here. Not a device RAM allocation.
 * A real queue must carry this ticket: pad number or payload alone cannot
 * distinguish an old request from a newer identical one. */
KEEP void od_emulator_owned_stream(uint32_t pad,uint32_t frames,uint32_t span,uint32_t position) {
    OwnLedger *l=(OwnLedger *)0x21020000;
    uint32_t ticket=*(volatile uint32_t *)0x21003810;
    OwnRequest r={OWN_STREAM,{pad,frames,span,position}};
    int32_t status=od_own_claim(l,ticket,&r);
    if (!status) {
        ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t))0x800369a9)(pad,frames,span,position);
        status=od_own_complete(l,ticket);
    }
    /* A consumed message that cannot be attributed/completed is not discarded
     * and treated as idle. Fail closed; a real dispatcher needs retry/recovery. */
    if (status) od_gate_fail(&l->gate);
    *(volatile int32_t *)0x21003814=status;
}
