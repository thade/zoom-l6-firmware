/* Offline fixed-capacity queue transport experiment. No queued-slot reuse,
 * dynamic allocation or automatic rearm. Storage must survive every possible
 * queued reference. Initialization/teardown require external quiescence. */
#include "request_router.h"
#include "exchange.h"
#include <stddef.h>
#include "retention.h"
#define ENTER() ((void(*)(void))0x80073ec9u)()
#define EXIT() ((void(*)(void))0x80073f19u)()
typedef struct {uint32_t task;Request *request,*callback;} Task;
typedef struct {uint32_t words[8];Request *request;uint32_t id,claimed,done,sent;} Job;
typedef struct {Request request;uint32_t busy;} EntrySlot;
typedef struct {Router *router;uint32_t session,queue,used,error;Task tasks[8];Job jobs[8];EntrySlot entries[16];
    uint32_t closing,cutoff,barrier_tx,barrier_seen,drain_error,drain_worker;
} Transport;
typedef struct {Transport *transport;Task *task;Request *previous;EntrySlot *slot;uint32_t identity;} Entry;
KEEP Transport *ct_active;
#define active ct_active
/* Permanent entry ownership; never stored in reclaimable Transport. */
KEEP uint32_t ct_gateway_readers;
static Transport *detached_transport;
static uint32_t detached_session;
static int gateway_enter(void) {
    uint32_t old=__atomic_fetch_add(&ct_gateway_readers,1,__ATOMIC_ACQ_REL);
    if(old&0x80000000u) {
        __atomic_fetch_sub(&ct_gateway_readers,1,__ATOMIC_RELEASE);return 0;
    }
    return 1;
}
static void gateway_leave(void) {
    __atomic_fetch_sub(&ct_gateway_readers,1,__ATOMIC_RELEASE);
}
KEEP const uint32_t ct_layout[]={sizeof(Transport),sizeof(Job),offsetof(Transport,jobs),offsetof(Transport,error)};
KEEP const uint32_t ct_auto_layout[]={sizeof(EntrySlot),offsetof(Transport,entries),16};
KEEP const uint32_t ct_drain_layout[]={offsetof(Transport,closing),offsetof(Transport,cutoff),
    offsetof(Transport,barrier_tx),offsetof(Transport,barrier_seen),offsetof(Transport,drain_error)};
extern uint32_t bridge_route_context(void*,void*,void*(*)(void*,uint32_t));
extern void bridge_route_fault(void*,uint32_t,uint32_t),bridge_hook(uint32_t,uint32_t);
void ct_dispatch(uint32_t*),ct_drain_marker(uint32_t*);
uint32_t ct_drain_poll(Transport*,uint32_t);
extern uint32_t ct_stock_send(uint32_t,const uint32_t*);
extern uint32_t ct_stock_record_request(uint32_t),ct_stock_stop_request(void),ct_stock_play_request(void);
extern uint32_t ct_stock_stop_argument(uint32_t),ct_stock_stop_other(void);
static uint32_t current(void) {
    uint32_t irq;__asm__ volatile("mrs %0, ipsr":"=r"(irq));
    return irq?0:((uint32_t(*)(void))0x800770e9u)();
}
static Task *task(Transport *t,uint32_t id,uint32_t create) {
    Task *empty=0;if(!id)return 0;
    for(uint32_t i=0;i<8;i++) {
        if(t->tasks[i].task==id)return &t->tasks[i];
        if(!t->tasks[i].task && !empty)empty=&t->tasks[i];
    }
    if(create && empty){empty->task=id;return empty;}return 0;
}
static void fault(Transport *t,uint32_t code) {
    if(!t->error)t->error=code;
    bridge_route_fault(t->router->bridge,t->session,code);
}
static void *lookup(void *opaque,uint32_t kind) {
    Transport *t=opaque;Task *p=task(t,current(),0);
    /* Common send wrapper owns the result; old per-producer result hooks do not. */
    if(kind==9)return 0;
    if((kind==4 || kind==5) && (!p || !p->callback) && !t->closing) {
        fault(t,27);return 0; /* late unowned stock callback: cancel extra only */
    }
    if(!p)return 0;
    return kind==4 || kind==5?p->callback:p->request;
}
KEEP uint32_t ct_init(Transport *t,Router *r,uint32_t queue) {
    if(__atomic_load_n(&ct_gateway_readers,__ATOMIC_ACQUIRE) || active || t->router || !queue)return 12;
    uint32_t s=bridge_route_context(r->bridge,t,lookup);if(s)return s;
    t->router=r;t->session=r->session;t->queue=queue;active=t;return 0;
}
/* Explicit binding API retained for lower-level fixtures. Automatic entry
 * wrappers below use original task identity and their own stack scope cookie. */
static uint32_t body_ct_scope(Transport *t,Request *q) {
    uint32_t id=current();if(!t || !id || t!=active)return 12;
    ENTER();Task *p=task(t,id,1);uint32_t s=0;
    if(!p)s=26;
    else if(q && (p->request || q->router!=t->router || q->session!=t->session || !q->held ||
                 (t->closing && q->id>t->cutoff)))s=12;
    else p->request=q;
    EXIT();return s;
}
/* Entry/exit adapters must use these guarded router operations, not call the
 * externally serialized rr_* interface directly from concurrent tasks. */
static uint32_t body_ct_request_op(Transport *t,Request *q,uint32_t op) {
    if(!t || t!=active || !current() || op>2)return 12;
    ENTER();uint32_t s=op==0?(t->closing?12:rr_begin(t->router,q)):
        op==1?rr_finish_request(t->router,q):rr_ignore(t->router,q);
    EXIT();return s;
}
/* Automatic wrappers keep their scope cookie on the calling task's stack.
 * Only never-submitted ignored Requests may be recycled. Queued identities and
 * all Job storage stay allocated until a separately proven session fence. */
static void entry_begin(Entry *e) {
    Transport *t=active;uint32_t id=current();
    e->transport=t;e->identity=id;e->task=0;e->previous=0;e->slot=0;
    if(!t || !id)return;
    ENTER();Task *p=task(t,id,!t->closing);e->task=p;
    if(!p){if(!t->closing)fault(t,26);EXIT();return;}
    e->previous=p->request;p->request=0;
    if(e->previous){fault(t,28);EXIT();return;}
    if(t->closing){EXIT();return;}
    for(uint32_t i=0;i<16;i++) {
        EntrySlot *s=&t->entries[i];Request *q=&s->request;
        if(s->busy || q->held)continue;
        if(q->id && !(q->state==4 && !q->kind && !q->sent && !q->delivered))continue;
        /* Zero only storage that has never been exposed through a queue job. */
        uint32_t *words=(uint32_t*)q;
        for(uint32_t k=0;k<sizeof(*q)/4;k++)words[k]=0;
        uint32_t status=rr_begin(t->router,q);
        if(status){EXIT();return;}
        s->busy=1;e->slot=s;p->request=q;EXIT();return;
    }
    fault(t,26);EXIT();
}
static void entry_end(Entry *e) {
    if(!e->transport || !e->task)return;
    ENTER();
    if(current()!=e->identity || active!=e->transport) {
        fault(e->transport,29);EXIT();return; /* retain uncertain scope/storage */
    }
    Request *expected=e->slot?&e->slot->request:0;
    if(e->task->request!=expected){fault(e->transport,29);EXIT();return;}
    e->task->request=e->previous;
    if(e->slot) {
        (void)rr_finish_request(e->transport->router,expected);
        e->slot->busy=0;
    }
    EXIT();
}
static uint32_t body_ct_record_request(uint32_t target) {
    Entry e;entry_begin(&e);uint32_t result=ct_stock_record_request(target);
    entry_end(&e);return result;
}
static uint32_t body_ct_stop_request(void) {
    Entry e;entry_begin(&e);uint32_t result=ct_stock_stop_request();
    entry_end(&e);return result;
}
static uint32_t body_ct_play_request(void) {
    Entry e;entry_begin(&e);uint32_t result=ct_stock_play_request();
    entry_end(&e);return result;
}
static uint32_t body_ct_stop_argument(uint32_t argument) {
    Entry e;entry_begin(&e);uint32_t result=ct_stock_stop_argument(argument);
    entry_end(&e);return result;
}
static uint32_t body_ct_stop_other(void) {
    Entry e;entry_begin(&e);uint32_t result=ct_stock_stop_other();
    entry_end(&e);return result;
}
static void body_ct_dispatch(uint32_t *args) {
    Transport *t=active;uint32_t id=current();
    if(!t || !id || args[0]!=(uint32_t)t || args[1]>=8 || args[3]!=t->session)return;
    ENTER();Job *j=&t->jobs[args[1]];Task *p=task(t,id,1);
    if(args[1]>=t->used || j->id!=args[2] || j->claimed || j->sent==2 || !p || p->callback ||
       !j->request || j->request->id!=j->id || j->request->session!=t->session) {
        EXIT();return;
    }
    if(rr_dispatch(t->router,j->request)){EXIT();return;}
    j->claimed=1;p->callback=j->request;EXIT();
    ((void(*)(uint32_t*))j->words[0])(&j->words[1]);
    ENTER();p->callback=0;(void)rr_complete(t->router,j->request);j->done=1;EXIT();
}
static uint32_t body_ct_queue_send(uint32_t queue,const uint32_t *words) {
    Transport *t=active;
    if(!t || queue!=t->queue || (words[0]!=0x8004b9a1u && words[0]!=0x8004ba41u))
        return ct_stock_send(queue,words);
    uint32_t id=current();if(!id)return ct_stock_send(queue,words);
    ENTER();Task *p=task(t,id,0);Request *q=p?p->request:0;
    /* New ordinary requests remain usable after capture admission closes.
     * Earlier owned requests can still submit and must be tracked to completion. */
    if(t->closing && !q){EXIT();return ct_stock_send(queue,words);}
    /* Unguarded producer is detected at the common boundary. Preserve ordinary
     * behavior, but invalidate optional capture rather than invent ownership. */
    if(!q || q->router!=t->router || q->session!=t->session || !q->held || t->used==8 ||
       (t->closing && q->id>t->cutoff)) {
        fault(t,!q?27:26);EXIT();return ct_stock_send(queue,words);
    }
    uint32_t kind=words[0]==0x8004b9a1u?3:4;
    if(q->state==0)(void)rr_submit(t->router,q,kind);
    if(q->state!=1 || q->kind!=kind){fault(t,27);EXIT();return ct_stock_send(queue,words);}
    uint32_t index=t->used++;Job *j=&t->jobs[index];
    for(uint32_t i=0;i<8;i++)j->words[i]=words[i];
    j->request=q;j->id=q->id;
    uint32_t wire[8]={(uint32_t)ct_dispatch,(uint32_t)t,index,j->id,t->session,0,0,0};
    EXIT();
    /* No critical section is held while stock queue send can block. */
    uint32_t result=ct_stock_send(queue,wire);
    ENTER();j->sent=result==0?1:3;
    (void)rr_sent(t->router,q,result==0?0:2);EXIT();return result;
}
/* Control-plane acknowledgement ONLY. This never frees memory, resets the
 * transport, reopens capture, or asserts audio-hook/filesystem quiescence. */
static uint32_t body_ct_close_admission(Transport *t,uint32_t session) {
    if(!t || t!=active || session!=t->session || !current())return 12;
    ENTER();if(!t->closing) {
        uint32_t worker=*(volatile uint32_t*)0x80446dc0u;
        if(!worker){EXIT();return 12;}
        t->drain_worker=worker;t->cutoff=t->router->next;t->closing=1;
    }EXIT();return 0;
}
static int owned_idle(Transport *t) {
    if(t->router->pending)return 0;
    for(uint32_t i=0;i<8;i++)
        if(t->tasks[i].request || t->tasks[i].callback)return 0;
    for(uint32_t i=0;i<16;i++)if(t->entries[i].busy || t->entries[i].request.held)return 0;
    for(uint32_t i=0;i<t->used;i++)
        if(!t->jobs[i].done || t->jobs[i].sent!=1 || t->jobs[i].request->held)return 0;
    return 1;
}
static void body_ct_drain_marker(uint32_t *args) {
    Transport *t=active;if(!t || !current() || current()!=t->drain_worker)return;
    if(args[0]!=(uint32_t)t || args[1]!=t->session || args[2]!=t->cutoff || args[3]!=0x4c364452u)return;
    ENTER();if(t->closing && t->barrier_tx)t->barrier_seen=1;EXIT();
}
static uint32_t body_ct_drain_poll(Transport *t,uint32_t session) {
    if(!t || t!=active || session!=t->session || !current() || current()==t->drain_worker)return 12;
    ENTER();
    if(!t->closing){EXIT();return 12;}
    if(t->drain_error){uint32_t s=t->drain_error;EXIT();return s;}
    if(!owned_idle(t)){EXIT();return 11;}
    if(t->barrier_tx) {
        uint32_t s=t->barrier_tx==2 && t->barrier_seen?0:11;EXIT();return s;
    }
    /* Set SENDING before releasing the guard: another poll cannot duplicate
     * the marker, and its callback may run before the send result returns. */
    t->barrier_tx=1;
    uint32_t wire[8]={(uint32_t)ct_drain_marker,(uint32_t)t,t->session,t->cutoff,0x4c364452u,0,0,0};
    EXIT();
    uint32_t mutex=*(volatile uint32_t*)0x80446894u;
    uint32_t acquired=((uint32_t(*)(uint32_t,uint32_t))0x80076951u)(mutex,UINT32_MAX);
    uint32_t sent=UINT32_MAX,released=0;
    if(acquired==1) {
        sent=ct_stock_send(t->queue,wire);
        released=((uint32_t(*)(uint32_t,uint32_t,uint32_t,uint32_t))0x800763d9u)(mutex,0,0,0);
    }
    ENTER();
    if(acquired!=1 || sent!=0 || released!=1) {
        t->barrier_tx=3;t->drain_error=30;EXIT();return 30;
    }
    t->barrier_tx=2;uint32_t status=owned_idle(t) && t->barrier_seen?0:10;
    EXIT();return status;
}
/* Test-only checkpoint body substituted for deep stock file registration. */
KEEP void ct_emulator_admit(void) {bridge_hook(5,0);}

/* Single externally serialized manager. Transport/Router remain allocated;
 * this does not authorize freeing or replacing either object. */
extern uint32_t bridge_detach(void*,uint32_t);
KEEP uint32_t ct_detach_capture(Transport *t,uint32_t session) {
    if(!gateway_enter())return 12;
    uint32_t status=body_ct_drain_poll(t,session);
    if(!status)status=bridge_detach(t->router->bridge,session);
    gateway_leave();return status;
}

/* Every installed control entry reserves before body loads active. Wrappers
 * hold ownership throughout the original caller's stack lifetime. Denied
 * ordinary operations still execute stock behavior, without optional state. */
#define WRAP0(name,stock) KEEP uint32_t name(void) { \
    if(!gateway_enter())return stock(); \
    uint32_t s=body_##name();gateway_leave();return s; }
#define WRAP1(name,stock) KEEP uint32_t name(uint32_t a) { \
    if(!gateway_enter())return stock(a); \
    uint32_t s=body_##name(a);gateway_leave();return s; }
WRAP1(ct_record_request,ct_stock_record_request)
WRAP0(ct_stop_request,ct_stock_stop_request)
WRAP0(ct_play_request,ct_stock_play_request)
WRAP1(ct_stop_argument,ct_stock_stop_argument)
WRAP0(ct_stop_other,ct_stock_stop_other)
KEEP uint32_t ct_scope(Transport *t,Request *q) {
    if(!gateway_enter())return 12;
    uint32_t s=body_ct_scope(t,q);gateway_leave();return s;
}
KEEP uint32_t ct_request_op(Transport *t,Request *q,uint32_t op) {
    if(!gateway_enter())return 12;
    uint32_t s=body_ct_request_op(t,q,op);gateway_leave();return s;
}
KEEP uint32_t ct_queue_send(uint32_t queue,const uint32_t *words) {
    if(!gateway_enter())return ct_stock_send(queue,words);
    uint32_t s=body_ct_queue_send(queue,words);gateway_leave();return s;
}
KEEP void ct_dispatch(uint32_t *args) {
    if(!gateway_enter())return;
    body_ct_dispatch(args);gateway_leave();
}
/* v1.10 stop checkpoint 0x8000b78c, before WAV finalization. The original
 * worker latches short/failed writes separately from its completion token.
 * Attribute the observation only to the still-owned ordinary STOP callback;
 * never clear the stock error or modify ordinary recording behavior. */
KEEP void ct_record_drained(void) {
    if(!gateway_enter())return;
    Transport *t=active;uint32_t id=current();
    if(t && id) {
        ENTER();Task *p=task(t,id,0);Request *q=p?p->callback:0;
        if(q && q->router==t->router && q->session==t->session && q->held &&
           q->owner==t->router->owner && q->kind==4 && q->state==2 && q->marked &&
           *(volatile int8_t*)0x801f5f00u<0 && *(volatile uint32_t*)0x8077e878u)
            bridge_route_fault(t->router->bridge,t->session,33);
        EXIT();
    }
    gateway_leave();
}
KEEP void ct_drain_marker(uint32_t *args) {
    if(!gateway_enter())return;
    body_ct_drain_marker(args);gateway_leave();
}
KEEP uint32_t ct_close_admission(Transport *t,uint32_t session) {
    if(!gateway_enter())return 12;
    uint32_t s=body_ct_close_admission(t,session);gateway_leave();return s;
}
KEEP uint32_t ct_drain_poll(Transport *t,uint32_t session) {
    if(!gateway_enter())return 12;
    uint32_t s=body_ct_drain_poll(t,session);gateway_leave();return s;
}
/* Single manager with stable state. After closing, only this manager may use
 * old pointers directly. Installed callbacks/wrappers are fenced above; the
 * audio/context lookup gateway must already be detached. No reopening here. */
extern uint32_t bridge_unroute_detached(void*,uint32_t);
KEEP uint32_t ct_shutdown(Transport *t,uint32_t session) {
    if(t==detached_transport && session && session==detached_session)return 0;
    if(!t || t!=active || session!=t->session || !current() || current()==t->drain_worker)return 12;
    if(!(__atomic_load_n(&ct_gateway_readers,__ATOMIC_ACQUIRE)&0x80000000u)) {
        uint32_t s=ct_detach_capture(t,session);if(s)return s;
        __atomic_fetch_or(&ct_gateway_readers,0x80000000u,__ATOMIC_ACQ_REL);
    }
    if(__atomic_load_n(&ct_gateway_readers,__ATOMIC_ACQUIRE)&0x7fffffffu)return 11;
    if(!owned_idle(t))return 11;
    Router *r=t->router;
    uint32_t s=bridge_unroute_detached(r->bridge,session);if(s)return s;
    /* Clear owned links; externally retained direct rr_* pointers are outside
     * this installed-entry contract and must not be used after shutdown. */
    for(uint32_t i=0;i<t->used;i++) {
        t->jobs[i].request->router=0;t->jobs[i].request=0;
    }
    for(uint32_t i=0;i<16;i++)t->entries[i].request.router=0;
    r->bridge=0;t->router=0;active=0;
    detached_transport=t;detached_session=session;return 0;
}

/* Fresh staging descriptor: Transport, Router, Bridge, Exchange, Life, Capture,
 * Slots, slot_count, unique_session, original_queue. Manager-only; storage is
 * fresh/zeroed under the shutdown contract, Life prepared by its worker. */
extern uint32_t bridge_prepare_next(void*,void*,void*,void*,uint32_t);
extern uint32_t bridge_queue_next(void*,void*,uint32_t),bridge_handover_ready(void*,uint32_t);
extern uint32_t rr_init(Router*,void*,uint32_t);
static Transport *staged_transport;
static uint32_t bootstrap_pending;
extern uint32_t bridge_boot_close(void);
/* Single initialization caller before hooks are installed. The bridge checks
 * virgin runtime state before changing anything. No ordinary queue is touched. */
KEEP uint32_t ct_boot_close(void) {
    if(active || detached_transport || staged_transport || bootstrap_pending ||
       __atomic_load_n(&ct_gateway_readers,__ATOMIC_ACQUIRE))return 12;
    uint32_t s=bridge_boot_close();if(s)return s;
    __atomic_store_n(&ct_gateway_readers,0x80000000u,__ATOMIC_RELEASE);
    bootstrap_pending=1;return 0;
}
KEEP uint32_t ct_stage_next(const uint32_t *d) {
    if(active || (!detached_transport && !bootstrap_pending) || staged_transport ||
       __atomic_load_n(&ct_gateway_readers,__ATOMIC_ACQUIRE)!=0x80000000u ||
       !d[0] || !d[1] || !d[2] || !d[3] || !d[4] || !d[5] || !d[6] || !d[9] ||
       d[7]<2 || d[7]>EXCHANGE_MAX_SLOTS || (d[7]&(d[7]-1)))return 12;
    Transport *t=(Transport*)d[0];Router *r=(Router*)d[1];
    if(t->router || r->bridge)return 12;
    uint32_t s=bridge_prepare_next((void*)d[2],(void*)d[3],(void*)d[4],(void*)d[5],d[8]);if(s)return s;
    s=rr_init(r,(void*)d[2],d[8]);if(s)return s;
    s=bridge_route_context((void*)d[2],t,lookup);if(s)return s;
    t->router=r;t->session=d[8];t->queue=d[9];t->closing=1;
    s=bridge_queue_next((void*)d[2],(void*)d[6],d[7]);
    if(!s)staged_transport=t;return s;
}
KEEP uint32_t ct_activate_next(Transport *t,uint32_t session) {
    if(!t || t!=staged_transport || session!=t->session)return 12;
    uint32_t s=bridge_handover_ready(t->router->bridge,session);if(s)return s;
    uint32_t expected=0x80000000u;
    if(!__atomic_compare_exchange_n(&ct_gateway_readers,&expected,0x80000001u,
                                   0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
    /* All state initialized before publication. Never reset a live count. */
    active=t;t->closing=0;staged_transport=0;bootstrap_pending=0;
    __atomic_fetch_and(&ct_gateway_readers,0x7fffffffu,__ATOMIC_RELEASE);
    gateway_leave();return 0;
}
extern uint32_t bridge_cancel_failed_stage(void*,uint32_t);
KEEP uint32_t ct_cancel_failed_stage(Transport *t,uint32_t session) {
    if(!t || t!=staged_transport || t->session!=session)return 12;
    uint32_t s=bridge_cancel_failed_stage(t->router->bridge,session);
    if(!s)staged_transport=0;return s;
}

extern uint32_t bridge_abort_stage(void*,uint32_t);
KEEP uint32_t ct_abort_stage(Transport *t,uint32_t session) {
    if(!t || t!=staged_transport || t->session!=session)return 12;
    uint32_t s=bridge_abort_stage(t->router->bridge,session);
    if(!s)staged_transport=0;return s;
}
KEEP uint32_t ct_manager_matches(const uint32_t *d) {
    Transport *t=(Transport*)d[0];Router *r=(Router*)d[1];
    return active==t && t->router==r && r->bridge==(void*)d[2] &&
           t->session==d[8] && r->session==d[8] && t->queue==d[9] && !t->closing;
}
KEEP uint32_t ct_stage_is_published(void *t) {return t==active || t==staged_transport;}
