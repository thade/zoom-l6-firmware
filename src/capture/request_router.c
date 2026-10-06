/* Emulator-only ownership layer. Caller supplies a fresh zeroed Request per
 * invocation and transports that exact object with its queue job. No global
 * "current request" inference. Stock queue tagging remains an adapter obligation.
 * All router operations require external serialization in this first version;
 * audio/extra-file worker may run between operations using bridge reservations.
 * Request storage stays alive until rr_released returns true; no object reuse. */
#include "request_router.h"
#include <stddef.h>
#include "retention.h"
KEEP const uint32_t rr_layout[]={sizeof(Router),sizeof(Request),offsetof(Request,stamp)};
extern uint32_t bridge_route_enable(void*,uint32_t),bridge_route_hold(void*,uint32_t);
extern void bridge_route_release(void*),bridge_route_fault(void*,uint32_t,uint32_t);
extern uint32_t bridge_route_snapshot(void*,uint32_t,uint32_t,uint64_t*);
extern uint32_t bridge_route_event(void*,uint32_t,uint32_t,const uint64_t*);
extern uint32_t bridge_route_admit(void*,uint32_t);
static uint32_t fail(Request *q,uint32_t reason) {
    if(q->owner && q->owner==q->router->owner)
        bridge_route_fault(q->router->bridge,q->session,reason);
    return reason;
}
static void release(Request *q) {
    if(q->held){q->held=0;q->router->pending--;bridge_route_release(q->router->bridge);}
}
static int valid(Router *r,Request *q) {
    return q->router==r && q->session==r->session && q->id && q->held;
}
KEEP uint32_t rr_init(Router *r,void *bridge,uint32_t session) {
    if(r->bridge || !session)return 12;
    uint32_t s=bridge_route_enable(bridge,session);if(s)return s;
    r->bridge=bridge;r->session=session;return 0;
}
KEEP uint32_t rr_begin(Router *r,Request *q) {
    if(q->id || r->next==UINT32_MAX || !r->bridge)return 12;
    uint32_t s=bridge_route_hold(r->bridge,r->session);if(s)return s;
    q->router=r;q->session=r->session;q->id=++r->next;q->held=1;
    q->snapshot=18;r->pending++;return 0;
}
KEEP uint32_t rr_snapshot(Router *r,Request *q,uint32_t selected) {
    if(!valid(r,q) || q->state)return 12;
    q->selected=selected;
    q->snapshot=bridge_route_snapshot(r->bridge,r->session,selected,&q->stamp);
    return q->snapshot; /* A bad ignored request must not fault another take. */
}
KEEP uint32_t rr_ignore(Router *r,Request *q) {
    if(!valid(r,q) || q->state)return 12;
    q->state=4;release(q);return 0;
}
KEEP uint32_t rr_submit(Router *r,Request *q,uint32_t kind) {
    if(!valid(r,q) || q->state || (kind!=3 && kind!=4))return 12;
    if(kind==4 && !r->owner)return 12;
    uint32_t overlap=kind==3 && r->owner;
    if(kind==3 && !overlap)r->owner=q->id;
    q->owner=r->owner;q->kind=kind;q->state=1;
    /* The stock producer can still queue this request. Keep its reservation
     * until its actual send/delivery finishes, even though capture is cancelled. */
    if(overlap)return fail(q,24);
    if(kind==3) {
        if(q->snapshot)return fail(q,q->snapshot);
        uint32_t s=bridge_route_event(r->bridge,r->session,3,&q->stamp);
        if(s)return fail(q,s);
    }
    return 0;
}
/* outcome 0=confirmed queued, 1=confirmed not queued, 2=unknown. Unknown
 * cancels eligibility but retains storage/ownership until callback completion
 * plus a definitive outcome or an external drain fence (not supplied here). */
KEEP uint32_t rr_sent(Router *r,Request *q,uint32_t outcome) {
    if(!valid(r,q) || !q->state || q->sent || outcome>2)return 12;
    if(outcome==2)return fail(q,22);
    q->sent=outcome==0?1:2;
    if(outcome==1) {
        fail(q,q->delivered?23:16);
        if(!q->delivered){q->state=4;release(q);return 16;}
    }
    if(q->state==3)release(q);
    return outcome?23:0;
}
KEEP uint32_t rr_dispatch(Router *r,Request *q) {
    if(!valid(r,q) || q->owner!=r->owner || q->state!=1 || q->delivered || q->sent==2)return 12;
    q->delivered=1;q->state=2;return 0;
}
KEEP uint32_t rr_mark(Router *r,Request *q,uint32_t selected) {
    if(!valid(r,q) || q->owner!=r->owner || q->state!=2 || q->marked)return 12;
    q->marked=1;uint32_t s;
    if(q->kind==3) {
        /* Stock still uses a global saved cursor. Do not silently pair an
         * owned extra start with a different start used by ordinary streams. */
        if(*(volatile uint32_t*)0x80443154u!=q->selected)return fail(q,25);
        s=bridge_route_admit(r->bridge,r->session);
    }
    else {
        s=bridge_route_snapshot(r->bridge,r->session,selected,&q->stamp);
        if(!s)s=bridge_route_event(r->bridge,r->session,4,&q->stamp);
    }
    return s?fail(q,s):0;
}
KEEP uint32_t rr_complete(Router *r,Request *q) {
    if(!valid(r,q) || q->state!=2)return 12;
    if(!q->marked)fail(q,16);
    q->state=3;if(q->sent)release(q);
    return q->marked?0:16;
}
KEEP uint32_t rr_released(const Request *q) {return q->id && !q->held;}
KEEP uint32_t rr_finish_request(Router *r,Request *q) {
    if(!valid(r,q))return q->state?0:12;
    return q->state?0:rr_ignore(r,q);
}
KEEP void rr_hook(void *opaque,uint32_t kind,uint32_t selected) {
    Request *q=opaque;Router *r=q->router;
    if(!r)return;
    if(kind==3)(void)rr_snapshot(r,q,selected);
    else if(kind==7) {
        uint32_t s=rr_submit(r,q,3);
        if(s && r->owner)bridge_route_fault(r->bridge,r->session,s==11?24:s);
    }
    else if(kind==8)(void)rr_submit(r,q,4);
    /* Wrapper failure alone has no proven queue-drain/reclamation contract. */
    else if(kind==9)(void)rr_sent(r,q,selected==0?0:2);
    else if(kind==4 || kind==5) {
        if((kind==4 && q->kind==4) || (kind==5 && q->kind==3))
            (void)rr_mark(r,q,selected);
        else (void)fail(q,12);
    }
    /* Rejection is classification, not a fault of another owned take. The
     * adapter calls rr_finish_request after every original request return. */
}
