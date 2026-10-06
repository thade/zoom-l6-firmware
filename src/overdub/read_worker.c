#include "read_worker.h"
#define KEEP __attribute__((used,retain))
#define W(a) (*(volatile uint32_t *)(a))
#define READ_ERROR UINT32_C(0xffff0004)
enum {RW_IDLE,RW_PACKET,RW_BODY,RW_FAILED};
typedef struct {
    RwBinding binding;
    uint32_t bound,lock,phase,packet[4];
    RrQueueTask task;
    uint32_t result_ready,status,actual,error;
    RwOrdinary ordinary;OiTask operation;uint32_t ordinary_bound,started;
} RwState;
static RwState state;
KEEP const uint32_t rw_layout[]={sizeof(RwBinding),sizeof(RwState)};
static int lock(void) {
    uint32_t z=0;return __atomic_compare_exchange_n(&state.lock,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(int32_t s){__atomic_store_n(&state.lock,0,__ATOMIC_RELEASE);return s;}
static int context(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    return state.bound && !ipsr && W(0x80446dc4u)==state.binding.worker &&
        W(0x801f8f30u)==state.binding.queue &&
        ((uint32_t (*)(void))0x800770e9u)()==state.binding.worker;
}
static int32_t fault(void) {
    state.error=READ_ERROR;state.phase=RW_FAILED;
    if(state.bound)od_gate_fail(&state.binding.coordinator->ledger->gate);
    return -1;
}
static int32_t pause(void) {
    leave(-1);state.binding.yield();return -1;
}
KEEP int32_t rw_can_bind(const RwBinding *b) {
    if(state.bound || !b || !b->coordinator || !b->coordinator->ledger || !b->worker || !b->queue ||
       b->worker!=W(0x80446dc4u) || b->queue!=W(0x801f8f30u) || !b->receive || !b->read || !b->yield)
        return OWN_CONFLICT;
    uint32_t count=0;
    for(uint32_t i=0;i<RR_QUEUE_SLOTS;i++)if(b->slots[i]) {
        if((uintptr_t)b->slots[i]&3u)return OWN_CONFLICT;
        for(uint32_t j=0;j<i;j++)if(b->slots[i]==b->slots[j])return OWN_CONFLICT;
        count++;
    }
    if(!count)return OWN_CONFLICT;
    return OWN_OK;
}
KEEP int32_t rw_bind(const RwBinding *b) {
    int32_t result=rw_can_bind(b);if(result)return result;
    state.binding=*b;state.bound=1;return OWN_OK;
}
KEEP int32_t rw_can_bind_ordinary(const RwOrdinary *b) {
    if(!state.bound || state.ordinary_bound || !b || b->coordinator!=state.binding.coordinator ||
       !b->seek || pf_ready(b->coordinator) || W(0x80446dc4u)!=state.binding.worker ||
       W(0x801f8f30u)!=state.binding.queue)return OWN_CONFLICT;
    if(state.started || state.lock || state.phase!=RW_IDLE || b->coordinator->lock ||
       b->coordinator->ledger->lock || b->coordinator->ledger->gate.word ||
       b->coordinator->cleanup || b->coordinator->draining || b->coordinator->manager)return OWN_BUSY;
    for(uint32_t i=0;i<RL_SLOTS;i++)if(b->coordinator->jobs[i].owner)return OWN_BUSY;
    for(uint32_t i=0;i<OI_SLOTS;i++) {
        if(!b->slots[i] || ((uintptr_t)b->slots[i]&3u))return OWN_CONFLICT;
        for(uint32_t j=0;j<i;j++)if(b->slots[i]==b->slots[j])return OWN_CONFLICT;
        if(b->slots[i]->lock || b->slots[i]->phase || b->slots[i]->ticket)return OWN_BUSY;
    }
    return OWN_OK;
}
KEEP int32_t rw_bind_ordinary(const RwOrdinary *b) {
    int32_t s=rw_can_bind_ordinary(b);if(s)return s;
    state.ordinary=*b;state.ordinary_bound=1;return OWN_OK;
}
KEEP int32_t rw_next(uint32_t queue,uint32_t *out) {
    if(!context())return -1;
    if(!lock())return -1;
    state.started=1;
    if(queue!=state.binding.queue || !out){fault();return pause();}
    if(state.phase==RW_FAILED)return pause();
    int32_t s;
    if(state.phase==RW_BODY) {
        if(state.operation.io) {
            if(!state.result_ready){fault();return pause();}
            if(state.result_ready==1) {
                s=oi_observe(&state.operation,state.status,state.actual);
                if(s==OWN_BUSY)return pause();
                if(s){fault();return pause();}
                state.result_ready=2;
            }
            s=oi_return(&state.operation);
            if(s==OWN_BUSY)return pause();
            if(s){fault();return pause();}
        }
        if(state.task.read) {
            if(!state.result_ready){fault();return pause();}
            if(state.result_ready==1) {
                s=rr_queue_observe(&state.task,state.status,state.actual);
                if(s==OWN_BUSY)return pause();
                if(s){fault();return pause();}
                state.result_ready=2;
            }
            s=rr_queue_return(&state.task);
            if(s==OWN_BUSY)return pause();
            if(s){fault();return pause();}
        }
        state.result_ready=0;state.phase=RW_IDLE;
    }
    if(state.phase==RW_IDLE) {
        if(state.binding.receive(queue,state.packet))return pause();
        state.phase=RW_PACKET;
    }
    if(state.ordinary_bound && state.packet[0]==OI_MAGIC)
        s=oi_decode(state.ordinary.slots,&state.operation,state.packet,out);
    else {
        if(state.ordinary_bound && state.packet[0]!=RR_QUEUE_MAGIC){fault();return pause();}
        s=rr_queue_decode(state.binding.slots,&state.task,state.packet,out);
    }
    if(s==OWN_BUSY)return pause();
    if(s==OWN_STALE){state.phase=RW_IDLE;return pause();}
    if(s!=OWN_OK && s!=RR_QUEUE_FORWARD){fault();return pause();}
    if(state.task.read && state.task.read->coordinator!=state.binding.coordinator){fault();return pause();}
    if(state.operation.io && state.operation.io->coordinator!=state.binding.coordinator){fault();return pause();}
    state.phase=RW_BODY;return leave(0);
}
KEEP int32_t rw_read(uint32_t handle,uint32_t buffer,uint32_t bytes,uint32_t *actual) {
    if(!context())return READ_ERROR;
    if(!lock())return READ_ERROR;
    if(state.phase!=RW_BODY || !actual){fault();leave(-1);return READ_ERROR;}
    if(state.operation.io) {
        *actual=0;int32_t s;
        while((s=oi_check(&state.operation,handle,buffer,bytes))==OWN_BUSY)state.binding.yield();
        if(s || state.result_ready || state.operation.io->request.kind!=0 ||
           handle!=W(0x80735b24u+20*state.operation.io->request.pad)) {
            fault();leave(-1);return READ_ERROR;
        }
    }
    if(state.task.read) {
        const OwnRequest *r=&state.task.read->request;
        if(state.result_ready || !handle || buffer!=r->args[1] || bytes!=r->args[2] ||
           (r->args[3] && handle!=r->args[3]) ||
           handle!=W(0x80735b24u+20*r->args[0])) {
            *actual=0;fault();leave(-1);return READ_ERROR;
        }
        *actual=0;
    }
    int32_t result=state.binding.read(handle,buffer,bytes,actual);
    if(state.task.read || state.operation.io) {
        state.status=(uint32_t)result;state.actual=*actual;state.result_ready=1;
    }
    return leave(result);
}
KEEP int32_t rw_seek(uint32_t handle,uint32_t offset,uint32_t origin) {
    if(!context() || !lock())return READ_ERROR;
    if(state.phase!=RW_BODY || !state.ordinary_bound || !state.operation.io || state.task.read) {
        fault();leave(-1);return READ_ERROR;
    }
    int32_t s;
    while((s=oi_check(&state.operation,handle,offset,origin))==OWN_BUSY)state.binding.yield();
    if(s || state.result_ready || state.operation.io->request.kind!=1 ||
       handle!=W(0x80735b24u+20*state.operation.io->request.pad)) {
        fault();leave(-1);return READ_ERROR;
    }
    int32_t result=state.ordinary.seek(handle,offset,origin);
    state.status=(uint32_t)result;state.actual=0;state.result_ready=1;
    return leave(result);
}
