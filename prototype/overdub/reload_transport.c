#include "reload_transport.h"
#define KEEP __attribute__((used,retain))
#define CALLBACK UINT32_C(0x80049da1)
#define BOUNDARY_ERROR UINT32_C(0xffff0001)
#define SHORT_WRITE UINT32_C(0xffff0002)
static int lock(uint32_t *p) {
    uint32_t zero=0;
    return __atomic_compare_exchange_n(p,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t unlock(uint32_t *p,int32_t r){__atomic_store_n(p,0,__ATOMIC_RELEASE);return r;}
static int32_t fault(RtRuntime *r){od_gate_fail(&r->coordinator->ledger->gate);return OWN_FAULT;}
static int event_valid(const uint32_t *b){return b[0]==1 && b[1]==4 && b[2]==26 && !b[3] && !b[4];}
static void error(RtTask *t,uint32_t value){if(value && !t->error)t->error=value;}
static int running(RtTask *t){return t->lock && t->phase==RT_RUNNING;}
static int32_t produce(RtRuntime *r,RtProducer *p,uint32_t parent,uint32_t token) {
    if(!lock(&p->lock))return OWN_BUSY;
    if(p->owner)return unlock(&p->lock,OWN_CONFLICT);
    int32_t status=token?rl_begin_managed(r->coordinator,token,parent,&p->owner):rl_begin(r->coordinator,parent,&p->owner);
    if(status)return unlock(&p->lock,status);
    p->sends=0;p->body_result=r->port->producer();
    /* An uncertain metadata transition after a stock call cannot be retried by
     * repeating the stock operation. Retain the owner and fault closed. */
    if(p->sends!=1 || rl_producer_return(r->coordinator,p->owner))return unlock(&p->lock,fault(r));
    return unlock(&p->lock,OWN_OK);
}
KEEP int32_t rt_produce(RtRuntime *r,RtProducer *p,uint32_t parent) {return produce(r,p,parent,0);}
KEEP int32_t rt_produce_managed(RtRuntime *r,RtProducer *p,uint32_t parent,uint32_t token) {return produce(r,p,parent,token);}
KEEP int32_t rt_queue(RtRuntime *r,RtProducer *p,const uint32_t *body) {
    if(!p->lock || !p->owner || p->sends || body[0]!=CALLBACK){fault(r);return BOUNDARY_ERROR;}
    RtWorkerPacket packet;
    if(rl_envelope(r->coordinator,p->owner,RL_WORKER,&packet.tag)){fault(r);return BOUNDARY_ERROR;}
    for(uint32_t i=0;i<8;i++)packet.body[i]=body[i];
    p->sends=1;
    int32_t result=r->port->send_worker(&packet);
    if(rl_sent(r->coordinator,p->owner,RL_WORKER,result?OWN_UNCERTAIN:OWN_ACCEPTED))fault(r);
    return result;
}
KEEP int32_t rt_retire(RtRuntime *r,RtProducer *p) {
    if(!lock(&p->lock))return OWN_BUSY;
    int32_t status=rl_finish(r->coordinator,p->owner);
    if(!status){p->owner=0;p->sends=0;}
    return unlock(&p->lock,status);
}
KEEP int32_t rt_receive(RtTask *t,const void *raw,uint32_t role) {
    if(!lock(&t->lock))return OWN_BUSY;
    if(t->phase!=RT_IDLE && t->phase!=RT_DONE)return unlock(&t->lock,OWN_BUSY);
    const RtWorkerPacket *p=raw;
    if((role!=RL_WORKER && role!=RL_UI) || p->tag.magic!=RL_MAGIC || p->tag.role!=role ||
       !p->tag.owner || !p->tag.child || (role==RL_WORKER? p->body[0]!=CALLBACK:!event_valid(p->body)))
        return unlock(&t->lock,OWN_CONFLICT);
    t->tag=p->tag;t->error=0;t->body_result=0;
    for(uint32_t i=0;i<(role==RL_WORKER?8u:5u);i++)t->body[i]=p->body[i];
    t->phase=RT_READY;return unlock(&t->lock,OWN_OK);
}
KEEP int32_t rt_run(RtRuntime *r,RtTask *t) {
    if(!lock(&t->lock))return OWN_BUSY;
    int32_t status;
    if(t->phase==RT_READY) {
        status=rl_claim(r->coordinator,&t->tag);
        if(status) {
            /* A rejected stale packet owns no executable work in this task.
             * Consume it so the next valid packet is not permanently blocked. */
            if(status==OWN_STALE || status==OWN_CONFLICT)t->phase=RT_DONE;
            return unlock(&t->lock,status);
        }
        t->phase=RT_RUNNING;
        t->body_result=t->tag.role==RL_WORKER?r->port->worker(t->body+1):r->port->ui(t->body);
        t->phase=RT_ERROR;
    }
    if(t->phase==RT_ERROR) {
        if(t->error) {
            status=rl_io_error(r->coordinator,&t->tag,t->error);
            if(status)return unlock(&t->lock,status);
        }
        t->phase=RT_COMPLETE;
    }
    if(t->phase!=RT_COMPLETE)return unlock(&t->lock,OWN_STALE);
    status=rl_complete(r->coordinator,&t->tag);
    if(!status)t->phase=RT_DONE;
    return unlock(&t->lock,status);
}
KEEP int32_t rt_event(RtRuntime *r,RtTask *t,const uint32_t *body) {
    if(!running(t) || t->tag.role!=RL_WORKER || !event_valid(body)){fault(r);return BOUNDARY_ERROR;}
    RtUiPacket packet;
    if(rl_prepare_ui(r->coordinator,t->tag.owner) ||
       rl_envelope(r->coordinator,t->tag.owner,RL_UI,&packet.tag)) {
        error(t,BOUNDARY_ERROR);fault(r);return BOUNDARY_ERROR;
    }
    for(uint32_t i=0;i<5;i++)packet.body[i]=body[i];
    int32_t result=r->port->send_ui(&packet);
    if(rl_sent(r->coordinator,t->tag.owner,RL_UI,result?OWN_UNCERTAIN:OWN_ACCEPTED))fault(r);
    return result;
}
KEEP int32_t rt_close(RtRuntime *r,RtTask *t,uint32_t h) {
    if(!running(t)){fault(r);return BOUNDARY_ERROR;}
    int32_t result=r->port->close(h);error(t,(uint32_t)result);return result;
}
KEEP int32_t rt_open(RtRuntime *r,RtTask *t,const uint32_t *a) {
    if(!running(t)){fault(r);return BOUNDARY_ERROR;}
    int32_t result=r->port->open(a[0],a[1],a[2],a[3]);
    int expected=t->tag.role==RL_UI && a[4]==UINT32_C(0x8004b5db) &&
        a[2]==1 && (uint32_t)result==UINT32_C(0xffffd75a);
    if(!expected)error(t,(uint32_t)result);
    return result;
}
KEEP int32_t rt_write(RtRuntime *r,RtTask *t,const uint32_t *a) {
    if(!running(t)){fault(r);return BOUNDARY_ERROR;}
    uint32_t *transferred=(uint32_t *)a[3];*transferred=0;
    int32_t result=r->port->write(a[0],a[1],a[2],transferred);
    error(t,result?(uint32_t)result:*transferred!=a[2]?SHORT_WRITE:0);
    return result;
}
KEEP const uint32_t rt_layout[]={sizeof(RtRuntime),sizeof(RtPort),sizeof(RtTask),sizeof(RtProducer),sizeof(RtWorkerPacket),sizeof(RtUiPacket)};
