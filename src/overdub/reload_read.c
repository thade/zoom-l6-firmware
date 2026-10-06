#include "reload_read.h"
#define KEEP __attribute__((used,retain))
static int lock(RrRead *r) {
    uint32_t z=0;return __atomic_compare_exchange_n(&r->lock,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(RrRead *r,int32_t s){__atomic_store_n(&r->lock,0,__ATOMIC_RELEASE);return s;}
static int32_t begin(RlCoordinator *c,RrRead *r,const RlEnvelope *tag,const uint32_t *a,uint32_t handle) {
    if(!lock(r))return OWN_BUSY;
    if(r->phase!=RR_EMPTY && r->phase!=RR_DONE)return leave(r,OWN_BUSY);
    if(a[0]>3 || !a[1] || !a[2] || a[1]>UINT32_MAX-a[2])return leave(r,OWN_CONFLICT);
    OwnRequest request={OWN_SESSION,{a[0],a[1],a[2],handle}};uint32_t ticket=0;
    int32_t s=rl_read_reserve(c,tag,&request,&ticket);
    if(s)return leave(r,s);
    r->tag=*tag;r->request=request;r->ticket=ticket;r->coordinator=c;
    r->actual=0;r->raw_status=0;r->error=0;r->queue_state=0;r->phase=RR_RESERVED;
    return leave(r,OWN_OK);
}
KEEP int32_t rr_begin(RlCoordinator *c,RrRead *r,const RlEnvelope *tag,const uint32_t *a) {
    return begin(c,r,tag,a,0);
}
KEEP int32_t rr_begin_handle(RlCoordinator *c,RrRead *r,const RlEnvelope *tag,const uint32_t *a) {
    if(!a[3])return OWN_CONFLICT;
    return begin(c,r,tag,a,a[3]);
}
KEEP int32_t rr_ready(RlCoordinator *c,RrRead *r,uint32_t ticket) {
    if(!lock(r))return OWN_BUSY;
    if(c!=r->coordinator)return leave(r,OWN_CONFLICT);
    if(!ticket || ticket!=r->ticket)return leave(r,OWN_STALE);
    int32_t s;
    if(r->phase==RR_RESERVED) {
        s=od_own_offer(c->ledger,ticket);if(s)return leave(r,s);r->phase=RR_OFFERED;
    }
    if(r->phase==RR_OFFERED) {
        s=od_own_submitted(c->ledger,ticket,OWN_ACCEPTED);if(s)return leave(r,s);r->phase=RR_SUBMITTED;
    }
    if(r->phase==RR_SUBMITTED) {
        s=od_own_claim(c->ledger,ticket,&r->request);if(s)return leave(r,s);r->phase=RR_RUNNING;
    }
    return leave(r,r->phase==RR_RUNNING?OWN_OK:OWN_CONFLICT);
}
KEEP int32_t rr_observe(RrRead *r,uint32_t ticket,uint32_t status,uint32_t actual) {
    if(!lock(r))return OWN_BUSY;
    if(!ticket || ticket!=r->ticket)return leave(r,OWN_STALE);
    if(r->phase!=RR_RUNNING)return leave(r,OWN_CONFLICT);
    r->raw_status=status;r->actual=actual;
    r->error=status?status:actual!=r->request.args[2]?RR_SHORT_READ:0;
    r->phase=RR_OBSERVED;return leave(r,OWN_OK);
}
KEEP int32_t rr_finish(RlCoordinator *c,RrRead *r,uint32_t ticket) {
    if(!lock(r))return OWN_BUSY;
    if(c!=r->coordinator)return leave(r,OWN_CONFLICT);
    if(!ticket || ticket!=r->ticket)return leave(r,OWN_STALE);
    if(r->queue_state && r->queue_state!=3)return leave(r,OWN_BUSY);
    int32_t s;
    if(r->phase==RR_OBSERVED) {
        if(r->error){s=rl_io_error(c,&r->tag,r->error);if(s)return leave(r,s);}
        r->phase=RR_JOIN;
    }
    if(r->phase!=RR_JOIN)return leave(r,r->phase==RR_RUNNING?OWN_BUSY:OWN_CONFLICT);
    s=od_own_finish_session(c->ledger,ticket);
    if(!s)r->phase=RR_DONE;
    return leave(r,s);
}
KEEP const uint32_t rr_read_layout[]={sizeof(RrRead)};
KEEP int32_t rr_queue_packet(RrRead *r,uint32_t ticket,uint32_t slot,uint32_t *out) {
    if(!lock(r))return OWN_BUSY;
    if(!ticket || r->ticket!=ticket)return leave(r,OWN_STALE);
    if(slot>=RR_QUEUE_SLOTS || r->phase!=RR_RUNNING || r->queue_state)return leave(r,OWN_CONFLICT);
    out[0]=RR_QUEUE_MAGIC;out[1]=slot;out[2]=ticket;out[3]=0;
    r->queue_state=1;return leave(r,OWN_OK);
}
static int task_lock(RrQueueTask *t) {
    uint32_t z=0;return __atomic_compare_exchange_n(&t->lock,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t task_leave(RrQueueTask *t,int32_t s){__atomic_store_n(&t->lock,0,__ATOMIC_RELEASE);return s;}
KEEP int32_t rr_queue_decode(RrRead *const *slots,RrQueueTask *t,const uint32_t *words,uint32_t *out) {
    if(!task_lock(t))return OWN_BUSY;
    if(t->read)return task_leave(t,OWN_BUSY);
    if(words[0]==0 || words[0]==1) {
        for(uint32_t i=0;i<4;i++)out[i]=words[i];
        return task_leave(t,RR_QUEUE_FORWARD);
    }
    if(words[0]!=RR_QUEUE_MAGIC || words[1]>=RR_QUEUE_SLOTS || !words[2] || words[3])
        return task_leave(t,OWN_CONFLICT);
    RrRead *r=slots[words[1]];
    if(!r)return task_leave(t,OWN_STALE);
    if(!lock(r))return task_leave(t,OWN_BUSY);
    int32_t s=OWN_STALE;
    if(r->ticket==words[2] && r->phase==RR_RUNNING && r->queue_state==1) {
        out[0]=0;out[1]=r->request.args[0];out[2]=r->request.args[1];out[3]=r->request.args[2];
        r->queue_state=2;t->read=r;t->ticket=r->ticket;s=OWN_OK;
    }
    leave(r,OWN_OK);return task_leave(t,s);
}
KEEP int32_t rr_queue_observe(RrQueueTask *t,uint32_t status,uint32_t actual) {
    if(!task_lock(t))return OWN_BUSY;
    if(!t->read)return task_leave(t,OWN_STALE);
    return task_leave(t,rr_observe(t->read,t->ticket,status,actual));
}
KEEP int32_t rr_queue_return(RrQueueTask *t) {
    if(!task_lock(t))return OWN_BUSY;
    RrRead *r=t->read;
    if(!r)return task_leave(t,OWN_STALE);
    if(!lock(r))return task_leave(t,OWN_BUSY);
    int32_t s=OWN_STALE;
    if(r->ticket==t->ticket && r->queue_state==2) {
        s=OWN_BUSY;
        if(r->phase==RR_OBSERVED) {
            r->queue_state=3;t->read=0;t->ticket=0;s=OWN_OK;
        }
    }
    leave(r,OWN_OK);return task_leave(t,s);
}
