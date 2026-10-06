#include "playback_io.h"
#define KEEP __attribute__((used,retain))
#define W(a) (*(volatile uint32_t *)(a))
enum {PI_IDLE,PI_PACKET,PI_DECODED,PI_READY,PI_RUNNING,PI_RETURNED,PI_FAILED,PI_RECEIVING};
static PiBinding binding;static uint32_t bound,lock_word,phase,packet[4],ticket,direct_owner,started;
static OwnRequest request;
KEEP const uint32_t pi_layout[]={sizeof(PiBinding)};
static int lock(void) {
    uint32_t z=0;return __atomic_compare_exchange_n(&lock_word,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(int32_t s){__atomic_store_n(&lock_word,0,__ATOMIC_RELEASE);return s;}
static int context(uint32_t id) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    return bound && !ipsr && W(0x80446da4u)==binding.main_task &&
        W(0x80446dccu)==binding.stream_task && W(0x801f8f34u)==binding.queue &&
        id && ((uint32_t (*)(void))0x800770e9u)()==id;
}
static void fail(void){od_gate_fail(&binding.session->ledger->gate);phase=PI_FAILED;}
static __attribute__((noreturn)) void park(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(bound)od_gate_fail(&binding.session->ledger->gate);
    for(;;){if(bound && !ipsr)binding.yield();else __asm__ volatile("wfe");}
}
static int32_t pause(void){leave(-1);binding.yield();return -1;}
KEEP int32_t pi_bind(const PiBinding *b) {
    if(bound || !b || !b->session || !b->session->ledger || !b->session->port ||
       b->session->port->start!=pi_start || !b->main_task || !b->stream_task || !b->queue ||
       b->main_task==b->stream_task || b->stream_task==W(0x80446dc4u) ||
       b->main_task!=W(0x80446da4u) || b->stream_task!=W(0x80446dccu) || b->queue!=W(0x801f8f34u) ||
       b->queue==W(0x801f8f30u) || !b->receive || !b->start || b->start==pi_start ||
       !b->refill || b->refill==pi_refill || !b->yield)return OWN_CONFLICT;
    OdSession *s=b->session;
    if(s->operation || s->owner || s->playing || s->closing || s->held || s->fenced_epoch ||
       s->ledger->lock || s->ledger->gate.word)return OWN_BUSY;
    binding=*b;bound=1;return OWN_OK;
}
KEEP int32_t pi_parent_ready(OwnLedger *l,const uint32_t *ids,const uint32_t *words) {
    if(!bound || !l || l!=binding.session->ledger || !ids || !words)return OWN_CONFLICT;
    if(started || lock_word || phase || direct_owner || l->lock || l->gate.word ||
       binding.session->operation || binding.session->owner)return OWN_BUSY;
    uint32_t main=0,stream=0;
    for(uint32_t i=0;i<8;i++) {
        if(ids[i]==binding.main_task && words[i]==0x80446da4u)main=1;
        if(ids[i]==binding.stream_task && words[i]==0x80446dccu)stream=1;
    }
    return main && stream?OWN_OK:OWN_CONFLICT;
}
KEEP int32_t pi_scan_ready(OdSession *s,uint32_t queue) {
    if(!bound || s!=binding.session || queue!=binding.queue ||
       W(0x80446dccu)!=binding.stream_task || W(0x801f8f34u)!=queue)return OWN_CONFLICT;
    if(started || lock_word || phase || direct_owner || s->operation || s->owner ||
       s->ledger->lock || s->ledger->gate.word)return OWN_BUSY;
    return OWN_OK;
}
KEEP int32_t pi_parent(uint32_t id,uint32_t *out) {
    if(!out || !context(id))return OWN_CONFLICT;
    if(!lock())return OWN_BUSY;
    uint32_t owner=0;
    if(phase!=PI_FAILED) {
        if(id==binding.stream_task && phase==PI_RUNNING)owner=ticket;
        else if(id==binding.main_task && direct_owner && binding.session->operation &&
                binding.session->owner==direct_owner)owner=direct_owner;
    }
    if(!owner)return leave(OWN_CONFLICT);
    *out=owner;return leave(OWN_OK);
}
KEEP int32_t pi_start(uint32_t pad) {
    if(!bound || !context(binding.main_task) || pad>3)park();
    while(!lock())binding.yield();
    started=1;
    OdSession *s=binding.session;
    if(phase==PI_FAILED || direct_owner || !s->operation || !s->owner ||
       !(s->playing&(1u<<pad))){leave(OWN_CONFLICT);park();}
    direct_owner=s->owner;leave(OWN_OK);
    int32_t result=binding.start(pad);
    while(!lock())binding.yield();
    if(!s->operation || s->owner!=direct_owner){leave(OWN_CONFLICT);park();}
    direct_owner=0;leave(OWN_OK);return result;
}
KEEP int32_t pi_next(uint32_t queue,uint32_t *out) {
    if(!bound || !context(binding.stream_task))return -1;
    if(!lock())return -1;
    started=1;
    if(!out || queue!=binding.queue || phase==PI_RUNNING || phase==PI_READY || phase==PI_RETURNED || phase==PI_RECEIVING) {
        fail();return pause();
    }
    if(phase==PI_FAILED)return pause();
    if(phase==PI_IDLE) {
        /* Native receive can block indefinitely. Main must still enter its
         * start/seek scope while the stream worker sleeps on an empty queue. */
        phase=PI_RECEIVING;leave(OWN_OK);
        int32_t received=binding.receive(queue,packet);
        while(!lock())binding.yield();
        if(phase!=PI_RECEIVING){fail();return pause();}
        if(received){phase=PI_IDLE;return pause();}
        phase=PI_PACKET;
    }
    int32_t s;
    if(phase==PI_PACKET) {
        s=od_own_stream_decode(binding.session->ledger,packet,request.args,&ticket);
        if(s==OWN_BUSY)return pause();
        if(s==OWN_STALE){phase=PI_IDLE;return pause();}
        if(s || request.args[0]>3){fail();return pause();}
        request.kind=OWN_STREAM;phase=PI_DECODED;
    }
    s=od_own_claim(binding.session->ledger,ticket,&request);
    if(s==OWN_BUSY)return pause();
    if(s){fail();return pause();}
    for(uint32_t i=0;i<4;i++)out[i]=request.args[i];
    phase=PI_READY;return leave(0);
}
KEEP void pi_refill(uint32_t pad,uint32_t frames,uint32_t span,uint32_t position) {
    if(!bound || !context(binding.stream_task))park();
    while(!lock())binding.yield();
    if(phase!=PI_READY || request.args[0]!=pad || request.args[1]!=frames ||
       request.args[2]!=span || request.args[3]!=position){fail();leave(OWN_CONFLICT);park();}
    phase=PI_RUNNING;leave(OWN_OK);
    binding.refill(pad,frames,span,position);
    while(!lock())binding.yield();
    if(phase!=PI_RUNNING){leave(OWN_CONFLICT);park();}
    phase=PI_RETURNED;leave(OWN_OK);
    int32_t s;
    while((s=od_own_complete(binding.session->ledger,ticket))==OWN_BUSY)binding.yield();
    if(s)park();
    while(!lock())binding.yield();
    ticket=0;phase=PI_IDLE;leave(OWN_OK);
}
