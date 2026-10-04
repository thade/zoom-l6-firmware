#include "usb_ownership.h"
#define KEEP __attribute__((used,retain))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
static UsOwner *binding;
static int lock(uint32_t *p){uint32_t z=0;return __atomic_compare_exchange_n(p,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);}
static int32_t unlock(uint32_t *p,int32_t r){__atomic_store_n(p,0,__ATOMIC_RELEASE);return r;}
static int32_t fail(UsOwner *s,uint32_t e) {
    uint32_t zero=0;__atomic_compare_exchange_n(&s->error,&zero,e?e:OWN_FAULT,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
    od_gate_fail(&s->ledger->gate);s->phase=US_FAILED;return OWN_FAULT;
}
KEEP int32_t us_error(UsOwner *s,uint32_t owner,uint32_t e) {
    if(!owner || owner!=LD(&s->owner))return OWN_STALE;
    if(!e)return OWN_CONFLICT;
    uint32_t zero=0;__atomic_compare_exchange_n(&s->error,&zero,e,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
    od_gate_fail(&s->ledger->gate);return OWN_OK;
}
KEEP int32_t us_fenced(void) {
    UsOwner *s=binding;
    return s && s->owner && s->phase>=US_READY && s->phase<=US_RELEASE && !LD(&s->error) &&
        LD(&s->ledger->gate.word)==OD_GATE_PROMOTING && s->port->quiescent()==1;
}
KEEP const RmPort us_reload_port={us_fenced};
KEEP int32_t us_init(UsOwner *s,OwnLedger *l,RmManager *m,const UsPort *p) {
    if(binding || !s || !l || !m || !p || !p->quiescent || !p->enter || !p->send || !p->worker ||
       !p->remount || !p->local_ready || m->port!=&us_reload_port || !m->runtime ||
       m->runtime->coordinator->ledger!=l)return OWN_CONFLICT;
    s->ledger=l;s->reload=m;s->port=p;binding=s;return OWN_OK;
}
KEEP int32_t us_begin(UsOwner *s,uint32_t profile) {
    if(binding!=s || profile>2)return OWN_CONFLICT;
    if(!lock(&s->lock))return OWN_BUSY;
    if(s->phase!=US_IDLE && s->phase!=US_DONE)return unlock(&s->lock,OWN_BUSY);
    s->profile=profile;s->command=0;s->reload_intent=0;s->error=0;s->phase=US_ADMIT;
    return unlock(&s->lock,OWN_OK);
}
static OwnRequest request(const UsRequest *p){OwnRequest r={OWN_CARD,{p->owner,p->operation,p->selector,p->parameter}};return r;}
KEEP int32_t us_queue(UsOwner *s,uint32_t selector,uint32_t parameter) {
    /* Synchronous producer boundary inside enter/STOP_SEND, under sole-owner
     * operation latch. No worker needs this latch to execute or report errors. */
    if(!s->lock || s->command || !s->owner ||
       (s->phase!=US_ENTER && s->phase!=US_STOP_SEND))return fail(s,OWN_CONFLICT);
    uint32_t op=s->phase==US_ENTER?US_START:US_STOP;
    if((op==US_START && selector!=6+2*s->profile) || (op==US_STOP && (selector!=0x800 || parameter)))return fail(s,OWN_CONFLICT);
    UsRequest p={s->owner,0,op,selector,parameter};OwnRequest r=request(&p);
    int32_t status=od_own_child(s->ledger,s->owner,&r,&p.child);
    if(status)return fail(s,status);
    s->command=p.child;
    if(od_own_offer(s->ledger,p.child))return fail(s,OWN_FAULT);
    int32_t outcome=s->port->send(&p);
    if(outcome<OWN_ACCEPTED || outcome>OWN_UNCERTAIN ||
       od_own_submitted(s->ledger,p.child,(uint32_t)outcome) ||
       od_own_producer_done(s->ledger,p.child,0))return fail(s,OWN_FAULT);
    if(outcome==OWN_NOT_SENT)return fail(s,OWN_FAULT);
    return OWN_OK;
}
KEEP int32_t us_receive(UsTask *t,const UsRequest *p) {
    if(!lock(&t->lock))return OWN_BUSY;
    if(t->phase && t->phase!=4)return unlock(&t->lock,OWN_BUSY);
    if(!p || !p->owner || !p->child || (p->operation!=US_START && p->operation!=US_STOP))return unlock(&t->lock,OWN_CONFLICT);
    t->request=*p;t->error=0;t->phase=1;return unlock(&t->lock,OWN_OK);
}
KEEP int32_t us_run(UsOwner *s,UsTask *t) {
    if(!lock(&t->lock))return OWN_BUSY;
    int32_t r=OWN_BUSY;
    if(t->phase==1) {
        if(t->request.owner!=LD(&s->owner)){t->phase=4;return unlock(&t->lock,OWN_STALE);}
        OwnRequest req=request(&t->request);
        r=od_own_claim(s->ledger,t->request.child,&req);
        if(r) {if(r==OWN_STALE || r==OWN_CONFLICT)t->phase=4;return unlock(&t->lock,r);}
        t->phase=2;t->error=(uint32_t)s->port->worker(&t->request);t->phase=3;
    }
    if(t->phase!=3)return unlock(&t->lock,OWN_STALE);
    if(t->error)us_error(s,t->request.owner,t->error);
    r=od_own_complete(s->ledger,t->request.child);
    if(!r)t->phase=4;
    return unlock(&t->lock,r);
}
KEEP int32_t us_exit(UsOwner *s,uint32_t owner,const RmPlan *p) {
    if(binding!=s || !p)return OWN_CONFLICT;
    if(!lock(&s->lock))return OWN_BUSY;
    if(!owner || owner!=s->owner)return unlock(&s->lock,OWN_STALE);
    if(s->phase!=US_HOST)return unlock(&s->lock,OWN_BUSY);
    const uint8_t *src=(const uint8_t *)p;uint8_t *dst=(uint8_t *)&s->plan;
    for(uint32_t i=0;i<sizeof(*p);i++)dst[i]=src[i];
    s->command=0;s->phase=US_STOP_SEND;return unlock(&s->lock,OWN_OK);
}
KEEP int32_t us_defer_reload(UsOwner *s) {
    if(!s->lock || s->phase!=US_MOUNT || s->reload_intent)return fail(s,OWN_CONFLICT);
    s->reload_intent=1;return OWN_OK;
}
KEEP int32_t us_step(UsOwner *s) {
    if(binding!=s)return OWN_CONFLICT;
    if(!lock(&s->lock))return OWN_BUSY;
    if(s->phase==US_IDLE || s->phase==US_DONE)return unlock(&s->lock,OWN_OK);
    if(s->phase==US_FAILED)return unlock(&s->lock,OWN_FAULT);
    int32_t r=OWN_BUSY;
    if(LD(&s->error) || LD(&s->ledger->gate.word)&OD_GATE_FAILED){r=OWN_FAULT;goto error;}
    if(s->phase==US_ADMIT) {
        if(s->port->quiescent()!=1)return unlock(&s->lock,OWN_BUSY);
        r=od_own_promote(s->ledger,&s->owner);if(r)goto error;s->phase=US_ENTER;
    }
    if(s->port->quiescent()!=1){r=OWN_FAULT;goto error;}
    if(s->phase==US_ENTER) {
        s->port->enter(s->profile);
        if(LD(&s->error) || !s->command){r=OWN_FAULT;goto error;}
        s->phase=US_ENTER_WAIT;
    }
    if(s->phase==US_ENTER_WAIT || s->phase==US_STOP_WAIT) {
        r=od_own_exclusive_drained(s->ledger,s->owner);if(r)goto error;
        if(s->phase==US_ENTER_WAIT){s->phase=US_HOST;return unlock(&s->lock,OWN_BUSY);}
        s->phase=US_MOUNT;
    }
    if(s->phase==US_HOST)return unlock(&s->lock,OWN_BUSY);
    if(s->phase==US_STOP_SEND) {
        r=us_queue(s,0x800,0);if(r)goto error;s->phase=US_STOP_WAIT;
        return unlock(&s->lock,OWN_BUSY);
    }
    if(s->phase==US_MOUNT) {
        s->port->remount();
        if(LD(&s->error) || !s->reload_intent){r=OWN_FAULT;goto error;}
        s->phase=US_READY;
    }
    if(s->phase==US_READY) {
        r=s->port->local_ready();if(r)goto error;s->phase=US_RELOAD_START;
    }
    if(s->phase==US_RELOAD_START) {
        r=rm_start(s->reload,&s->plan,s->owner);if(r)goto error;s->phase=US_RELOAD_WAIT;
    }
    if(s->phase==US_RELOAD_WAIT) {
        r=rm_completed(s->reload);if(r)goto error;s->phase=US_RELEASE;
    }
    if(s->phase==US_RELEASE) {
        r=od_own_promote_end(s->ledger,s->owner,0);if(r)goto error;
        s->owner=0;s->phase=US_DONE;
    }
    return unlock(&s->lock,OWN_OK);
error:
    if(r!=OWN_BUSY)r=fail(s,(uint32_t)r);
    return unlock(&s->lock,r);
}
KEEP void us_stock_enter(uint32_t profile){((void (*)(uint32_t,uint32_t))0x8000c221)(1,profile);}
KEEP const uint32_t us_layout[]={sizeof(UsOwner),sizeof(UsTask),sizeof(UsRequest),sizeof(UsPort)};
