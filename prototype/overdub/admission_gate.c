#include "admission_gate.h"
#include "overdub.h"
#define KEEP __attribute__((used, retain))

/* The ARM build emits LDREX/STREX and barriers, with no RTOS lock or heap.
 * Admission attempts have bounded retries. Completion retries only competing
 * atomic updates, never waits for another activity to finish. On-device cache,
 * RAM placement and interrupt/RTOS compatibility still require verification. */
_Static_assert(__atomic_always_lock_free(4, 0), "requires lock-free 32-bit atomics");
static uint32_t read_word(OdGate *g) {
    return __atomic_load_n(&g->word, __ATOMIC_ACQUIRE);
}
static int change(OdGate *g, uint32_t *old, uint32_t next) {
    return __atomic_compare_exchange_n(&g->word, old, next, 0,
                                      __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
}
KEEP void od_gate_fail(OdGate *g) {
    __atomic_fetch_or(&g->word, OD_GATE_FAILED, __ATOMIC_ACQ_REL);
}
KEEP int32_t od_gate_work_begin(OdGate *g) {
    uint32_t old=read_word(g);
    for (uint32_t tries=0; tries<8; tries++) {
        if (old & OD_GATE_FAILED) return OD_GATE_FAULT;
        if (old & OD_GATE_PROMOTING) return OD_GATE_BUSY;
        if ((old & OD_GATE_COUNT)==OD_GATE_COUNT) {
            od_gate_fail(g); return OD_GATE_FAULT;
        }
        if (change(g, &old, old+1)) return OD_GATE_OK;
    }
    return OD_GATE_BUSY;
}
KEEP int32_t od_gate_work_end(OdGate *g) {
    uint32_t old=read_word(g);
    for (;;) {
        if ((old & OD_GATE_PROMOTING) || !(old & OD_GATE_COUNT)) {
            od_gate_fail(g); return OD_GATE_MISUSE;
        }
        if (change(g, &old, old-1)) return OD_GATE_OK;
    }
}
static int32_t claim(OdGate *g, uint32_t owned) {
    uint32_t old=owned;
    if (change(g, &old, OD_GATE_PROMOTING)) return OD_GATE_OK;
    return (old & OD_GATE_FAILED) ? OD_GATE_FAULT : OD_GATE_BUSY;
}
KEEP int32_t od_gate_promote_begin(OdGate *g) { return claim(g, 0); }
KEEP int32_t od_gate_upgrade(OdGate *g) { return claim(g, 1); }
KEEP int32_t od_gate_promote_end(OdGate *g, uint32_t failed) {
    uint32_t old=read_word(g);
    for (;;) {
        if (!(old & OD_GATE_PROMOTING) || (old & OD_GATE_COUNT)) {
            od_gate_fail(g); return OD_GATE_MISUSE;
        }
        uint32_t next=(old & OD_GATE_FAILED) | (failed ? OD_GATE_FAILED : 0);
        if (change(g, &old, next)) return OD_GATE_OK;
    }
}

/* Emulator fixtures only: a real port needs an owned activity ledger and
 * complete stock ingress/completion coverage before it can bind these hooks. */
KEEP int32_t od_emulator_gate_enter(void) {
    return od_gate_promote_begin((OdGate *)0x21003800);
}
KEEP void od_emulator_gate_leave(void) {
    od_gate_promote_end((OdGate *)0x21003800,
                       ((volatile State *)0x21010000)->fault);
}
KEEP int32_t od_emulator_gate_checkpoint(void) {
    OdGate *g=(OdGate *)0x21003800;
    int32_t result=od_gate_work_begin(g);
    *(volatile int32_t *)0x21003804=result;
    ++*(volatile uint32_t *)0x21003808;
    if (result==OD_GATE_OK) od_gate_work_end(g);
    if (result!=OD_GATE_BUSY) return 1;
    /* Existing harness cancellation/yield boundary, not an on-device address. */
    return ((int32_t (*)(void))0x21000071)();
}
