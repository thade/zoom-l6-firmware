#include "ordinary_io.h"
#define KEEP __attribute__((used,retain))
static int lock(uint32_t *p) {
    uint32_t z=0;return __atomic_compare_exchange_n(p,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(uint32_t *p,int32_t s){__atomic_store_n(p,0,__ATOMIC_RELEASE);return s;}
KEEP int32_t oi_begin(RlCoordinator *c,OiIo *o,const OiRequest *r) {
    if(!c || !o || !r || pf_ready(c) || r->kind>1 || r->pad>3 ||
       r->pin_slot<2 || r->pin_slot>=PF_PIN_SLOTS ||
       (!r->kind && (!r->first || r->first>UINT32_MAX-r->second)))return OWN_CONFLICT;
    if(!lock(&o->lock))return OWN_BUSY;
    if(o->phase!=OI_EMPTY && o->phase!=OI_DONE)return leave(&o->lock,OWN_BUSY);
    o->coordinator=c;o->request=*r;o->scope=(OwnRequest){OWN_SESSION,{r->kind,r->pad,r->first,r->second}};
    o->ticket=o->handle=o->pin=o->status=o->actual=0;o->phase=OI_NEW;
    return leave(&o->lock,OWN_OK);
}
KEEP int32_t oi_prepare(OiIo *o) {
    if(!lock(&o->lock))return OWN_BUSY;
    if(o->phase<OI_NEW || o->phase>OI_READY)return leave(&o->lock,OWN_CONFLICT);
    OwnLedger *l=o->coordinator->ledger;int32_t s;
    if(o->phase==OI_NEW) {
        s=o->request.parent?od_own_child(l,o->request.parent,&o->scope,&o->ticket):od_own_reserve(l,&o->scope,&o->ticket);
        if(s)return leave(&o->lock,s);o->phase=OI_RESERVED;
    }
    if(o->phase==OI_RESERVED) {
        uint32_t pin[2];s=pf_pin(o->coordinator,o->request.pin_slot,o->request.pad,pin);
        if(s)return leave(&o->lock,s);
        o->handle=pin[0];o->pin=pin[1];o->phase=OI_PINNED;
    }
    if(o->phase==OI_PINNED) {
        s=od_own_offer(l,o->ticket);if(s)return leave(&o->lock,s);o->phase=OI_OFFERED;
    }
    if(o->phase==OI_OFFERED) {
        /* This accepts our internal lifetime scope, not delivery to an RTOS
         * queue. Missing/uncertain delivery cannot reach RETURNED/retirement. */
        s=od_own_submitted(l,o->ticket,OWN_ACCEPTED);if(s)return leave(&o->lock,s);o->phase=OI_SUBMITTED;
    }
    if(o->phase==OI_SUBMITTED) {
        s=od_own_claim(l,o->ticket,&o->scope);if(s)return leave(&o->lock,s);o->phase=OI_READY;
    }
    return leave(&o->lock,OWN_OK);
}
KEEP int32_t oi_packet(OiIo *o,uint32_t slot,uint32_t *out) {
    if(!out || slot>=OI_SLOTS)return OWN_CONFLICT;
    if(!lock(&o->lock))return OWN_BUSY;
    if(o->phase!=OI_READY)return leave(&o->lock,OWN_CONFLICT);
    out[0]=OI_MAGIC;out[1]=slot;out[2]=o->ticket;out[3]=0;o->phase=OI_QUEUED;
    return leave(&o->lock,OWN_OK);
}
KEEP int32_t oi_decode(OiIo *const *slots,OiTask *t,const uint32_t *w,uint32_t *out) {
    if(!slots || !t || !w || !out || w[0]!=OI_MAGIC || w[1]>=OI_SLOTS || !w[2] || w[3])return OWN_CONFLICT;
    if(!lock(&t->lock))return OWN_BUSY;
    if(t->io)return leave(&t->lock,OWN_BUSY);
    OiIo *o=slots[w[1]];
    if(!o)return leave(&t->lock,OWN_STALE);
    if(!lock(&o->lock))return leave(&t->lock,OWN_BUSY);
    int32_t s=OWN_STALE;
    if(o->ticket==w[2] && o->phase==OI_QUEUED) {
        out[0]=o->request.kind;out[1]=o->request.pad;out[2]=o->request.first;out[3]=o->request.second;
        o->phase=OI_RUNNING;t->io=o;t->ticket=o->ticket;s=OWN_OK;
    }
    leave(&o->lock,s);return leave(&t->lock,s);
}
KEEP int32_t oi_check(OiTask *t,uint32_t h,uint32_t a,uint32_t b) {
    if(!lock(&t->lock))return OWN_BUSY;
    OiIo *o=t->io;if(!o)return leave(&t->lock,OWN_STALE);
    if(!lock(&o->lock))return leave(&t->lock,OWN_BUSY);
    int32_t s=o->ticket!=t->ticket?OWN_STALE:o->phase!=OI_RUNNING || h!=o->handle ||
        a!=o->request.first || b!=o->request.second?OWN_CONFLICT:OWN_OK;
    leave(&o->lock,s);return leave(&t->lock,s);
}
KEEP int32_t oi_observe(OiTask *t,uint32_t status,uint32_t actual) {
    if(!lock(&t->lock))return OWN_BUSY;
    OiIo *o=t->io;if(!o)return leave(&t->lock,OWN_STALE);
    if(!lock(&o->lock))return leave(&t->lock,OWN_BUSY);
    int32_t s=OWN_CONFLICT;
    if(o->ticket!=t->ticket)s=OWN_STALE;
    else if(o->phase==OI_RUNNING) {o->status=status;o->actual=actual;o->phase=OI_OBSERVED;s=OWN_OK;}
    leave(&o->lock,s);return leave(&t->lock,s);
}
KEEP int32_t oi_return(OiTask *t) {
    if(!lock(&t->lock))return OWN_BUSY;
    OiIo *o=t->io;if(!o)return leave(&t->lock,OWN_STALE);
    if(!lock(&o->lock))return leave(&t->lock,OWN_BUSY);
    int32_t s=OWN_BUSY;
    if(o->ticket!=t->ticket)s=OWN_STALE;
    else if(o->phase==OI_OBSERVED){o->phase=OI_RETURNED;t->io=0;t->ticket=0;s=OWN_OK;}
    leave(&o->lock,s);return leave(&t->lock,s);
}
KEEP int32_t oi_finish(OiIo *o) {
    if(!lock(&o->lock))return OWN_BUSY;
    int32_t s;
    if(o->phase==OI_RETURNED) {
        s=pf_drop(o->request.pin_slot,o->pin);if(s)return leave(&o->lock,s);o->phase=OI_UNPINNED;
    }
    if(o->phase==OI_UNPINNED) {
        s=od_own_finish_session(o->coordinator->ledger,o->ticket);
        if(s)return leave(&o->lock,s);o->phase=OI_DONE;
    }
    return leave(&o->lock,o->phase==OI_DONE?OWN_OK:OWN_BUSY);
}
KEEP int32_t oi_result(OiIo *o,uint32_t *out) {
    if(!out)return OWN_CONFLICT;
    if(!lock(&o->lock))return OWN_BUSY;
    if(o->phase!=OI_DONE)return leave(&o->lock,OWN_BUSY);
    out[0]=o->status;out[1]=o->actual;return leave(&o->lock,OWN_OK);
}
