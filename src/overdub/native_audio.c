#include "native_audio.h"
#define KEEP __attribute__((used,retain))
#define W(a) (*(volatile uint32_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
static OcCoordinator *control;
static uint32_t task_id,phase,token;
static uint32_t started;
static void (*capture_hook)(uint32_t,uint32_t);
static uint32_t activation,ready;
enum {NA_UNBOUND,NA_PREPARED,NA_ARMED,NA_ENABLED};
enum {NA_IDLE,NA_NULL,NA_ACTIVE,NA_FAILED};
static void fault(void) {
    if(control)__atomic_store_n(&control->audio_fault,1,__ATOMIC_RELEASE);
}
KEEP __attribute__((noinline)) uint32_t na_thread_context(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    return ipsr==0;
}
static int context(void) {
    return control && na_thread_context() && W(0x80446d78u)==task_id &&
        ((uint32_t (*)(void))0x800770e9u)()==task_id;
}
static uint32_t bind_control(OcCoordinator *c,uint32_t id) {
    if(control || !c || !id || id!=W(0x80446d78u))return OC_INVALID;
    if(c->lock || c->sequence || c->epoch || c->closed || c->running ||
       c->audio_request || c->audio_ack || c->audio_fault || c->audio_sequence ||
       c->audio_active || c->audio_epoch || c->audio_primary || c->audio_secondary)return OC_BUSY;
    for(uint32_t i=0;i<OC_SLOTS;i++)if(c->jobs[i].phase || c->jobs[i].ticket)return OC_BUSY;
    task_id=id;control=c;return OC_OK;
}
KEEP uint32_t na_bind(OcCoordinator *c,uint32_t id) {
    uint32_t s=bind_control(c,id);if(!s)ST(&activation,NA_ENABLED);return s;
}
KEEP void na_begin(uint32_t loaded) {
    started=1;
    if(!context()){fault();return;}
    if(phase!=NA_IDLE){fault();return;}
    if(!loaded){phase=NA_NULL;return;}
    token=oc_audio_begin(control,loaded,W(0x20016d54u));
    phase=token?NA_ACTIVE:NA_FAILED;
}
KEEP void na_end(void) {
    started=1;
    if(!context()){fault();return;}
    if(phase==NA_NULL){phase=NA_IDLE;return;}
    if(phase!=NA_ACTIVE){fault();return;}
    uint32_t result=oc_audio_end(control,token,W(0x20015e10u),W(0x20016d54u));
    phase=result==OC_OK?NA_IDLE:NA_FAILED;token=0;
}
KEEP uint32_t na_bind_capture(void (*hook)(uint32_t,uint32_t),uint32_t (*enable)(void)) {
    if(!control || !hook || !enable || capture_hook)return OC_INVALID;
    if(started || phase!=NA_IDLE || control->audio_sequence || control->audio_fault ||
       control->closed || control->running || control->lock)return OC_BUSY;
    if(enable())return OC_BUSY;
    capture_hook=hook;return OC_OK;
}
KEEP uint32_t na_prepare(OcCoordinator *c,uint32_t id,
                        void (*hook)(uint32_t,uint32_t),uint32_t (*check)(void)) {
    if(!hook || !check)return OC_INVALID;
    uint32_t s=bind_control(c,id);if(s)return s;
    s=na_bind_capture(hook,check);
    if(s){fault();return s;} /* Partial initialization cannot be retried. */
    ST(&activation,NA_PREPARED);return OC_OK;
}
KEEP uint32_t na_arm(void) {
    if(!control || !capture_hook || !na_thread_context() || !W(0x801f9048u) ||
       !W(0x80446da4u) || ((uint32_t (*)(void))0x800770e9u)()!=W(0x80446da4u))return OC_INVALID;
    if(LD(&control->audio_fault))return OC_FAULT;
    uint32_t state=LD(&activation);
    if(state==NA_ARMED || state==NA_ENABLED)return OC_OK;
    if(state!=NA_PREPARED)return OC_INVALID;
    ST(&activation,NA_ARMED);return OC_OK;
}
KEEP uint32_t na_ready(void) {
    if(!control || LD(&control->audio_fault))return OC_FAULT;
    return LD(&ready)?OC_OK:OC_BUSY;
}
/* Completion brackets capture too: no ack can be visible until capture's
 * matching return has released its session reservation. Both calls are bounded
 * and perform no IO. Faulted completion still lets balanced capture calls drain.
 * A wrong task must not attach to or release the AudioProcess capture scope. */
KEEP void na_observe_begin(uint32_t loaded) {
    uint32_t state=LD(&activation);
    if(state<NA_ARMED)return;
    started=1;
    if(!context()){fault();return;}
    if(state==NA_ARMED)ST(&activation,NA_ENABLED);
    na_begin(loaded);
    if(capture_hook)capture_hook(10,loaded);
}
KEEP void na_observe_end(void) {
    if(LD(&activation)!=NA_ENABLED)return;
    started=1;
    if(!context()){fault();return;}
    if(capture_hook)capture_hook(11,0);
    na_end();
    if(phase==NA_IDLE && control->audio_sequence && !LD(&control->audio_fault))ST(&ready,1);
}
