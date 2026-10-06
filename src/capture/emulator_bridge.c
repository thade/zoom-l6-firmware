/* Emulator adapters only. Control producers use a bounded try-lock mailbox;
 * exactly one worker owns Capture/Life. No hook performs file IO or waits.
 * Scheduling/wakeup and the external retirement fence remain unbound. */
#include "capture.h"
#include "exchange.h"
#include <stddef.h>
#include "retention.h"
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define W(a) (*(volatile uint32_t *)(a))
#define B(a) (*(volatile uint8_t *)(a))
typedef struct {uint32_t session,kind;uint64_t stamp;} Packet;
typedef struct {
    Exchange *exchange;void *life;Capture *capture;
    uint32_t session,error,phase,have_start,admitted,have_stop;
    uint64_t start,stop,cursor;
    uint32_t q_lock,q_read,q_write,worker_busy,closed,retired,bound,actors;
    Packet queue[8];
    uint32_t routed;
    void *request_scope,*callback_scope;
    void *transport;
    void *(*context)(void*,uint32_t);
} Bridge;
KEEP Bridge *emulator_bridge_current;
static uint32_t last_session;
/* Permanent gateway: must outlive every session and installed hook. Reserve
 * BEFORE loading any session pointer. Raw binding after close is forbidden;
 * prepared handover alone can reopen at a strict outer callback boundary. */
KEEP uint32_t bridge_gateway_readers;
static Bridge *detached_bridge;
static uint32_t detached_session;
static int gateway_enter(void) {
    uint32_t old=__atomic_fetch_add(&bridge_gateway_readers,1,__ATOMIC_ACQ_REL);
    if(old&0x80000000u) {
        __atomic_fetch_sub(&bridge_gateway_readers,1,__ATOMIC_RELEASE);return 0;
    }
    return 1;
}
static void gateway_leave(void) {
    __atomic_fetch_sub(&bridge_gateway_readers,1,__ATOMIC_RELEASE);
}
/* Opt-in whole-callback adapter. Permanent state, one audio producer required.
 * Nested/overlapping calls suppress taps and cancel optional capture. */
KEEP uint32_t bridge_audio_calls;
static uint32_t audio_mode,audio_overlap,audio_gateway,audio_actor,audio_phase,audio_expected;
static Bridge *audio_bridge;
static Bridge *pending_bridge;
static uint32_t handover_session,handover_state;
static Bridge *adopt_pending(uint32_t callback);
extern uint32_t life_is_prepared(const void*);
static void audio_begin(uint32_t callback),audio_end(void),audio_hook(uint32_t kind);
KEEP uint32_t bridge_audio_enable(void) {
    /* Initialization-only, externally quiescent. */
    if(LD(&bridge_audio_calls) || LD(&bridge_gateway_readers))return 11;
    ST(&audio_mode,1);return 0;
}
/* Cold runtime only, before installing hooks or allowing any caller to enter.
 * This cannot reset a previously bound, detached or staged session. */
KEEP uint32_t bridge_boot_close(void) {
    if(audio_mode || last_session || LD(&emulator_bridge_current) || detached_bridge ||
       LD(&pending_bridge) || LD(&bridge_audio_calls) || LD(&bridge_gateway_readers))return 12;
    ST(&bridge_gateway_readers,0x80000000u);ST(&audio_mode,1);return 0;
}
/* Read-only startup composition check after manager_boot, before worker release.
 * Unlike bridge_audio_enable, this accepts the intentionally closed gateway. */
KEEP uint32_t bridge_audio_boot_ready(void) {
    return LD(&audio_mode) && LD(&bridge_gateway_readers)==0x80000000u &&
           !LD(&bridge_audio_calls) && !LD(&emulator_bridge_current) &&
           !LD(&pending_bridge)?0:11;
}
KEEP const uint32_t bridge_layout[]={sizeof(Bridge),offsetof(Bridge,error),offsetof(Bridge,phase),
    offsetof(Bridge,start),offsetof(Bridge,stop),offsetof(Bridge,cursor)};
KEEP const uint32_t bridge_queue_layout[]={offsetof(Bridge,q_lock),offsetof(Bridge,q_read),
    offsetof(Bridge,q_write),offsetof(Bridge,worker_busy),offsetof(Bridge,closed),
    offsetof(Bridge,retired),offsetof(Bridge,queue),sizeof(Packet),offsetof(Bridge,actors)};
extern uint32_t life_start_quiesced(void*,Capture*),life_stop_quiesced(void*,Capture*);
extern uint32_t life_cancel_quiesced(void*,Capture*),life_step(void*,Capture*);
extern uint32_t life_revoke_quiesced(void*,Capture*);
extern const uint16_t *life_verified_path(const void*);
extern void rr_hook(void*,uint32_t,uint32_t);
static Observation observe(void) {
    Observation o={W(0x20015e2cu),W(0x20015e30u),W(0x20015e10u),B(0x20015e1cu)};
    return o;
}
static void error(Bridge *b,uint32_t why) {
    uint32_t zero=0;
    __atomic_compare_exchange_n(&b->error,&zero,why,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
}
/* High bit closes admission atomically with outstanding hook/publication count.
 * A bounded number of system callers (far below 2^31) is a required contract.
 * Closed arrivals undo their count and do not touch queue or error state. */
static int enter(Bridge *b) {
    uint32_t old=__atomic_fetch_add(&b->actors,1,__ATOMIC_ACQ_REL);
    if(old&0x80000000u){__atomic_fetch_sub(&b->actors,1,__ATOMIC_RELEASE);return 0;}
    return 1;
}
static void leave(Bridge *b) {__atomic_fetch_sub(&b->actors,1,__ATOMIC_RELEASE);}
KEEP uint32_t bridge_bind(Bridge *b,Exchange *p,void *life,Capture *c) {
    /* Caller supplies nonzero unique session in zeroed, unused Bridge. */
    if(!b->session || b->session<=last_session || b->bound || b->phase ||
       b->have_start || b->error || LD(&emulator_bridge_current) ||
       LD(&bridge_gateway_readers) || LD(&bridge_audio_calls))return 12;
    b->exchange=p;b->life=life;b->capture=c;b->bound=1;last_session=b->session;
    ST(&emulator_bridge_current,b);return 0;
}
/* A producer never waits for another producer/consumer. If contention or
 * capacity prevents publication, latch failure out-of-band so no event is
 * silently lost. All queue payload accesses occur under the same gate. */
static uint32_t publish(Bridge *b,uint32_t session,uint32_t kind,const uint64_t *stamp) {
    if(session!=b->session || LD(&b->retired) || LD(&b->closed))return 12;
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&b->q_lock,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
        error(b,20);return 20;
    }
    uint32_t status=0,w=b->q_write;
    if(LD(&b->closed) || LD(&b->retired))status=12;
    else if(w==UINT32_MAX || w-b->q_read>=8){error(b,21);status=21;}
    else {b->queue[w&7]=(Packet){session,kind,*stamp};b->q_write=w+1;}
    ST(&b->q_lock,0);return status;
}
KEEP uint32_t bridge_publish(Bridge *b,uint32_t session,uint32_t kind,const uint64_t *stamp) {
    if(session!=b->session || LD(&b->retired))return 12;
    if(!enter(b))return 12;
    uint32_t status=publish(b,session,kind,stamp);leave(b);return status;
}
/* No IO. 0 outer entry, 1 snapshot, 2 commit, 3 start, 4 stop,
 * 5 registered-stream admission, 6 rejected ordinary request. */
static void hook(Bridge *b,uint32_t kind,uint32_t selected) {
    /* Routed integrations supply owned control events explicitly. Legacy
     * isolated-window fixtures retain the old un-attributed hook mode. */
    if(kind>=3 && LD(&b->routed)) {
        if(b->context) {
            uint32_t irq;__asm__ volatile("mrs %0, ipsr":"=r"(irq));
            if(irq)return;
            ((void(*)(void))0x80073ec9u)();
            void *q=b->context(b->transport,kind);
            if(q)rr_hook(q,kind,selected);
            ((void(*)(void))0x80073f19u)();return;
        }
        void *q=(kind==4 || kind==5)?b->callback_scope:b->request_scope;
        if(q)rr_hook(q,kind,selected);
        return;
    }
    if(LD(&b->error) || LD(&b->closed))return;
    Observation o=observe();uint32_t status=0;uint64_t stamp=0;
    if(kind==0) {
        if(o.callback!=0x2022a791u || o.copy_state==2 ||
           o.capacity!=b->exchange->capacity)error(b,18);
        return;
    }
    if(kind==1)status=exchange_stage(b->exchange,(float*)0x20013e00u,(float*)0x20013f00u,&o);
    else if(kind==2)status=exchange_commit(b->exchange,&o);
    else if(kind==3 || kind==4) {
        Event e={o,selected};status=exchange_resolve(b->exchange,&e,&stamp);
        if(status){error(b,status==11?18:status);return;}
    } else if(kind==5) {
        const uint32_t channels[]={0,1,2,4,6,8,10};
        if(B(0x801f5f00u)!=255 || (W(0x8077ce70u)&0x557u)!=0x557u)status=12;
        for(uint32_t i=0;i<7;i++)if(!W(0x8077e87cu+channels[i]*4))status=12;
    } else if(kind!=6)status=12;
    if(status && !(kind==1 && status==11))error(b,status);
    if(!status && kind>=3)(void)publish(b,b->session,kind,&stamp);
}
KEEP void bridge_hook(uint32_t kind,uint32_t selected) {
    if(kind==10){audio_begin(selected);return;}
    if(kind==11){audio_end();return;}
    if(kind<=2 && LD(&audio_mode)){audio_hook(kind);return;}
    if(!gateway_enter())return;
    Bridge *b=LD(&emulator_bridge_current);
    if(b && enter(b)){hook(b,kind,selected);leave(b);}
    gateway_leave();
}
/* Calls remain counted between the outer, tap, commit and return sites.
 * Unlike each short hook reservation this spans ordinary callback execution. */
static void audio_begin(uint32_t callback) {
    uint32_t old=__atomic_fetch_add(&bridge_audio_calls,1,__ATOMIC_ACQ_REL);
    if(old){ST(&audio_overlap,1);return;}
    audio_phase=0;audio_expected=callback==0x2022a791u;
    audio_gateway=0;audio_actor=0;audio_bridge=0;
    Bridge *b=adopt_pending(callback);
    if(!b) {
        if(!gateway_enter())return;
        b=LD(&emulator_bridge_current);
    }
    audio_gateway=1;
    if(!b || !enter(b))return;
    audio_actor=1;audio_bridge=b;
    if(!audio_expected)error(b,18);
    hook(b,0,callback);
}
static void audio_hook(uint32_t kind) {
    /* No bare tap may attach itself to whatever session happens to be current.
     * Detached/closed arrivals touch only permanent counters. */
    if(LD(&bridge_audio_calls)!=1 || LD(&audio_overlap) || !audio_bridge) return;
    Bridge *b=audio_bridge;
    if((kind==1 && audio_phase!=0) || (kind==2 && audio_phase!=1) || kind==0) {
        error(b,32);return;
    }
    hook(b,kind,0);audio_phase=kind;
}
static void audio_end(void) {
    uint32_t old=__atomic_fetch_sub(&bridge_audio_calls,1,__ATOMIC_ACQ_REL);
    if(!old){__atomic_fetch_add(&bridge_audio_calls,1,__ATOMIC_RELEASE);return;}
    if(old!=1)return;
    /* Single-producer/LIFO contract: no new outer entry until this return hook
     * finishes. This is NOT an arbitrary multi-core admission gate. */
    Bridge *b=audio_bridge;
    if(b) {
        if(LD(&audio_overlap))error(b,31);
        else if(audio_expected && audio_phase!=2)error(b,32);
        if(audio_actor)leave(b);
    }
    audio_bridge=0;audio_actor=0;ST(&audio_overlap,0);
    if(audio_gateway){audio_gateway=0;gateway_leave();}
}
/* Worker owns event-derived fields. Drain at most the fixed mailbox capacity;
 * a contended gate causes WAIT before any audio/IO work in this step. */
static uint32_t events(Bridge *b) {
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&b->q_lock,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
    uint32_t status=0;
    for(uint32_t i=0;i<8 && b->q_read!=b->q_write;i++) {
        Packet p=b->queue[b->q_read&7];b->q_read++;
        if(p.session!=b->session){status=12;break;}
        if(p.kind==3) {
            if(b->have_start || b->phase){status=12;break;}
            b->start=p.stamp;b->have_start=1;
        } else if(p.kind==5) {
            if(!b->have_start || b->admitted){status=12;break;}
            b->admitted=1;
        } else if(p.kind==4) {
            if(!b->admitted || b->have_stop || p.stamp<=b->start || b->phase>=2){status=12;break;}
            b->stop=p.stamp;b->have_stop=1;
        } else {status=p.kind==6?16:12;break;}
    }
    ST(&b->q_lock,0);
    if(status)error(b,status);
    return status;
}
static uint32_t cancel(Bridge *b,uint32_t why) {
    error(b,why);extra_invalidate_quiesced(b->capture);
    if(life_verified_path(b->life))(void)life_revoke_quiesced(b->life,b->capture);
    else (void)life_cancel_quiesced(b->life,b->capture);
    __atomic_fetch_or(&b->actors,0x80000000u,__ATOMIC_ACQ_REL);
    ST(&b->closed,1);ST(&b->phase,4);return LD(&b->error);
}
static uint32_t step(Bridge *b) {
    if(b->phase==4)return LD(&b->error);
    uint32_t fault=LD(&b->error);if(fault)return cancel(b,fault);
    if(b->phase==3)return 0;
    uint32_t delivered=events(b);
    if(delivered==11)return 11;
    if(delivered)return cancel(b,delivered);
    if(LD(&b->error))return cancel(b,LD(&b->error));
    if(LD(&b->exchange->pub_fault))return cancel(b,18);
    if(b->phase==0) {
        if(!b->admitted)return 11;
        if(life_start_quiesced(b->life,b->capture))return cancel(b,12);
        b->capture->range_pending=1;b->cursor=b->start;ST(&b->phase,1);
    }
    if(b->phase==2) {
        uint32_t s=life_step(b->life,b->capture);
        if(LD(&b->error))return cancel(b,LD(&b->error));
        if(s==0) {
            /* Serialize final eligibility with producers. Queued late events
             * must still be consumed; closure cannot discard them silently. */
            uint32_t active=__atomic_fetch_or(&b->actors,0x80000000u,__ATOMIC_ACQ_REL);
            if(active&0x7fffffffu)return 11;
            uint32_t zero=0;
            if(!__atomic_compare_exchange_n(&b->q_lock,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
            if(b->q_read!=b->q_write){ST(&b->q_lock,0);return 10;}
            ST(&b->closed,1);ST(&b->q_lock,0);
            if(LD(&b->error))return cancel(b,LD(&b->error));
            ST(&b->phase,3);
        }
        else if(s!=10)return cancel(b,s);
        return s;
    }
    if(b->have_stop && b->cursor>b->stop)return cancel(b,12);
    if(b->have_stop && b->cursor==b->stop) {
        b->capture->range_pending=0;
        if(life_stop_quiesced(b->life,b->capture))return cancel(b,12);
        ST(&b->phase,2);return 10;
    }
    uint64_t first=b->cursor&~(uint64_t)63;Slot *s=0;
    uint32_t result=exchange_claim(b->exchange,&first,&s);
    if(result==11)return 11;
    if(result)return cancel(b,result);
    uint32_t offset=(uint32_t)(b->cursor-first),n=64-offset;
    if(b->have_stop && b->stop-b->cursor<n)n=(uint32_t)(b->stop-b->cursor);
    result=extra_capture_frames(b->capture,s->left+offset,s->right+offset,n);
    uint32_t released=exchange_release(b->exchange,&first);
    if(result || released)return cancel(b,result?result:released);
    b->cursor+=n;
    if(LD(&b->error))return cancel(b,LD(&b->error));
    /* Only this worker fills/drains staging. Retention belongs to Exchange;
     * accumulate a batch here instead of issuing a 512-byte write per step.
     * The lifecycle drains any partial batch after the exact stop boundary. */
    if(b->capture->write-b->capture->read==EXTRA_SLOTS) {
        result=extra_drain(b->capture);
        if(result!=0 && result!=1)return cancel(b,result);
    }
    return 10;
}
KEEP uint32_t bridge_step(Bridge *b,uint32_t session) {
    if(!gateway_enter())return 12;
    /* Pointer comparison precedes dereference, including stale worker calls. */
    if(!b || b!=LD(&emulator_bridge_current) || !session || session!=b->session || LD(&b->retired)) {
        gateway_leave();return 12;
    }
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&b->worker_busy,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
        gateway_leave();return 11;
    }
    uint32_t status=step(b);ST(&b->worker_busy,0);gateway_leave();return status;
}
/* Single manager only, with stable session storage and control ownership
 * already drained. This fences ONLY gateway hooks/workers, not direct router
 * APIs, Transport wrappers, path readers or arbitrary external pointers. */
KEEP uint32_t bridge_detach(Bridge *b,uint32_t session) {
    if(b==detached_bridge && session && session==detached_session)return 0;
    if(!b || b!=LD(&emulator_bridge_current) || session!=b->session)return 12;
    uint32_t phase=LD(&b->phase);
    if(phase!=3 && phase!=4)return 11; /* Keep worker able to finish/cancel. */
    __atomic_fetch_or(&bridge_gateway_readers,0x80000000u,__ATOMIC_ACQ_REL);
    if(LD(&bridge_gateway_readers)&0x7fffffffu)return 11;
    if(LD(&b->worker_busy) || LD(&b->q_lock) || (LD(&b->actors)&0x7fffffffu))return 11;
    for(uint32_t i=0;i<=b->exchange->mask;i++)
        if(LD(&b->exchange->slots[i].state)==3)return 11;
    ST(&b->closed,1);ST(&b->retired,1);
    ST(&emulator_bridge_current,(Bridge*)0);
    detached_bridge=b;detached_session=session;return 0;
}
/* NOT a fence implementation: caller must first prevent ALL old hooks/events
 * (including stock queued callbacks) and await in-flight accesses. Retired
 * storage cannot be reclaimed until that external quiescence is established. */
KEEP uint32_t bridge_retire_quiesced(Bridge *b,uint32_t session) {
    if(session!=b->session || LD(&emulator_bridge_current)!=b ||
       LD(&b->worker_busy) || LD(&b->q_lock) || (LD(&b->actors)&0x7fffffffu) ||
       (b->phase!=3 && b->phase!=4))return 11;
    for(uint32_t i=0;i<=b->exchange->mask;i++)
        if(LD(&b->exchange->slots[i].state)==3)return 11;
    ST(&b->closed,1);ST(&b->retired,1);ST(&emulator_bridge_current,(Bridge*)0);return 0;
}
KEEP const uint16_t *bridge_verified_path(Bridge *b,uint32_t session) {
    if(session!=b->session || LD(&b->phase)!=3 || LD(&b->error) || LD(&b->retired))return 0;
    return life_verified_path(b->life);
}
/* Request router ports. Binding is externally quiescent, before requests.
 * Each request holds a reservation through queue delivery AND send outcome. */
KEEP uint32_t bridge_route_enable(Bridge *b,uint32_t session) {
    if(session!=b->session || b->phase || b->q_write || b->routed)return 12;
    ST(&b->routed,1);return 0;
}
/* Explicit adapter scopes, NOT task-local storage. The emulator serializes
 * scope installation/removal and execution within each scope. Real concurrent
 * task binding must replace this with attributable per-task/per-message context. */
KEEP uint32_t bridge_route_scope(Bridge *b,void *q,uint32_t callback) {
    void **slot=callback?&b->callback_scope:&b->request_scope;
    if(q && *slot)return 11;
    *slot=q;return 0;
}
KEEP uint32_t bridge_route_context(Bridge *b,void *transport,void *(*lookup)(void*,uint32_t)) {
    if(!b->routed || b->context || b->request_scope || b->callback_scope)return 12;
    b->transport=transport;b->context=lookup;return 0;
}
KEEP uint32_t bridge_route_hold(Bridge *b,uint32_t session) {
    if(session!=b->session || LD(&b->retired) || !b->routed)return 12;
    return enter(b)?0:12;
}
KEEP void bridge_route_release(Bridge *b) {leave(b);}
KEEP uint32_t bridge_route_snapshot(Bridge *b,uint32_t session,uint32_t selected,uint64_t *stamp) {
    if(session!=b->session || LD(&b->retired))return 12;
    Observation o=observe();Event e={o,selected};
    uint32_t s=exchange_resolve(b->exchange,&e,stamp);return s==11?18:s;
}
KEEP uint32_t bridge_route_event(Bridge *b,uint32_t session,uint32_t kind,const uint64_t *stamp) {
    /* Caller already holds a request reservation; do not reacquire after the
     * worker closes admission while waiting for that request to complete. */
    return publish(b,session,kind,stamp);
}
KEEP void bridge_route_fault(Bridge *b,uint32_t session,uint32_t why) {
    if(session==b->session && !LD(&b->retired))error(b,why);
}
KEEP uint32_t bridge_route_admit(Bridge *b,uint32_t session) {
    uint64_t zero=0;const uint32_t channels[]={0,1,2,4,6,8,10};
    if(B(0x801f5f00u)!=255 || (W(0x8077ce70u)&0x557u)!=0x557u)return 12;
    for(uint32_t i=0;i<7;i++)if(!W(0x8077e87cu+channels[i]*4))return 12;
    return publish(b,session,5,&zero);
}

/* Manager-only unlink, after the permanent hook/worker gateway detached. */
KEEP uint32_t bridge_unroute_detached(Bridge *b,uint32_t session) {
    if(!b || b!=detached_bridge || session!=detached_session ||
       LD(&bridge_gateway_readers)!=0x80000000u)return 11;
    b->context=0;b->transport=0;b->request_scope=0;b->callback_scope=0;return 0;
}

/* Single-manager staging while both old gateways are closed. Caller owns fresh
 * zeroed objects and an already prepared file. Publication occurs only at the
 * next outer callback; no file IO occurs on that audio path. */
KEEP uint32_t bridge_prepare_next(Bridge *b,Exchange *p,void *life,Capture *c,uint32_t session) {
    if(!LD(&audio_mode) || LD(&emulator_bridge_current) || LD(&pending_bridge) ||
       !(LD(&bridge_gateway_readers)&0x80000000u) || !session || session<=last_session ||
       b->bound || b->session || b->phase || b->error || !life_is_prepared(life))return 12;
    b->session=session;b->exchange=p;b->life=life;b->capture=c;b->bound=1;return 0;
}
KEEP uint32_t bridge_queue_next(Bridge *b,Slot *slots,uint32_t count) {
    if(!slots || count<2 || count>EXCHANGE_MAX_SLOTS || (count&(count-1)) || !b->bound || !b->context ||
       !b->routed || b->session<=last_session || LD(&pending_bridge))return 12;
    /* Worker owns the fenced storage. Finish all slot-count-dependent work
     * before publishing the pointer that the audio callback can adopt. */
    uint32_t status=exchange_prepare(b->exchange,slots,count);if(status)return status;
    handover_session=b->session;
    last_session=b->session;ST(&handover_state,1);ST(&pending_bridge,b);return 0;
}
static Bridge *adopt_pending(uint32_t callback) {
    Bridge *b=LD(&pending_bridge);if(!b)return 0;
    /* Single audio producer owns this callback boundary. CAS reserves one
     * gateway count while still closed. Closed arrivals may increment/decrement
     * around us; clearing only the closed bit preserves all such counts. */
    uint32_t expected=0x80000000u;
    if(!__atomic_compare_exchange_n(&bridge_gateway_readers,&expected,0x80000001u,
                                    0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 0;
    /* A manager may have withdrawn this stage after our first pointer load. */
    if(b!=LD(&pending_bridge)){gateway_leave();return 0;}
    Observation o=observe();
    if(callback!=0x2022a791u || exchange_begin(b->exchange,&o)) {
        ST(&pending_bridge,(Bridge*)0);ST(&handover_state,18);gateway_leave();return 0;
    }
    ST(&emulator_bridge_current,b);ST(&pending_bridge,(Bridge*)0);
    __atomic_fetch_and(&bridge_gateway_readers,0x7fffffffu,__ATOMIC_RELEASE);
    ST(&handover_state,2);return b; /* caller owns the reserved gateway count */
}
KEEP uint32_t bridge_handover_ready(Bridge *b,uint32_t session) {
    if(session!=handover_session)return 12;
    uint32_t state=LD(&handover_state);
    if(state!=2)return state==1?11:state;
    if(b!=LD(&emulator_bridge_current) || b->session!=session)return 12;
    if(LD(&bridge_audio_calls) || LD(&bridge_gateway_readers))return 11;
    if(LD(&b->error) || LD(&b->exchange->pub_fault))return 18;
    return b->exchange->next>=64 && !b->exchange->pending?0:11;
}
/* Worker/manager cleanup after failed adoption; wait for the failed audio
 * invocation to return before touching its prepared file. No retry in audio. */
extern uint32_t life_resources_released(const void*);
KEEP uint32_t bridge_cancel_failed_stage(Bridge *b,uint32_t session) {
    if(session!=handover_session || b->session!=session || LD(&pending_bridge) ||
       LD(&bridge_audio_calls))return 11;
    if(LD(&handover_state)==2 && LD(&emulator_bridge_current)==b) {
        if(!LD(&b->error) && !LD(&b->exchange->pub_fault))return 12;
        /* Adopted but failed before control activation: only worker does IO. */
        uint32_t s=bridge_step(b,session);
        if(s==10 || s==11)return 11;
        s=bridge_detach(b,session);if(s)return s;
        ST(&handover_state,18);
        return life_resources_released(b->life)?0:13;
    }
    if(LD(&handover_state)!=18 || LD(&emulator_bridge_current) ||
       LD(&bridge_gateway_readers)!=0x80000000u)return 11;
    uint32_t s=life_cancel_quiesced(b->life,b->capture);
    return s==16 && life_resources_released(b->life)?0:s;
}

/* Manager/worker observations; it is the sole caller of bridge_step. */
KEEP uint32_t bridge_manager_flags(Bridge *b) {
    return (b->have_stop?1u:0u) | (LD(&b->phase)==3?2u:0u) |
           (LD(&b->error)?4u:0u) | (LD(&b->retired)?8u:0u);
}
KEEP uint32_t bridge_manager_matches(Bridge *b,uint32_t session) {
    return LD(&audio_mode) && b==LD(&emulator_bridge_current) &&
           b->session==session && !b->phase && !LD(&b->retired);
}
/* Abort a queued or adopted stage without waiting for an absent audio callback.
 * Manager and audio adopter compete for the same closed-gateway reservation. */
KEEP uint32_t bridge_abort_stage(Bridge *b,uint32_t session) {
    if(session!=handover_session || b->session!=session)return 12;
    if(LD(&emulator_bridge_current)==b) {
        error(b,16);uint32_t s=bridge_step(b,session);
        if(s==10 || s==11)return 11;
        s=bridge_detach(b,session);if(s)return s;
        ST(&handover_state,16);return life_resources_released(b->life)?0:13;
    }
    if(LD(&pending_bridge)==b) {
        uint32_t expected=0x80000000u;
        if(!__atomic_compare_exchange_n(&bridge_gateway_readers,&expected,0x80000001u,
                                        0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
        if(LD(&pending_bridge)!=b){gateway_leave();return 11;}
        ST(&pending_bridge,(Bridge*)0);ST(&handover_state,16);gateway_leave();return 11;
    }
    uint32_t state=LD(&handover_state);
    if((state!=16 && state!=18) || LD(&emulator_bridge_current) ||
       LD(&bridge_gateway_readers)!=0x80000000u || LD(&bridge_audio_calls))return 11;
    if(life_resources_released(b->life))return 0;
    (void)life_cancel_quiesced(b->life,b->capture);
    return life_resources_released(b->life)?0:13;
}
KEEP uint32_t bridge_manager_error(Bridge *b) {return LD(&b->error);}
