#include "reload_compact.h"
#include "publication_workflow.h"
#define KEEP __attribute__((used,retain))
static RcBinding *binding;
static RmManager *manager;
KEEP int32_t rc_bind_manager(RmManager *m) {
    if(manager || !binding || !m || m->runtime!=binding->runtime)return OWN_CONFLICT;
    manager=m;return OWN_OK;
}
/* EMPTY=0, private sender/consumer ownership=1, retryable=2. No metadata lock
 * spans the native event call. Capacity equals the maximum live reload jobs. */
typedef struct {uint32_t state,words[5];} RcPending;
static RcPending pending[RL_SLOTS];
KEEP RcMode rc_mode5_state;
extern int32_t rc_stock_send(uint32_t,const void *);
extern int32_t rc_stock_event(const void *,uint32_t);
extern int32_t rc_stock_ui(const uint32_t *);
extern uint32_t rc_stock_filter(uint32_t);
extern int32_t rc_stock_clear(void);
extern int32_t rc_stock_delete(uint32_t,uint32_t,uint32_t);
extern void rc_mode5_prefix(void),rc_mode5_suffix(void);
static int32_t bad(void) {
    if(binding){binding->unbound=1;od_gate_fail(&binding->runtime->coordinator->ledger->gate);}
    return OWN_FAULT;
}
static RtTask *task(uint32_t role) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(!binding || ipsr)return 0;
    uint32_t id=((uint32_t (*)(void))UINT32_C(0x800770e9))();
    if(!id)return 0;
    if(role==RL_WORKER && id==binding->worker_id)return binding->worker;
    if(role==RL_UI && id==binding->ui_id)return binding->ui;
    return 0;
}
KEEP int32_t rc_bind(RcBinding *b) {
    if(binding || !b || !b->runtime || !b->worker || !b->ui || b->worker==b->ui ||
       !b->worker_id || !b->ui_id || b->worker_id==b->ui_id ||
       !b->worker_queue || !b->ui_queue || b->worker_queue==b->ui_queue || !b->receive || !b->yield)return OWN_CONFLICT;
    binding=b;return OWN_OK;
}
KEEP int32_t rc_bind_reads(const RpBinding *p,const RwBinding *w) {
    if(!binding || !p || !w || !binding->runtime->coordinator ||
       p->coordinator!=binding->runtime->coordinator || w->coordinator!=p->coordinator ||
       p->tasks[0]!=binding->worker || p->tasks[1]!=binding->ui ||
       p->ids[0]!=binding->worker_id || p->ids[1]!=binding->ui_id || p->queue!=w->queue ||
       w->worker==p->ids[0] || w->worker==p->ids[1] ||
       p->queue==binding->worker_queue || p->queue==binding->ui_queue ||
       binding->worker_queue!=*(volatile uint32_t *)0x801f8f3cu ||
       binding->ui_queue!=*(volatile uint32_t *)0x801f8f28u)return OWN_CONFLICT;
    int32_t result=rp_can_bind(p);if(result)return result;
    result=rw_can_bind(w);if(result)return result;
    if(w->slots[p->slots[0]]!=p->reads[0] || w->slots[p->slots[1]]!=p->reads[1])return OWN_CONFLICT;
    RlCoordinator *c=p->coordinator;
    if(c->lock || c->ledger->lock || c->ledger->gate.word || c->cleanup || c->draining || c->manager ||
       binding->worker->lock || binding->worker->phase!=RT_IDLE ||
       binding->ui->lock || binding->ui->phase!=RT_IDLE)return OWN_BUSY;
    for(uint32_t i=0;i<RL_SLOTS;i++)if(c->jobs[i].owner)return OWN_BUSY;
    for(uint32_t i=0;i<RR_QUEUE_SLOTS;i++)if(w->slots[i]) {
        const RrRead *r=w->slots[i];
        if(r->lock || r->phase!=RR_EMPTY || r->ticket || r->queue_state || r->coordinator)return OWN_BUSY;
    }
    /* Preflight cannot race: this API's contract is one cold initialization
     * caller before hooks or participants run. Unexpected partial failure is
     * terminal; never activate hooks or attempt to reset permanent state. */
    result=rw_bind(w);if(result)return bad();
    result=rp_bind(p);if(result)return bad();
    return OWN_OK;
}
KEEP int32_t rc_send_worker(const RtWorkerPacket *p) {
    if(!binding || p->tag.magic!=RL_MAGIC || p->tag.role!=RL_WORKER || p->body[0]!=UINT32_C(0x80049da1))return bad();
    uint32_t words[8]={(uint32_t)rc_worker,RL_MAGIC,p->tag.owner,p->tag.child,RL_WORKER,0,0,0};
    return rc_stock_send(binding->worker_queue,words);
}
KEEP int32_t rc_send_ui(const RtUiPacket *p) {
    if(!binding || p->tag.magic!=RL_MAGIC || p->tag.role!=RL_UI ||
       p->body[0]!=1 || p->body[1]!=4 || p->body[2]!=26 || p->body[3] || p->body[4])return bad();
    RcPending *slot=0;
    for(uint32_t i=0;i<RL_SLOTS;i++) {
        uint32_t zero=0;
        if(__atomic_compare_exchange_n(&pending[i].state,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED)){slot=&pending[i];break;}
    }
    if(!slot)return bad();
    slot->words[0]=1;slot->words[1]=4;slot->words[2]=26;
    slot->words[3]=p->tag.owner;slot->words[4]=p->tag.child;
    int32_t result=rc_stock_event(slot->words,0);
    __atomic_store_n(&slot->state,result?2:0,__ATOMIC_RELEASE);
    return result;
}
KEEP int32_t rc_worker(const uint32_t *args) {
    RtTask *t=task(RL_WORKER);if(!t)return bad();
    RtWorkerPacket p;
    p.tag=(RlEnvelope){args[0],args[1],args[2],args[3]};
    if(args[4] || args[5] || args[6])return OWN_CONFLICT;
    p.body[0]=UINT32_C(0x80049da1);
    for(uint32_t i=1;i<8;i++)p.body[i]=0;
    int32_t r=rt_receive(t,&p,RL_WORKER);
    if(r==OWN_BUSY)return bad(); /* ingress must drain retained work first */
    return r?r:rt_run(binding->runtime,t);
}
KEEP int32_t rc_ui(const uint32_t *words) {
    RtTask *t=task(RL_UI);if(!t)return bad();
    if(words[0]!=1 || words[1]!=4 || words[2]!=26 || (!words[3] && !words[4]))return rc_stock_ui(words);
    RtUiPacket p;
    p.tag=(RlEnvelope){RL_MAGIC,words[3],words[4],RL_UI};
    p.body[0]=1;p.body[1]=4;p.body[2]=26;p.body[3]=0;p.body[4]=0;
    int32_t r=rt_receive(t,&p,RL_UI);
    if(r==OWN_BUSY)return bad();
    return r?r:rt_run(binding->runtime,t);
}
KEEP int32_t rc_next(uint32_t q,void *out) {
    if(!binding)return bad();
    uint32_t role=q==binding->worker_queue?RL_WORKER:q==binding->ui_queue?RL_UI:0;
    RtTask *t=task(role);if(!t)return bad();
    if(t->phase!=RT_IDLE && t->phase!=RT_DONE) {
        int32_t r=rt_run(binding->runtime,t);
        if(r!=OWN_OK && r!=OWN_STALE && r!=OWN_CONFLICT){binding->yield();return -1;}
    }
    if(role==RL_UI && rc_retry_ui()==OWN_FAULT)return -1;
    if(role==RL_UI && manager) {
        int32_t r=rm_step(manager);
        if(r==OWN_FAULT){binding->yield();return -1;}
        if(r==OWN_BUSY) {
            rc_service_owned();binding->yield();return -1;
        }
    }
    if(role==RL_UI) {
        int32_t r=pw_main_ready();
        if(r!=OWN_OK) {
            if(r==OWN_BUSY)rc_service_owned();
            binding->yield();return -1;
        }
    }
    return binding->receive(q,out);
}
KEEP int32_t rc_queue(uint32_t q,const void *p) {
    if(!binding)return -1;
    if(q!=binding->ui_queue)return rc_stock_send(q,p);
    int32_t r=((int32_t (*)(uint32_t,const void *,uint32_t,uint32_t))UINT32_C(0x800763d9))(q,p,0,0);
    if(!r)return -1;
    ++*(volatile uint32_t *)UINT32_C(0x806b2f20);
    return 0;
}
static int begin_cleanup(uint32_t bit) {
    if(!binding)return 0;
    if(rl_cleanup_begin(binding->runtime->coordinator)) {binding->deferred|=bit;return 0;}
    return 1;
}
static int32_t end_cleanup(void) {
    return rl_cleanup_end(binding->runtime->coordinator)?bad():OWN_OK;
}
KEEP uint32_t rc_filter(uint32_t n) {
    if(!begin_cleanup(1))return n;
    uint32_t result=rc_stock_filter(n);end_cleanup();return result;
}
KEEP int32_t rc_clear(void) {
    if(!begin_cleanup(2))return OWN_BUSY;
    rc_stock_clear();return end_cleanup();
}
KEEP int32_t rc_delete(uint32_t a,uint32_t b,uint32_t c) {
    if(!begin_cleanup(4))return OWN_BUSY;
    rc_stock_delete(a,b,c);return end_cleanup();
}
KEEP const uint32_t rc_layout[]={sizeof(RcBinding)};

KEEP int32_t rc_retry_ui(void) {
    if(!task(RL_UI))return bad();
    for(uint32_t i=0;i<RL_SLOTS;i++) {
        uint32_t ready=2;
        if(!__atomic_compare_exchange_n(&pending[i].state,&ready,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))continue;
        RlEnvelope e;
        int32_t r=rl_envelope(binding->runtime->coordinator,pending[i].words[3],RL_UI,&e);
        if(r==OWN_STALE){__atomic_store_n(&pending[i].state,0,__ATOMIC_RELEASE);continue;}
        if(r || e.child!=pending[i].words[4]) {
            __atomic_store_n(&pending[i].state,2,__ATOMIC_RELEASE);
            return r==OWN_BUSY?OWN_BUSY:bad();
        }
        r=rc_stock_event(pending[i].words,0);
        __atomic_store_n(&pending[i].state,r?2:0,__ATOMIC_RELEASE);
        /* One attempt per poll; never spin waiting for space in Main. */
        return r?OWN_BUSY:OWN_OK;
    }
    return OWN_OK;
}
/* During transition draining a full queue may contain only ordinary controls,
 * which cannot safely run before startup finishes. Transfer one retained UI
 * event directly into Main's task-owned continuation instead of requiring a
 * free queue slot. Normal Main receive still retries in FIFO order. */
static int32_t retained_to_main(void) {
    for(uint32_t i=0;i<RL_SLOTS;i++) {
        uint32_t ready=2;
        if(!__atomic_compare_exchange_n(&pending[i].state,&ready,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))continue;
        RlEnvelope e;
        int32_t r=rl_envelope(binding->runtime->coordinator,pending[i].words[3],RL_UI,&e);
        if(r==OWN_STALE){__atomic_store_n(&pending[i].state,0,__ATOMIC_RELEASE);continue;}
        if(r || e.child!=pending[i].words[4]) {
            __atomic_store_n(&pending[i].state,2,__ATOMIC_RELEASE);
            return r==OWN_BUSY?OWN_BUSY:bad();
        }
        r=rc_ui(pending[i].words);
        /* BUSY here has transferred the copied message into RtTask. Its
         * receive/return retry phases own subsequent progress. */
        __atomic_store_n(&pending[i].state,r==OWN_FAULT?2:0,__ATOMIC_RELEASE);
        return r;
    }
    return OWN_BUSY;
}
/* Rotate a snapshot under the stock event mutex. Preserve the relative order
 * of all unselected messages, then run at most one owned UI body AFTER unlock.
 * Ordinary UI controls are not dispatched during startup-transition draining. */
KEEP int32_t rc_service_owned(void) {
    RtTask *t=task(RL_UI);if(!t)return bad();
    if(t->phase!=RT_IDLE && t->phase!=RT_DONE) {
        int32_t r=rt_run(binding->runtime,t);
        if(r!=OWN_OK && r!=OWN_STALE && r!=OWN_CONFLICT)return r;
    }
    if(rc_retry_ui()==OWN_FAULT)return OWN_FAULT;
    uint32_t mutex=*(volatile uint32_t *)UINT32_C(0x80446810);
    if(!((int32_t (*)(uint32_t,uint32_t))UINT32_C(0x80076951))(mutex,0))return OWN_BUSY;
    uint32_t count=*(volatile uint32_t *)(binding->ui_queue+0x38),found=0;
    uint32_t saved[5],words[5];int32_t status=OWN_BUSY;
    if(count>4096)status=bad();
    else for(uint32_t i=0;i<count;i++) {
        if(!((int32_t (*)(uint32_t,void *,uint32_t))UINT32_C(0x80076711))(binding->ui_queue,words,0)){status=bad();break;}
        --*(volatile uint32_t *)UINT32_C(0x806b2f20);
        if(!found && words[0]==1 && words[1]==4 && words[2]==26 && words[3] && words[4]) {
            for(uint32_t k=0;k<5;k++)saved[k]=words[k];found=1;
        } else if(rc_queue(binding->ui_queue,words)){status=bad();break;}
    }
    ((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t))UINT32_C(0x800763d9))(mutex,0,0,0);
    if(status==OWN_FAULT)return status;
    return found?rc_ui(saved):retained_to_main();
}
KEEP void rc_pause(void){if(binding)binding->yield();}
KEEP int32_t rc_mode5_step(RcMode *s) {
    if(!task(RL_UI))return bad();
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&s->lock,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return OWN_BUSY;
    int32_t r=OWN_BUSY;RlCoordinator *c=binding->runtime->coordinator;
    if(s->phase==RC_MODE_IDLE) {
        /* A publication workflow still owns its parent/capture handoff after
         * RM_DONE. Keep progressing owned reloads, but do not close admission
         * ahead of its producer or run mode setup before its final release. */
        r=pw_main_ready();
        if(r==OWN_BUSY) {
            if(manager && rm_step(manager)==OWN_FAULT){r=OWN_FAULT;goto done;}
            r=rc_service_owned();
            if(r==OWN_OK || r==OWN_STALE || r==OWN_CONFLICT)r=OWN_BUSY;
            goto done;
        }
        if(r)goto done;
        /* Acquire/launch a prepared manager before closing new admission. */
        if(manager && (manager->phase==RM_ACQUIRE || manager->phase==RM_START)) {
            r=rm_step(manager);
            if(r==OWN_FAULT || manager->phase==RM_ACQUIRE || manager->phase==RM_START)goto done;
        }
        r=rl_transition_begin(c);
        if(r)goto done;
        s->phase=RC_MODE_DRAIN;
    }
    if(s->phase==RC_MODE_DRAIN) {
        if(manager && rm_step(manager)==OWN_FAULT){r=OWN_FAULT;goto done;}
        r=rl_transition_ready(c);
        if(r==OWN_BUSY) {
            r=rc_service_owned();
            if(r==OWN_OK || r==OWN_STALE || r==OWN_CONFLICT)r=OWN_BUSY;
            goto done;
        }
        if(r)goto done;
        s->phase=RC_MODE_RUN;
        rc_mode5_prefix();rc_stock_clear();rc_mode5_suffix();
        s->phase=RC_MODE_RELEASE;
    }
    if(s->phase==RC_MODE_RELEASE) {
        r=rl_transition_end(c);
        if(!r)s->phase=RC_MODE_DONE;
    } else if(s->phase==RC_MODE_DONE)r=OWN_OK;
    else if(s->phase==RC_MODE_FAILED)r=OWN_FAULT;
done:
    if(r!=OWN_OK && r!=OWN_BUSY){s->error=(uint32_t)r;s->phase=RC_MODE_FAILED;bad();r=OWN_FAULT;}
    __atomic_store_n(&s->lock,0,__ATOMIC_RELEASE);return r;
}
KEEP int32_t rc_mode5_poll(void){return rc_mode5_step(&rc_mode5_state);}
