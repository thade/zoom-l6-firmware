#include "reload_ownership.h"
#define KEEP __attribute__((used,retain))
static int enter(RlCoordinator *c) {
    uint32_t zero=0;
    return __atomic_compare_exchange_n(&c->lock,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(RlCoordinator *c,int32_t r){__atomic_store_n(&c->lock,0,__ATOMIC_RELEASE);return r;}
static int32_t fail(RlCoordinator *c){od_gate_fail(&c->ledger->gate);return OWN_FAULT;}
/* Avoid pulling a hosted/compiler-runtime memset into the freestanding image. */
static void clear(RlJob *j) {
    volatile uint32_t *p=(volatile uint32_t *)j;
    for(uint32_t i=0;i<sizeof(*j)/sizeof(*p);i++)p[i]=0;
}
static RlJob *find(RlCoordinator *c,uint32_t id) {
    for(uint32_t i=0;i<RL_SLOTS;i++)if(id && c->jobs[i].owner==id)return &c->jobs[i];
    return 0;
}
static OwnRequest request(uint32_t role,uint32_t owner) {
    OwnRequest r={OWN_SCAN,{owner,role,0,0}};return r;
}
static int32_t offered(RlCoordinator *c,uint32_t parent,uint32_t role,uint32_t *ticket) {
    OwnRequest r=request(role,parent);
    int32_t status=od_own_child(c->ledger,parent,&r,ticket);
    if(status)return status;
    return od_own_offer(c->ledger,*ticket)?fail(c):OWN_OK;
}
static int32_t begin(RlCoordinator *c,uint32_t token,uint32_t parent,uint32_t *out) {
    *out=0;if(!enter(c))return OWN_BUSY;
    if(c->cleanup || (c->draining && !token) || c->manager!=token)return leave(c,OWN_BUSY);
    RlJob *j=0;
    for(uint32_t i=0;i<RL_SLOTS;i++)if(!c->jobs[i].owner){j=&c->jobs[i];break;}
    if(!j)return leave(c,OWN_FULL);
    OwnRequest r={OWN_SESSION,{0,0,0,0}};
    uint32_t id=0;
    int32_t status=parent?od_own_child(c->ledger,parent,&r,&id):od_own_reserve(c->ledger,&r,&id);
    if(status)return leave(c,status);
    clear(j);j->owner=id;*out=id;
    if(od_own_offer(c->ledger,id) || od_own_submitted(c->ledger,id,OWN_ACCEPTED) ||
       od_own_claim(c->ledger,id,&r))return leave(c,fail(c));
    status=offered(c,id,RL_WORKER,&j->worker);
    return leave(c,status?fail(c):OWN_OK);
}
KEEP int32_t rl_begin(RlCoordinator *c,uint32_t parent,uint32_t *out) {return begin(c,0,parent,out);}
KEEP int32_t rl_begin_managed(RlCoordinator *c,uint32_t token,uint32_t parent,uint32_t *out) {
    if(!token)return OWN_CONFLICT;
    return begin(c,token,parent,out);
}
KEEP int32_t rl_manage_begin(RlCoordinator *c,uint32_t token) {
    if(!token)return OWN_CONFLICT;
    if(!enter(c))return OWN_BUSY;
    if(c->cleanup || c->draining || c->manager)return leave(c,OWN_BUSY);
    for(uint32_t i=0;i<RL_SLOTS;i++)if(c->jobs[i].owner)return leave(c,OWN_BUSY);
    if(__atomic_load_n(&c->ledger->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)return leave(c,OWN_FAULT);
    c->manager=token;return leave(c,OWN_OK);
}
KEEP int32_t rl_manage_end(RlCoordinator *c,uint32_t token) {
    if(!enter(c))return OWN_BUSY;
    if(!token || c->manager!=token)return leave(c,OWN_CONFLICT);
    if(__atomic_load_n(&c->ledger->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)return leave(c,OWN_FAULT);
    for(uint32_t i=0;i<RL_SLOTS;i++)if(c->jobs[i].owner)return leave(c,OWN_BUSY);
    c->manager=0;return leave(c,OWN_OK);
}
KEEP int32_t rl_prepare_ui(RlCoordinator *c,uint32_t id) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=find(c,id);if(!j)return leave(c,OWN_STALE);
    if(!j->worker_claimed || j->worker_done || j->ui)return leave(c,OWN_CONFLICT);
    int32_t r=offered(c,id,RL_UI,&j->ui);
    return leave(c,r==OWN_BUSY?r:r?fail(c):OWN_OK);
}
KEEP int32_t rl_envelope(RlCoordinator *c,uint32_t id,uint32_t role,RlEnvelope *out) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=find(c,id);if(!j)return leave(c,OWN_STALE);
    uint32_t child=role==RL_WORKER?j->worker:role==RL_UI?j->ui:0;
    if(!child)return leave(c,OWN_CONFLICT);
    *out=(RlEnvelope){RL_MAGIC,id,child,role};return leave(c,OWN_OK);
}
KEEP int32_t rl_sent(RlCoordinator *c,uint32_t id,uint32_t role,uint32_t outcome) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=find(c,id);if(!j)return leave(c,OWN_STALE);
    uint32_t *sent=role==RL_WORKER?&j->worker_sent:role==RL_UI?&j->ui_sent:0;
    uint32_t child=role==RL_WORKER?j->worker:j->ui;
    if(!sent || !child || *sent || outcome<OWN_ACCEPTED || outcome>OWN_UNCERTAIN)return leave(c,OWN_CONFLICT);
    int32_t r=od_own_submitted(c->ledger,child,outcome);
    if(r)return leave(c,r==OWN_BUSY?r:fail(c));
    *sent=outcome;
    if(outcome==OWN_NOT_SENT) {
        j->error=1;
        if(role==RL_WORKER)j->worker_done=1;else j->ui_done=1;
    }
    if(role==RL_UI && od_own_producer_done(c->ledger,child,0))return leave(c,fail(c));
    return leave(c,OWN_OK);
}
KEEP int32_t rl_producer_return(RlCoordinator *c,uint32_t id) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=find(c,id);if(!j)return leave(c,OWN_STALE);
    if(!j->worker_sent || j->producer_done)return leave(c,OWN_CONFLICT);
    int32_t r=od_own_producer_done(c->ledger,j->worker,0);
    if(!r)j->producer_done=1;
    return leave(c,r==OWN_BUSY?r:r?fail(c):OWN_OK);
}
static int32_t decode(RlCoordinator *c,const RlEnvelope *e,RlJob **job,uint32_t **claimed,uint32_t **done) {
    if(e->magic!=RL_MAGIC || (e->role!=RL_WORKER && e->role!=RL_UI))return OWN_CONFLICT;
    RlJob *j=find(c,e->owner);if(!j)return OWN_STALE;
    if(!e->child || e->child!=(e->role==RL_WORKER?j->worker:j->ui))return OWN_STALE;
    *job=j;*claimed=e->role==RL_WORKER?&j->worker_claimed:&j->ui_claimed;
    *done=e->role==RL_WORKER?&j->worker_done:&j->ui_done;return OWN_OK;
}
KEEP int32_t rl_claim(RlCoordinator *c,const RlEnvelope *e) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=0;uint32_t *claimed=0,*done=0;
    int32_t r=decode(c,e,&j,&claimed,&done);
    if(r)return leave(c,r);
    if(*claimed || *done)return leave(c,OWN_STALE);
    OwnRequest req=request(e->role,e->owner);
    r=od_own_claim(c->ledger,e->child,&req);
    if(!r)*claimed=1;
    return leave(c,r==OWN_BUSY?r:r?fail(c):OWN_OK);
}
KEEP int32_t rl_complete(RlCoordinator *c,const RlEnvelope *e) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=0;uint32_t *claimed=0,*done=0;
    int32_t r=decode(c,e,&j,&claimed,&done);
    if(r)return leave(c,r);
    if(!*claimed || *done)return leave(c,OWN_STALE);
    /* Worker cannot publish completion without attributing its continuation. */
    if(e->role==RL_WORKER && !j->ui)return leave(c,OWN_BUSY);
    r=od_own_complete(c->ledger,e->child);
    if(!r)*done=1;
    return leave(c,r==OWN_BUSY?r:r?fail(c):OWN_OK);
}
KEEP int32_t rl_io_error(RlCoordinator *c,const RlEnvelope *e,uint32_t error) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=0;uint32_t *claimed=0,*done=0;
    int32_t r=decode(c,e,&j,&claimed,&done);
    if(r)return leave(c,r);
    /* Attributed asynchronous descendants can report after the stock body
     * returned; their ledger reservations still prevent owner retirement. */
    if(!*claimed || !error)return leave(c,OWN_CONFLICT);
    if(!j->error)j->error=error;
    return leave(c,OWN_OK);
}
static int returned(const RlJob *j) {
    return j->producer_done && j->worker_done && j->worker_sent &&
        (j->worker_sent==OWN_NOT_SENT || (j->ui && j->ui_done && j->ui_sent));
}
KEEP int32_t rl_read_reserve(RlCoordinator *c,const RlEnvelope *e,const OwnRequest *request,uint32_t *ticket) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=0;uint32_t *claimed=0,*done=0;
    int32_t r=decode(c,e,&j,&claimed,&done);
    if(r)return leave(c,r);
    if(!*claimed || *done || request->kind!=OWN_SESSION)return leave(c,OWN_CONFLICT);
    return leave(c,od_own_child(c->ledger,e->child,request,ticket));
}
KEEP int32_t rl_seal(RlCoordinator *c,uint32_t token,uint32_t id) {
    if(!enter(c))return OWN_BUSY;
    if(!token || c->manager!=token)return leave(c,OWN_CONFLICT);
    RlJob *j=find(c,id);if(!j)return leave(c,OWN_STALE);
    if(!returned(j))return leave(c,OWN_BUSY);
    if(j->error || j->verified==RL_REJECTED)return leave(c,fail(c));
    return leave(c,od_own_seal_session(c->ledger,id));
}
KEEP int32_t rl_verify(RlCoordinator *c,uint32_t id,uint32_t evidence) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=find(c,id);if(!j)return leave(c,OWN_STALE);
    if(evidence>RL_REJECTED)return leave(c,OWN_CONFLICT);
    if(!returned(j))return leave(c,OWN_BUSY);
    int32_t r=od_own_session_drained(c->ledger,id);
    if(r)return leave(c,r);
    if(j->verified==RL_REJECTED && evidence!=RL_REJECTED)return leave(c,OWN_CONFLICT);
    j->verified=evidence;return leave(c,OWN_OK);
}
KEEP int32_t rl_finish(RlCoordinator *c,uint32_t id) {
    if(!enter(c))return OWN_BUSY;
    RlJob *j=find(c,id);if(!j)return leave(c,OWN_STALE);
    if(!returned(j))return leave(c,OWN_BUSY);
    if(j->error || j->verified==RL_REJECTED)return leave(c,fail(c));
    if(j->verified!=RL_VERIFIED)return leave(c,OWN_BUSY);
    int32_t r=od_own_finish_session(c->ledger,id);
    if(!r)clear(j);
    return leave(c,r);
}
KEEP const uint32_t rl_layout[]={sizeof(RlCoordinator),sizeof(RlJob),sizeof(RlEnvelope)};
KEEP int32_t rl_cleanup_begin(RlCoordinator *c) {
    if(!enter(c))return OWN_BUSY;
    if(c->cleanup || c->draining || c->manager)return leave(c,OWN_BUSY);
    for(uint32_t i=0;i<RL_SLOTS;i++)if(c->jobs[i].owner)return leave(c,OWN_BUSY);
    c->cleanup=1;return leave(c,OWN_OK);
}
KEEP int32_t rl_cleanup_end(RlCoordinator *c) {
    if(!enter(c))return OWN_BUSY;
    if(!c->cleanup || c->draining)return leave(c,OWN_CONFLICT);
    c->cleanup=0;return leave(c,OWN_OK);
}
KEEP int32_t rl_transition_begin(RlCoordinator *c) {
    if(!enter(c))return OWN_BUSY;
    if(c->cleanup || c->draining)return leave(c,OWN_BUSY);
    if(__atomic_load_n(&c->ledger->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)return leave(c,OWN_FAULT);
    c->draining=1;return leave(c,OWN_OK);
}
KEEP int32_t rl_transition_ready(RlCoordinator *c) {
    if(!enter(c))return OWN_BUSY;
    if(!c->draining || c->cleanup)return leave(c,OWN_CONFLICT);
    if(c->manager)return leave(c,OWN_BUSY);
    if(__atomic_load_n(&c->ledger->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)return leave(c,OWN_FAULT);
    for(uint32_t i=0;i<RL_SLOTS;i++)if(c->jobs[i].owner)return leave(c,OWN_BUSY);
    c->cleanup=1;return leave(c,OWN_OK);
}
KEEP int32_t rl_transition_end(RlCoordinator *c) {
    if(!enter(c))return OWN_BUSY;
    if(!c->draining || !c->cleanup)return leave(c,OWN_CONFLICT);
    if(__atomic_load_n(&c->ledger->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED)return leave(c,OWN_FAULT);
    c->cleanup=0;c->draining=0;return leave(c,OWN_OK);
}
