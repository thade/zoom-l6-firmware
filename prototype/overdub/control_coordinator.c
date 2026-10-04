#include "control_coordinator.h"
#include <stddef.h>
#define KEEP __attribute__((used,retain))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
KEEP const uint32_t oc_layout[]={sizeof(OcCoordinator),sizeof(OcJob),offsetof(OcCoordinator,jobs)};
static int enter(OcCoordinator *c) {
    uint32_t zero=0;
    return __atomic_compare_exchange_n(&c->lock,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static uint32_t leave(OcCoordinator *c,uint32_t status){ST(&c->lock,0);return status;}
static OcJob *find(OcCoordinator *c,uint32_t ticket) {
    for(uint32_t i=0;i<OC_SLOTS;i++)if(c->jobs[i].ticket==ticket && ticket)return &c->jobs[i];
    return 0;
}
static void reap_runner(OcCoordinator *c) {
    OcJob *j=find(c,c->running);
    if(j && LD(&j->phase)==OC_DONE)c->running=0;
}
KEEP uint32_t oc_submit(OcCoordinator *c,uint32_t kind,const uint32_t args[2],uint32_t *out) {
    if(!c || !args || !out || kind<OC_EFFECT_A || kind>OC_MODE_C ||
       (kind>=OC_MODE_A && (args[0] || args[1])))return OC_INVALID;
    if(!enter(c))return OC_BUSY;
    if(c->sequence==UINT32_MAX)return leave(c,OC_EXHAUSTED);
    OcJob *j=0;
    for(uint32_t i=0;i<OC_SLOTS;i++)if(!c->jobs[i].ticket){j=&c->jobs[i];break;}
    if(!j)return leave(c,OC_FULL);
    j->ticket=++c->sequence;j->kind=kind;j->args[0]=args[0];j->args[1]=args[1];
    ST(&j->phase,OC_QUEUED);*out=j->ticket;return leave(c,OC_OK);
}
KEEP uint32_t oc_run_one(OcCoordinator *c,OcDispatch dispatch) {
    if(!c || !dispatch)return OC_INVALID;
    if(!enter(c))return OC_BUSY;
    reap_runner(c);
    if(c->closed || c->running)return leave(c,OC_BUSY);
    OcJob *j=0;
    for(uint32_t i=0;i<OC_SLOTS;i++) {
        OcJob *p=&c->jobs[i];
        if(LD(&p->phase)==OC_QUEUED && (!j || p->ticket<j->ticket))j=p;
    }
    if(!j)return leave(c,OC_BUSY);
    c->running=j->ticket;ST(&j->phase,OC_RUNNING);leave(c,OC_OK);
    /* One admitted whole workflow. Its queued/direct parameter writes must
     * complete normally while audio keeps running. No metadata lock is held. */
    dispatch(j->kind,j->args);
    /* Last access to this job: DONE follows actual dispatch return. Reader may
     * reclaim its slot after acquiring DONE; this function touches neither
     * job nor coordinator again. */
    ST(&j->phase,OC_DONE);
    return OC_OK;
}
KEEP uint32_t oc_close(OcCoordinator *c,uint32_t *out) {
    if(!c || !out)return OC_INVALID;
    if(!enter(c))return OC_BUSY;
    if(c->closed)return leave(c,OC_BUSY);
    if(c->epoch==UINT32_MAX)return leave(c,OC_EXHAUSTED);
    c->closed=1;*out=++c->epoch;return leave(c,OC_OK);
}
static uint32_t drained(OcCoordinator *c,uint32_t epoch) {
    if(!epoch || !c->closed || epoch!=c->epoch)return OC_STALE;
    reap_runner(c);
    return c->running?OC_BUSY:OC_OK;
}
KEEP uint32_t oc_drained(OcCoordinator *c,uint32_t epoch) {
    if(!c)return OC_INVALID;
    if(!enter(c))return OC_BUSY;
    return leave(c,drained(c,epoch));
}
KEEP uint32_t oc_reopen(OcCoordinator *c,uint32_t epoch) {
    if(!c)return OC_INVALID;
    if(!enter(c))return OC_BUSY;
    uint32_t status=drained(c,epoch);
    if(!status && LD(&c->audio_fault))status=OC_FAULT;
    if(!status && LD(&c->audio_request) && LD(&c->audio_ack)!=epoch)status=OC_BUSY;
    if(!status){ST(&c->audio_request,0);c->closed=0;}
    return leave(c,status);
}
KEEP uint32_t oc_audio_request(OcCoordinator *c,uint32_t epoch) {
    if(!c)return OC_INVALID;
    if(!enter(c))return OC_BUSY;
    uint32_t status=drained(c,epoch);
    if(!status && LD(&c->audio_fault))status=OC_FAULT;
    if(!status && LD(&c->audio_request))status=OC_BUSY;
    if(!status){ST(&c->audio_ack,0);ST(&c->audio_request,epoch);}
    return leave(c,status);
}
KEEP uint32_t oc_audio_poll(OcCoordinator *c,uint32_t epoch) {
    if(!c)return OC_INVALID;
    if(!enter(c))return OC_BUSY;
    uint32_t status=drained(c,epoch);
    if(!status && LD(&c->audio_request)!=epoch)status=OC_STALE;
    if(!status && LD(&c->audio_fault))status=OC_FAULT;
    if(!status && LD(&c->audio_ack)!=epoch)status=OC_BUSY;
    return leave(c,status);
}
KEEP uint32_t oc_take_done(OcCoordinator *c,uint32_t ticket) {
    if(!c)return OC_INVALID;
    if(!enter(c))return OC_BUSY;
    OcJob *j=find(c,ticket);
    if(!j)return leave(c,OC_STALE);
    if(LD(&j->phase)!=OC_DONE)return leave(c,OC_BUSY);
    if(c->running==ticket)c->running=0;
    j->ticket=j->kind=j->args[0]=j->args[1]=0;ST(&j->phase,OC_FREE);
    return leave(c,OC_OK);
}
/* Emulator-only stock dispatch. Not a patched import table or UI entry hook. */
KEEP void oc_stock_dispatch(uint32_t kind,const uint32_t *args) {
    switch(kind) {
    case OC_EFFECT_A:((void (*)(uint32_t,uint32_t))0x8000e749)(args[0],args[1]);break;
    case OC_EFFECT_B:((void (*)(uint32_t,uint32_t))0x8000e7b1)(args[0],args[1]);break;
    case OC_MODE_A:((void (*)(void))0x80006ca9)();break;
    case OC_MODE_B:((void (*)(void))0x80006fc9)();break;
    case OC_MODE_C:((void (*)(void))0x8001d969)();break;
    }
}
