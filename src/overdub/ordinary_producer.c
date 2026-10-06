#include "ordinary_producer.h"
#include "read_producer.h"
#include "playback_io.h"
#define KEEP __attribute__((used,retain))
#define W(a) (*(volatile uint32_t *)(a))
static OpBinding binding;static uint32_t bound;
static OiIo operations[OI_SLOTS];
typedef struct {uint32_t lock,send_result,wait_result;} OpState;
static OpState producers[OI_SLOTS];
KEEP const uint32_t op_layout[]={sizeof(OpBinding),sizeof(OiIo),sizeof(OpState)};
KEEP uint32_t op_enabled(void){return bound;}
KEEP int32_t op_bind(const OpBinding *b) {
    if(bound || !b || !b->coordinator || !b->coordinator->ledger || pf_ready(b->coordinator) ||
       b->queue!=W(0x801f8f30u) || !b->queue || !b->semaphores[0] || !b->semaphores[1] ||
       b->semaphores[0]!=W(0x804467fcu) || b->semaphores[1]!=W(0x80446800u) ||
       b->semaphores[0]==b->semaphores[1] || !b->send || !b->wait || !b->yield || !b->parent || !b->seek)
        return OWN_CONFLICT;
    uint32_t count=0;
    for(uint32_t i=0;i<OI_SLOTS;i++) {
        uint32_t id=b->ids[i],word=b->id_words[i];
        if(!id && !word)continue;
        if(!id || word<0x80000000u || word>=0x81000000u || (word&3u) ||
           W(word)!=id || id==W(0x80446dc4u))return OWN_CONFLICT;
        for(uint32_t j=0;j<i;j++)if(b->ids[j]==id || b->id_words[j]==word)return OWN_CONFLICT;
        count++;
    }
    if(!count)return OWN_CONFLICT;
    if(b->parent==pi_parent) {
        int32_t s=pi_parent_ready(b->coordinator->ledger,b->ids,b->id_words);if(s)return s;
    }
    int32_t s=rp_ordinary_ready(b->coordinator,b->queue);if(s)return s;
    RwOrdinary w;w.coordinator=b->coordinator;w.seek=b->seek;
    for(uint32_t i=0;i<OI_SLOTS;i++)w.slots[i]=&operations[i];
    s=rw_bind_ordinary(&w);if(s)return s;
    /* No remaining fallible action; single cold caller makes publication safe. */
    /* Explicit bounded copy avoids pulling a compiler memory-helper runtime
     * into this freestanding image for the 100-byte configuration assignment. */
    binding.coordinator=b->coordinator;
    for(uint32_t i=0;i<OI_SLOTS;i++){binding.ids[i]=b->ids[i];binding.id_words[i]=b->id_words[i];}
    binding.queue=b->queue;binding.semaphores[0]=b->semaphores[0];binding.semaphores[1]=b->semaphores[1];
    binding.send=b->send;binding.wait=b->wait;binding.yield=b->yield;binding.parent=b->parent;binding.seek=b->seek;
    bound=1;return OWN_OK;
}
static __attribute__((noreturn)) void park(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(bound)od_gate_fail(&binding.coordinator->ledger->gate);
    for(;;){if(bound && !ipsr)binding.yield();else __asm__ volatile("wfe");}
}
static int role(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(!bound || ipsr || W(0x801f8f30u)!=binding.queue ||
       W(0x804467fcu)!=binding.semaphores[0] || W(0x80446800u)!=binding.semaphores[1])return -1;
    uint32_t id=((uint32_t (*)(void))0x800770e9u)();
    for(uint32_t i=0;i<OI_SLOTS;i++)if(id && binding.ids[i]==id && W(binding.id_words[i])==id)return (int)i;
    return -1;
}
static int32_t callback(uint32_t kind,uint32_t pad,uint32_t first,uint32_t second) {
    int i=role();if(i<0)park();
    /* Preserve original no-op argument cases before reserving anything. */
    if(pad>3 || (!kind && !first))return (int32_t)pad;
    OpState *p=&producers[i];uint32_t z=0;
    if(!__atomic_compare_exchange_n(&p->lock,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))park();
    uint32_t parent=0;int32_t s;
    while((s=binding.parent(binding.ids[i],&parent))==OWN_BUSY)binding.yield();
    if(s)park();
    OiIo *o=&operations[i];OiRequest request={kind,pad,first,second,(uint32_t)i+2,parent};
    while((s=oi_begin(binding.coordinator,o,&request))==OWN_BUSY)binding.yield();
    if(s)park();
    while((s=oi_prepare(o))==OWN_BUSY)binding.yield();
    if(s)park();
    uint32_t packet[4];
    while((s=oi_packet(o,(uint32_t)i,packet))==OWN_BUSY)binding.yield();
    if(s)park();
    p->send_result=(uint32_t)binding.send(binding.queue,packet);
    p->wait_result=(uint32_t)binding.wait(binding.semaphores[kind],1);
    /* Neither notification nor timeout is matching completion. An uncertain
     * send never permits releasing a request that may still be delivered. */
    while((s=oi_finish(o))==OWN_BUSY)binding.yield();
    if(s)park();
    /* A shared binary semaphore is only a scheduling hint. Another caller
     * may consume/coalesce our signal. Matching completion is authoritative. */
    int32_t result=1;
    __atomic_store_n(&p->lock,0,__ATOMIC_RELEASE);return result;
}
KEEP int32_t op_read(uint32_t pad,uint32_t buffer,uint32_t bytes){return callback(0,pad,buffer,bytes);}
KEEP int32_t op_seek(uint32_t pad,uint32_t offset,uint32_t origin){return callback(1,pad,offset,origin);}
