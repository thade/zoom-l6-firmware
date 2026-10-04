#include "work_ownership.h"
#define KEEP __attribute__((used, retain))

/* These addresses are emulator fixtures. Context must become producer-task
 * local in a device integration; it is NOT a global permission bypass. */
typedef struct {
    uint32_t owner;
    uint32_t (*send)(uint32_t,const uint32_t *); /* OWN_* submission evidence */
    int32_t status;
    uint32_t last_ticket;
} ScanContext;
#define LEDGER ((OwnLedger *)0x21020000)
#define CONTEXT ((volatile ScanContext *)0x21003900)

static void error(int32_t status) {
    if (!CONTEXT->status) CONTEXT->status=status;
}
static void fail(int32_t status) {
    od_gate_fail(&LEDGER->gate);error(status?status:OWN_FAULT);
}

/* Original queue wrapper: 0 means accepted; all other returns are treated
 * conservatively as UNCERTAIN until its blocking failure contract is proven.
 * A test publisher can supply definite NOT_SENT evidence before publication. */
KEEP uint32_t od_emulator_stock_stream_send(uint32_t queue,const uint32_t *words) {
    int32_t status=((int32_t (*)(uint32_t,const uint32_t *))0x800483f9)(queue,words);
    return status==0?OWN_ACCEPTED:OWN_UNCERTAIN;
}

KEEP void od_emulator_stream_publish(uint32_t pad,uint32_t frames,uint32_t span,uint32_t position) {
    if (pad>3 || !CONTEXT->owner) {fail(OWN_CONFLICT);return;}
    volatile uint8_t *state=(volatile uint8_t *)(0x80735180+pad*0x44);
    volatile uint32_t *requested=(volatile uint32_t *)(state+0x20);
    /* This reproduces the zero-work store under the admitted outer scan. */
    if (!frames) {*requested=0;return;}
    if (state[0x1c]) {error(OWN_BUSY);return;}
    OwnRequest request={OWN_STREAM,{pad,frames,span,position}};
    uint32_t ticket=0,message[4];
    int32_t status=od_own_child(LEDGER,CONTEXT->owner,&request,&ticket);
    if (status) {error(status);return;}
    CONTEXT->last_ticket=ticket;
    status=od_own_offer(LEDGER,ticket);
    if (status) {fail(status);return;}
    status=od_own_stream_message(LEDGER,ticket,message);
    if (status) {fail(status);return;}
    uint32_t old_requested=*requested;
    *requested=frames;
    state[0x1c]=1;
    __atomic_thread_fence(__ATOMIC_RELEASE);
    uint32_t (*send)(uint32_t,const uint32_t *)=CONTEXT->send;
    if (!send) send=od_emulator_stock_stream_send;
    uint32_t outcome=send(*(volatile uint32_t *)0x801f8f34,message);
    status=od_own_submitted(LEDGER,ticket,outcome);
    if (status) {fail(status);return;}
    if (outcome==OWN_NOT_SENT) {
        /* Only positive nonpublication evidence permits undoing pending state.
         * A contradictory worker claim was rejected by submitted() above. */
        if (state[0x1c]!=1 || *requested!=frames) {fail(OWN_CONFLICT);return;}
        *requested=old_requested;
        state[0x1c]=0;
        error(OWN_BUSY);
    } else if (outcome==OWN_UNCERTAIN) {
        /* Do not undo a request that might already be visible to a worker. */
        error(OWN_BUSY);
    }
    status=od_own_producer_done(LEDGER,ticket,0);
    if (status) fail(status);
}

/* Redirect original 0x8003664a here, before BOTH requested-count and pending
 * stores. Preserve live scratch registers and the original stack. The original
 * producer body resumes after the replaced publication block at 0x800365d8.
 * This is compiled emulator glue, not a generated binary patch. */
__attribute__((used,retain,naked)) void od_emulator_stream_publish_trampoline(void) {
    __asm__ volatile(
        "push.w {r0-r3, r12, lr}\n"
        "mov r1, r2\n"
        "mov r0, r5\n"
        "mov r2, r9\n"
        "ldr r3, [sp, #28]\n"
        "bl od_emulator_stream_publish\n"
        "pop.w {r0-r3, r12, lr}\n"
        "ldr pc, =0x800365d9\n"
    );
}

/* Admit the WHOLE original scan, which can mutate state before publication.
 * A caller must explicitly provide any inherited promotion/ordinary parent.
 * BUSY here may mean admitted scan work remains pending after unknown enqueue;
 * it does not have the ledger APIs' no-change meaning. */
KEEP int32_t od_emulator_stream_scan(uint32_t parent) {
    if (CONTEXT->owner) {fail(OWN_CONFLICT);return OWN_CONFLICT;}
    CONTEXT->status=0;CONTEXT->last_ticket=0;
    OwnRequest request={OWN_SCAN,{0,0,0,0}};
    uint32_t ticket=0;
    int32_t status=parent?od_own_child(LEDGER,parent,&request,&ticket):
                          od_own_reserve(LEDGER,&request,&ticket);
    if (status) return status;
    /* Synchronous scan: offer/accept/claim confirm the direct invocation. */
    if ((status=od_own_offer(LEDGER,ticket)) ||
        (status=od_own_submitted(LEDGER,ticket,OWN_ACCEPTED)) ||
        (status=od_own_claim(LEDGER,ticket,&request))) {
        fail(status);return status;
    }
    CONTEXT->owner=ticket;
    ((void (*)(void))0x80036509)();
    CONTEXT->owner=0;
    status=od_own_complete(LEDGER,ticket);
    if (!status) status=od_own_producer_done(LEDGER,ticket,0);
    if (status) fail(status);
    return CONTEXT->status;
}
