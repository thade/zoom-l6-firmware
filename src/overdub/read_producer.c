#include "read_producer.h"
#include "pad_file.h"
#include "ordinary_producer.h"
#define KEEP __attribute__((used,retain))
#define W(a) (*(volatile uint32_t *)(a))
enum {RP_IDLE,RP_RESERVE,RP_READY,RP_PACKET,RP_SEND,RP_WAIT,RP_ERROR,RP_JOIN,RP_RELEASE,RP_DONE};
typedef struct {
    uint32_t lock,phase;RlEnvelope tag;
    uint32_t args[4],packet[4],ticket,send_result,wait_result,lease;
} RpState;
static RpBinding binding;static uint32_t bound;static RpState states[2];
KEEP const uint32_t rp_layout[]={sizeof(RpBinding),sizeof(RpState)};
static int role(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(!bound || ipsr || W(0x801f8f30u)!=binding.queue || W(0x804467fcu)!=binding.semaphore)return -1;
    uint32_t id=((uint32_t (*)(void))0x800770e9u)();
    for(uint32_t i=0;i<2;i++)if(id==binding.ids[i] && W(i?0x80446da4u:0x80446dc8u)==id)return (int)i;
    return -1;
}
static int active(uint32_t i) {
    RtTask *t=binding.tasks[i];
    return t->lock && t->phase==RT_RUNNING && t->tag.magic==RL_MAGIC && t->tag.role==i+1 &&
           t->tag.owner && t->tag.child;
}
static int same(uint32_t i,const RpState *s) {
    const RlEnvelope *t=&binding.tasks[i]->tag;
    return active(i) && t->magic==s->tag.magic && t->owner==s->tag.owner &&
           t->child==s->tag.child && t->role==s->tag.role;
}
static int lock(RpState *s) {
    uint32_t z=0;return __atomic_compare_exchange_n(&s->lock,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(RpState *s,int32_t r){__atomic_store_n(&s->lock,0,__ATOMIC_RELEASE);return r;}
static int32_t pending(RpState *s) {leave(s,OWN_BUSY);binding.yield();return OWN_BUSY;}
KEEP int32_t rp_can_bind(const RpBinding *b) {
    if(bound || !b || !b->coordinator || !b->coordinator->ledger || !b->queue || !b->semaphore ||
       b->queue!=W(0x801f8f30u) || b->semaphore!=W(0x804467fcu) || !b->send || !b->wait || !b->yield)
        return OWN_CONFLICT;
    for(uint32_t i=0;i<2;i++)if(!b->tasks[i] || !b->reads[i] || !b->ids[i] ||
        b->slots[i]>=RR_QUEUE_SLOTS || b->ids[i]!=W(i?0x80446da4u:0x80446dc8u))return OWN_CONFLICT;
    if(b->tasks[0]==b->tasks[1] || b->reads[0]==b->reads[1] || b->ids[0]==b->ids[1] || b->slots[0]==b->slots[1])return OWN_CONFLICT;
    return OWN_OK;
}
KEEP int32_t rp_bind(const RpBinding *b) {
    int32_t result=rp_can_bind(b);if(result)return result;
    binding=*b;bound=1;return OWN_OK;
}
KEEP int32_t rp_ordinary_ready(RlCoordinator *c,uint32_t queue) {
    if(!bound || binding.coordinator!=c || binding.queue!=queue ||
       binding.semaphore!=W(0x804467fcu) || binding.ids[0]!=W(0x80446dc8u) ||
       binding.ids[1]!=W(0x80446da4u))return OWN_CONFLICT;
    for(uint32_t i=0;i<2;i++)if(states[i].lock || states[i].phase!=RP_IDLE ||
        binding.tasks[i]->lock || binding.tasks[i]->phase!=RT_IDLE)return OWN_BUSY;
    return OWN_OK;
}
KEEP int32_t rp_begin(uint32_t pad,uint32_t buffer,uint32_t bytes) {
    int i=role();if(i<0 || !active((uint32_t)i))return OWN_CONFLICT;
    RpState *s=&states[i];if(!lock(s))return OWN_BUSY;
    if(s->phase!=RP_IDLE && s->phase!=RP_DONE)return leave(s,OWN_BUSY);
    if(pad>3 || !buffer || !bytes || buffer>UINT32_MAX-bytes)return leave(s,OWN_CONFLICT);
    uint32_t pin[2];int32_t result=pf_pin(binding.coordinator,(uint32_t)i,pad,pin);
    if(result)return leave(s,result);
    s->lease=pin[1];s->tag=binding.tasks[i]->tag;
    s->args[0]=pad;s->args[1]=buffer;s->args[2]=bytes;s->args[3]=pin[0];
    s->ticket=0;s->send_result=0;s->wait_result=0;s->phase=RP_RESERVE;
    return leave(s,OWN_OK);
}
KEEP int32_t rp_step(void) {
    int i=role();if(i<0)return OWN_CONFLICT;
    RpState *s=&states[i];if(!lock(s))return OWN_BUSY;
    if(!same((uint32_t)i,s))return leave(s,OWN_CONFLICT);
    RrRead *r=binding.reads[i];int32_t result=OWN_OK;
    switch(s->phase) {
    case RP_RESERVE:
        result=rr_begin_handle(binding.coordinator,r,&s->tag,s->args);
        if(!result){s->ticket=r->ticket;s->phase=RP_READY;}break;
    case RP_READY:
        result=rr_ready(binding.coordinator,r,s->ticket);
        if(!result)s->phase=RP_PACKET;break;
    case RP_PACKET:
        result=rr_queue_packet(r,s->ticket,binding.slots[i],s->packet);
        if(!result)s->phase=RP_SEND;break;
    case RP_SEND:
        s->send_result=(uint32_t)binding.send(binding.queue,s->packet);s->phase=RP_WAIT;break;
    case RP_WAIT:
        /* Signals can coalesce across readers. A bounded wait is a hint,
         * never proof of completion or an I/O error when it times out. */
        (void)binding.wait(binding.semaphore,1);
        s->wait_result=1;s->phase=RP_JOIN;break;
    case RP_JOIN:
        result=rr_finish(binding.coordinator,r,s->ticket);
        if(!result)s->phase=s->lease?RP_RELEASE:RP_DONE;break;
    case RP_RELEASE:
        result=pf_drop((uint32_t)i,s->lease);
        if(!result)s->phase=RP_DONE;break;
    case RP_DONE:return leave(s,OWN_OK);
    default:return leave(s,OWN_CONFLICT);
    }
    if(result && result!=OWN_BUSY)return leave(s,result);
    return s->phase==RP_DONE?leave(s,OWN_OK):pending(s);
}
KEEP int32_t rp_result(uint32_t *out) {
    int i=role();if(i<0 || !out)return OWN_CONFLICT;
    RpState *s=&states[i];if(!lock(s))return OWN_BUSY;
    if(s->phase!=RP_DONE || !same((uint32_t)i,s))return leave(s,OWN_BUSY);
    out[0]=s->send_result;out[1]=s->wait_result;out[2]=s->ticket;return leave(s,OWN_OK);
}
static __attribute__((noreturn)) void park(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(bound)od_gate_fail(&binding.coordinator->ledger->gate);
    /* No return path: stock prefetch ignores the callback result. Fault
     * isolation/unwinding must be designed before this is deployed. */
    for(;;) {
        if(bound && !ipsr)binding.yield();
        else __asm__ volatile("wfe");
    }
}
KEEP int32_t rp_callback(uint32_t pad,uint32_t buffer,uint32_t bytes) {
    int32_t result;
    while((result=rp_begin(pad,buffer,bytes))==OWN_BUSY)binding.yield();
    if(result!=OWN_OK)park();
    do {result=rp_step();}while(result==OWN_BUSY);
    if(result!=OWN_OK)park();
    uint32_t out[3];
    while((result=rp_result(out))==OWN_BUSY)binding.yield();
    if(result!=OWN_OK)park();
    return (int32_t)out[1];
}
extern int32_t rp_stock_read(uint32_t,uint32_t,uint32_t);
extern int32_t rp_stock_seek(uint32_t,uint32_t,uint32_t);
static int32_t dispatch(uint32_t pad,uint32_t buffer,uint32_t bytes,uint32_t caller,uint32_t seek) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    /* Never silently fall back after losing a native binding. Installation
     * is cold-only, with permanent task identities and both queue endpoints. */
    if(!bound || ipsr || W(0x801f8f30u)!=binding.queue || W(0x804467fcu)!=binding.semaphore ||
       W(0x80446dc8u)!=binding.ids[0] || W(0x80446da4u)!=binding.ids[1])park();
    uint32_t id=((uint32_t (*)(void))0x800770e9u)();
    if(!id)park();
    for(uint32_t i=0;i<2;i++)if(id==binding.ids[i]) {
        RtTask *t=binding.tasks[i];RpState *s=&states[i];
        if(active(i)) {
            /* Original initial-prefetch BLX continuations, including carry. */
            if(seek || (caller!=0x80036b59u && caller!=0x80036b0fu))park();
            return rp_callback(pad,buffer,bytes);
        }
        /* Only completely inactive contexts may use the ordinary path. A
         * damaged tag, retained operation or transitional phase is not idle. */
        if(t->lock || (t->phase!=RT_IDLE && t->phase!=RT_DONE) || s->lock ||
           (s->phase!=RP_IDLE && s->phase!=RP_DONE))park();
        break;
    }
    if(op_enabled())return seek?op_seek(pad,buffer,bytes):op_read(pad,buffer,bytes);
    return seek?rp_stock_seek(pad,buffer,bytes):rp_stock_read(pad,buffer,bytes);
}
KEEP int32_t rp_dispatch(uint32_t pad,uint32_t buffer,uint32_t bytes,uint32_t caller) {
    return dispatch(pad,buffer,bytes,caller,0);
}
KEEP int32_t rp_seek_dispatch(uint32_t pad,uint32_t offset,uint32_t origin) {
    return dispatch(pad,offset,origin,0,1);
}
