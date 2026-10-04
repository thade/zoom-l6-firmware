#include "playback_session.h"
#define KEEP __attribute__((used,retain))
static int enter(OdSession *s) {
    uint32_t zero=0;
    return __atomic_compare_exchange_n(&s->operation,&zero,1,0,
                                      __ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(OdSession *s,int32_t result) {
    __atomic_store_n(&s->operation,0,__ATOMIC_RELEASE);return result;
}
static int failed(OdSession *s) {
    return !!(__atomic_load_n(&s->ledger->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED);
}
static int32_t fault(OdSession *s) {
    od_gate_fail(&s->ledger->gate);return OWN_FAULT;
}
static int32_t begin(OdSession *s) {
    OwnRequest r={OWN_SESSION,{0,0,0,0}};
    uint32_t owner=0;
    int32_t result=od_own_reserve(s->ledger,&r,&owner);
    if (result) return result;
    s->owner=owner;
    if (od_own_offer(s->ledger,owner) ||
        od_own_submitted(s->ledger,owner,OWN_ACCEPTED) ||
        od_own_claim(s->ledger,owner,&r)) return fault(s);
    return OWN_OK;
}
KEEP int32_t od_session_start(OdSession *s,uint32_t pad) {
    if (pad>3) return OWN_CONFLICT;
    if (!enter(s)) return OWN_BUSY;
    if (failed(s)) return leave(s,OWN_FAULT);
    if (s->closing) return leave(s,OWN_BUSY);
    if (!s->port->loaded(pad)) return leave(s,OWN_STALE);
    int32_t result=s->owner?OWN_OK:begin(s);
    if (result) return leave(s,result);
    /* Retain the owner and bit even if a start/rearm has an unknown outcome. */
    s->playing|=1u<<pad;
    if (s->fenced_epoch) {
        if (s->port->rearm(s->fenced_epoch,s->owner)) return leave(s,fault(s));
        s->fenced_epoch=0;
    }
    if (s->port->start(pad)) return leave(s,fault(s));
    return leave(s,OWN_OK);
}
KEEP int32_t od_session_stop(OdSession *s,uint32_t pad) {
    if (pad>3) return OWN_CONFLICT;
    if (!enter(s)) return OWN_BUSY;
    if (failed(s)) return leave(s,OWN_FAULT);
    if (s->playing&(1u<<pad)) {
        if (s->port->stop(pad)) return leave(s,fault(s));
        s->playing&=~(1u<<pad);
    }
    /* Sound stop never retires session ownership by itself. */
    return leave(s,OWN_OK);
}
KEEP int32_t od_session_scan(OdSession *s) {
    if (!enter(s)) return OWN_BUSY;
    if (failed(s)) return leave(s,OWN_FAULT);
    if (!s->owner || s->closing) return leave(s,OWN_BUSY);
    return leave(s,s->port->scan(s->owner));
}
KEEP int32_t od_session_quiesce(OdSession *s) {
    if (!enter(s)) return OWN_BUSY;
    if (failed(s)) return leave(s,OWN_FAULT);
    if (!s->owner) return leave(s,OWN_OK);
    if (s->playing) return leave(s,OWN_BUSY);
    s->closing=1; /* Blocks retrigger and scans across BUSY retries. */
    if (!s->fenced_epoch) {
        uint32_t acknowledged=0;
        int32_t result=s->port->fence(s->owner,&acknowledged);
        if (result==OWN_BUSY) return leave(s,OWN_BUSY);
        if (result) return leave(s,fault(s));
        if (acknowledged!=s->owner) return leave(s,fault(s));
        s->fenced_epoch=s->owner;
    }
    if (!s->port->quiet()) return leave(s,OWN_BUSY);
    int32_t result=od_own_finish_session(s->ledger,s->owner);
    if (result==OWN_BUSY) return leave(s,OWN_BUSY);
    if (result) return leave(s,fault(s));
    s->owner=0;s->closing=s->held;
    return leave(s,OWN_OK);
}
KEEP int32_t od_session_hold(OdSession *s) {
    if (!enter(s)) return OWN_BUSY;
    if (failed(s)) return leave(s,OWN_FAULT);
    s->held=1;s->closing=1;
    return leave(s,OWN_OK);
}
KEEP int32_t od_session_unhold(OdSession *s) {
    if (!enter(s)) return OWN_BUSY;
    if (failed(s)) return leave(s,OWN_FAULT);
    if (s->owner || s->playing) return leave(s,OWN_BUSY);
    s->held=0;s->closing=0;
    return leave(s,OWN_OK);
}
KEEP const uint32_t od_session_layout[]={sizeof(OdSession),sizeof(OdSessionPort)};

/* Emulator-only stock adapters; these addresses are not a device placement. */
KEEP uint32_t od_emulator_session_loaded(uint32_t pad) {
    return ((uint32_t (*)(uint32_t))0x80009741)(pad);
}
KEEP int32_t od_emulator_session_start(uint32_t pad) {
    ((void (*)(uint32_t))0x80002c61)(pad);
    return *(volatile uint32_t *)(0x20015e4c+pad*0x3c)==1?OWN_OK:OWN_FAULT;
}
KEEP int32_t od_emulator_session_stop(uint32_t pad) {
    ((void (*)(uint32_t))0x80018351)(pad);
    return *(volatile uint32_t *)(0x20015e4c+pad*0x3c)==0?OWN_OK:OWN_FAULT;
}
KEEP uint32_t od_emulator_session_quiet(void) {
    for (uint32_t pad=0;pad<4;pad++) {
        volatile uint8_t *stream=(volatile uint8_t *)(0x80735180+pad*0x44);
        if (*(volatile uint32_t *)(0x20015e4c+pad*0x3c) || stream[0] || stream[0x1c]) return 0;
    }
    return 1;
}
/* Renderer fence/rearm is NOT recovered. Default adapters deliberately block. */
KEEP int32_t od_emulator_session_unbound_fence(uint32_t epoch,uint32_t *ack) {
    (void)epoch;*ack=0;return OWN_BUSY;
}
KEEP int32_t od_emulator_session_unbound_rearm(uint32_t old,uint32_t next) {
    (void)old;(void)next;return OWN_BUSY;
}
KEEP void od_emulator_session_callback(void) {
    (void)od_session_scan((OdSession *)0x21003a00);
}
