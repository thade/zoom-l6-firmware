#include "native_scan.h"
#include "playback_io.h"
#define KEEP __attribute__((used,retain))
#define W(a) (*(volatile uint32_t *)(a))
static NsBinding binding;
static uint32_t bound,worker,owner,parent_owner,status;
static OwnLedger *ledger;
KEEP const uint32_t ns_layout[]={sizeof(NsBinding)};
static int context(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    return bound && !ipsr && binding.session->ledger==ledger &&
        W(0x80446d7cu)==binding.task && W(0x80446dccu)==worker && W(0x801f8f34u)==binding.queue &&
        ((uint32_t (*)(void))0x800770e9u)()==binding.task;
}
static __attribute__((noreturn)) void park(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(bound)od_gate_fail(&ledger->gate);
    for(;;){if(bound && !ipsr)binding.yield();else __asm__ volatile("wfe");}
}
#define RETRY(expr) do {while((s=(expr))==OWN_BUSY)binding.yield();if(s)park();} while(0)
KEEP int32_t ns_bind(const NsBinding *b) {
    if(bound || !b || !b->session || !b->session->ledger || !b->session->port ||
       b->session->port->scan!=ns_scan || !b->task || b->task!=W(0x80446d7cu) ||
       b->task==W(0x80446da4u) || b->task==W(0x80446dccu) || b->task==W(0x80446dc4u) ||
       !b->send || !b->yield)return OWN_CONFLICT;
    int32_t s=pi_scan_ready(b->session,b->queue);if(s)return s;
    if(b->session->playing || b->session->closing || b->session->held || b->session->fenced_epoch)return OWN_BUSY;
    binding=*b;ledger=b->session->ledger;worker=W(0x80446dccu);bound=1;return OWN_OK;
}
extern int32_t rc_stock_send(uint32_t,const void *);
KEEP uint32_t ns_stock_send(uint32_t q,const uint32_t *words) {
    return rc_stock_send(q,words)==0?OWN_ACCEPTED:OWN_UNCERTAIN;
}
KEEP void ns_publish(uint32_t pad,uint32_t frames,uint32_t span,uint32_t position) {
    if(!context() || !owner || !binding.session->operation || binding.session->owner!=parent_owner || pad>3)park();
    volatile uint8_t *stream=(volatile uint8_t *)(0x80735180u+pad*0x44u);
    volatile uint32_t *requested=(volatile uint32_t *)(stream+0x20);
    if(!frames){*requested=0;return;}
    if(stream[0x1c]){status=OWN_BUSY;return;}
    OwnRequest request={OWN_STREAM,{pad,frames,span,position}};
    uint32_t child=0,words[4];int32_t s;
    RETRY(od_own_child(ledger,owner,&request,&child));
    RETRY(od_own_offer(ledger,child));
    RETRY(od_own_stream_message(ledger,child,words));
    uint32_t previous=*requested;
    *requested=frames;stream[0x1c]=1;
    __atomic_thread_fence(__ATOMIC_RELEASE);
    uint32_t outcome=binding.send(binding.queue,words);
    RETRY(od_own_submitted(ledger,child,outcome));
    if(outcome==OWN_NOT_SENT) {
        if(stream[0x1c]!=1 || *requested!=frames)park();
        *requested=previous;stream[0x1c]=0;status=OWN_BUSY;
    } else if(outcome==OWN_UNCERTAIN)status=OWN_BUSY;
    RETRY(od_own_producer_done(ledger,child,0));
}
KEEP int32_t ns_scan(uint32_t parent) {
    if(!context() || owner || !parent || !binding.session->operation ||
       parent!=binding.session->owner || binding.session->closing)return OWN_CONFLICT;
    OwnRequest request={OWN_SCAN,{0,0,0,0}};uint32_t scan=0;int32_t s;
    /* Before admission, BUSY/FULL has no native scan effects. */
    s=od_own_child(ledger,parent,&request,&scan);if(s)return s;
    RETRY(od_own_offer(ledger,scan));
    RETRY(od_own_submitted(ledger,scan,OWN_ACCEPTED));
    RETRY(od_own_claim(ledger,scan,&request));
    owner=scan;parent_owner=parent;status=OWN_OK;
    ((void (*)(void))0x80036509u)();
    RETRY(od_own_complete(ledger,scan));
    RETRY(od_own_producer_done(ledger,scan,0));
    owner=0;parent_owner=0;return (int32_t)status;
}
KEEP void ns_callback(void) {
    if(!context())park();
    int32_t s=od_session_scan(binding.session);
    /* A held session latch, closing session or pre-admission full ledger means
     * skip this periodic scan. No participant waits for the session latch. */
    if(s!=OWN_OK && s!=OWN_BUSY && s!=OWN_FULL)park();
}
