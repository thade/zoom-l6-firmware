#include "playback_shutdown.h"
#define KEEP __attribute__((used,retain))
static int enter(OdShutdown *s) {
    uint32_t zero=0;
    return __atomic_compare_exchange_n(&s->lock,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(OdShutdown *s,int32_t r) {
    __atomic_store_n(&s->lock,0,__ATOMIC_RELEASE);return r;
}
static int32_t fail(OdShutdown *s) {
    s->phase=SD_FAILED;od_gate_fail(&s->session->ledger->gate);return OWN_FAULT;
}
static int has_fault(OdShutdown *s) {
    return !!(__atomic_load_n(&s->session->ledger->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED);
}
static int32_t control(OdShutdown *s,uint32_t r) {
    return r==OC_OK?OWN_OK:r==OC_BUSY?OWN_BUSY:fail(s);
}
KEEP int32_t od_shutdown_fence(OdShutdown *s,uint32_t owner,uint32_t *ack) {
    OdSession *p=s->session;
    *ack=0;
    if(s->phase!=SD_FENCE || !s->lock || !p->operation || !p->held ||
       !p->closing || p->playing || !owner || owner!=s->owner || owner!=p->owner)return fail(s);
    int32_t r=control(s,oc_drained(s->control,s->epoch));
    if(r)return r;
    /* No admitted session scan can still be running: quiesce owns operation.
     * A queued worker remains allowed to complete, and is joined by the ledger.
     * Do NOT clear pending flags or abandon their tickets. */
    r=s->port->disable_streams();
    if(r)return r==OWN_BUSY?r:fail(s);
    if(!s->requested) {
        r=control(s,oc_audio_request(s->control,s->epoch));
        if(r)return r;
        s->requested=1;
    }
    r=control(s,oc_audio_poll(s->control,s->epoch));
    if(r)return r;
    if(!s->port->quiet())return OWN_BUSY;
    *ack=owner;s->last_fenced=owner;return OWN_OK;
}
KEEP int32_t od_shutdown_poll(OdShutdown *s) {
    if(!enter(s))return OWN_BUSY;
    OdSession *p=s->session;
    int32_t r=OWN_OK;
    if(s->phase==SD_FAILED || has_fault(s))return leave(s,fail(s));
    if(s->phase>=SD_REOPEN)return leave(s,OWN_BUSY);
    if(s->phase==SD_IDLE) {
        r=control(s,oc_close(s->control,&s->epoch));
        if(r)return leave(s,r);
        s->phase=SD_HOLD;
    }
    if(s->phase==SD_HOLD) {
        r=od_session_hold(p);if(r)goto done;
        s->owner=p->owner;s->phase=SD_DRAIN;
    }
    if(s->phase==SD_DRAIN) {
        r=control(s,oc_drained(s->control,s->epoch));if(r)goto done;
        s->phase=SD_STOP;
    }
    if(s->phase==SD_STOP) {
        for(uint32_t pad=0;pad<4;pad++) {r=od_session_stop(p,pad);if(r)goto done;}
        s->phase=SD_FENCE;
    }
    if(s->phase==SD_FENCE) {
        /* Even an initially idle session needs a fresh completion and quiet
         * check. There is no session owner for quiesce to fence in that case. */
        if(!s->owner) {
            r=s->port->disable_streams();if(r)goto done;
            if(!s->requested) {
                r=control(s,oc_audio_request(s->control,s->epoch));if(r)goto done;
                s->requested=1;
            }
        }
        if(s->requested) {
            r=control(s,oc_audio_poll(s->control,s->epoch));if(r)goto done;
        }
        r=od_session_quiesce(p);if(r)goto done;
        if(!s->port->quiet()){r=OWN_BUSY;goto done;}
        s->phase=SD_PROMOTE;
    }
    if(s->phase==SD_PROMOTE) {
        r=control(s,oc_audio_poll(s->control,s->epoch));if(r)goto done;
        if(!s->port->quiet()){r=OWN_BUSY;goto done;}
        r=od_own_promote(p->ledger,&s->promotion);if(r)goto done;
        s->phase=SD_HELD;
    }
    if(s->phase==SD_HELD) {
        r=control(s,oc_audio_poll(s->control,s->epoch));if(r)goto done;
        if(!s->port->quiet())r=fail(s);
    }
done:
    if(r && r!=OWN_BUSY)r=fail(s);
    return leave(s,r);
}
KEEP int32_t od_shutdown_finish(OdShutdown *s,uint32_t ticket,uint32_t failed) {
    if(!enter(s))return OWN_BUSY;
    if(s->phase==SD_FAILED || has_fault(s))return leave(s,fail(s));
    if(!ticket || ticket!=s->promotion || s->phase<SD_HELD || s->phase>SD_UNHOLD)
        return leave(s,OWN_STALE);
    if(failed)return leave(s,fail(s)); /* Retain ownership on uncertain writes. */
    int32_t r;
    if(s->phase==SD_HELD) {
        r=control(s,oc_audio_poll(s->control,s->epoch));if(r)return leave(s,r);
        if(!s->port->quiet())return leave(s,fail(s));
        r=od_own_promote_end(s->session->ledger,ticket,0);
        if(r)return leave(s,r==OWN_BUSY?r:fail(s));
        s->phase=SD_REOPEN;
    }
    if(s->phase==SD_REOPEN) {
        r=control(s,oc_reopen(s->control,s->epoch));if(r)return leave(s,r);
        s->phase=SD_UNHOLD;
    }
    r=od_session_unhold(s->session);
    if(r)return leave(s,r==OWN_BUSY?r:fail(s));
    s->phase=SD_IDLE;s->epoch=s->owner=s->requested=s->promotion=0;
    return leave(s,OWN_OK);
}
KEEP int32_t od_shutdown_rearm(OdShutdown *s,uint32_t old,uint32_t next) {
    /* Called with session operation held, before original restart changes
     * buffers or enables streaming. Original restart supplies the new state. */
    /* Do not inspect shutdown phase here: a start can acquire the session latch
     * just after finish releases its hold, before finish clears its bookkeeping.
     * The session latch orders hold release and this read of last_fenced. */
    if(!old || old!=s->last_fenced || !next || next==old ||
       s->session->owner!=next || s->session->held)return OWN_FAULT;
    return s->port->quiet()?OWN_OK:OWN_FAULT;
}
KEEP const uint32_t od_shutdown_layout[]={sizeof(OdShutdown),sizeof(OdShutdownPort)};
KEEP int32_t od_shutdown_publish_begin(OdShutdown *s,uint32_t *child) {
    *child=0;
    if(!enter(s))return OWN_BUSY;
    if(s->phase==SD_FAILED || has_fault(s))return leave(s,fail(s));
    if(s->phase!=SD_HELD)return leave(s,OWN_BUSY);
    int32_t r=control(s,oc_audio_poll(s->control,s->epoch));
    if(r)return leave(s,r);
    if(!s->session->held || !s->port->quiet())return leave(s,fail(s));
    OwnLedger *l=s->session->ledger;
    OwnRequest request={OWN_CARD,{0,0,0,0}};
    r=od_own_child(l,s->promotion,&request,child);
    if(r)return leave(s,r==OWN_BUSY?r:fail(s));
    /* Conservative on intermediate lock failure: retain the child and fault,
     * rather than claim no admission happened and lose its attribution. */
    if(od_own_offer(l,*child) || od_own_submitted(l,*child,OWN_ACCEPTED) ||
       od_own_claim(l,*child,&request))return leave(s,fail(s));
    return leave(s,OWN_OK);
}
KEEP int32_t od_shutdown_publish_end(OdShutdown *s,uint32_t child,uint32_t failed) {
    if(!enter(s))return OWN_BUSY;
    if(s->phase!=SD_HELD || has_fault(s) || failed || !child)return leave(s,fail(s));
    OwnLedger *l=s->session->ledger;
    if(od_own_complete(l,child) || od_own_producer_done(l,child,0))return leave(s,fail(s));
    return leave(s,OWN_OK);
}
/* Explicit emulator bindings, not recovered stock APIs or allocated device RAM. */
#define SD ((OdShutdown *)0x21003c00)
KEEP int32_t od_emulator_shutdown_fence(uint32_t owner,uint32_t *ack) {
    return od_shutdown_fence(SD,owner,ack);
}
KEEP int32_t od_emulator_shutdown_rearm(uint32_t old,uint32_t next) {
    return od_shutdown_rearm(SD,old,next);
}
KEEP int32_t od_emulator_shutdown_disable_streams(void) {
    for(uint32_t pad=0;pad<4;pad++)*(volatile uint8_t *)(0x80735180+pad*0x44)=0;
    __atomic_thread_fence(__ATOMIC_RELEASE);return OWN_OK;
}
