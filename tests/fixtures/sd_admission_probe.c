/* OFFLINE ONLY. Recovered MMIO and native event drain, not a device source gate.
 * Fixed 0x2102b800 is the explicit QUIET/ownership MODEL. A positive result must
 * retain that exclusion through native address programming and chunk joining.
 * Quiet registers or an empty event are not substitutes for this contract.
 * L6_SD_RETAIN_ONLY instead uses a zero-initialized source port; it cannot
 * advance until an offline test supplies that same explicit contract.
 * Faults retain the caller; no reset, retry, allocation or event replacement. */
#include "sd_admission_probe.h"
#include "sd_event_probe.h"
#include "sd_chunk_probe.h"
#define KEEP __attribute__((used,retain))
#define W(a) (*(volatile uint32_t *)(a))
#define TASK 0x808e291cu
#define EVENT 0x808e28e0u
#define STATUS 0x402c0030u
#define SIGNAL 0x402c0038u
#define ERRORS 0x157f0000u
/* A block-gap completion may cover only a prefix of the requested span. */
#define REJECT_STATUS (ERRORS|4u)
extern int32_t sdp_scope_matches(uint32_t,uint32_t);
extern int32_t sdp_scope_failed(uint32_t,uint32_t);
KEEP volatile SdAdmissionProbe sdp_admission_state;
KEEP volatile uint32_t sdp_chunk_admit_port;
#ifdef L6_SD_RETAIN_ONLY
/* Unbound in the combined fixture. Zero cannot grant source ownership. */
KEEP volatile uint32_t sdp_source_port;
#endif

static void delay(void) { ((void (*)(uint32_t))0x80032251u)(1); }
static int32_t fault(uint32_t why) { sdp_admission_state.fault=why;return 0; }
static int32_t shape(void) {
    uint32_t protocol=W(0x402c0028u);
    /* Refuse stop-at-block-gap and continue requests as well as ADMA/endian
     * modes: TC alone does not distinguish a full transfer from a gap stop. */
    return (protocol&0x30330u)==0x20u && (protocol&6u)<=2u &&
           !(W(0x402c00c8u)&0x1000u);
}
static int32_t identity(uint32_t unit,uint32_t event) {
    return !unit && event && sdp_scope_matches(unit,event) &&
           !sdp_scope_failed(unit,event) && W(EVENT)==event &&
           W(TASK) && W(TASK)==sdp_admission_state.task;
}

KEEP int32_t sdp_native_admit(uint32_t unit,uint32_t event,uint32_t address,uint32_t site) {
    if(sdp_admission_state.fault)return 0;
    if(!sdp_event_context_ready())return fault(1);
    if(!identity(unit,event))return fault(2);
    if(!shape())return fault(3);
    /* IRQ111 has a second wrapper into the same controller body. Until its
     * ownership is bound, refuse a configured/active/pending second source.
     * IRQ110 enable/priority/context are checked by the native event helper. */
    if((W(0xe000e10cu)|W(0xe000e20cu)|W(0xe000e30cu))&(1u<<15))return fault(4);
    if(W(0x402c002cu)&0x07000000u)return 0;
    uint32_t present=W(0x402c0024u);
    /* New commands require settled command/data/card activity. Unlike a
     * completed chunk's host-RAM join, admission also waits for card busy. */
    if((present&0x307u) || !(present&0x01000000u) || !(present&8u))return 0;
    if(W(STATUS)&REJECT_STATUS)return fault(5);
#ifdef L6_SD_RETAIN_ONLY
    uint32_t source=sdp_source_port;
    if(!source)return 0;
#else
    uint32_t source=0x2102b801u;
#endif
    if(((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t))source)(
          unit,event,address,site)!=1)return 0;
    if(!identity(unit,event) || !shape())return fault(6);
    present=W(0x402c0024u);
    if((present&0x307u) || !(present&0x01000000u) || !(present&8u) ||
       (W(0x402c002cu)&0x07000000u) || (W(STATUS)&REJECT_STATUS))return fault(6);
    if((W(0xe000e10cu)|W(0xe000e20cu)|W(0xe000e30cu))&(1u<<15))return fault(4);
    /* Clear old CC/TC/data status BEFORE DS_ADDR, then drain native software
     * flags, the real binary token and IRQ110 pending state. W1C effects remain
     * simulated offline. Unexpected status and a failed drain stay blocked. */
    W(SIGNAL)=0;
    W(STATUS)=0x3fu;
    __asm__ volatile("dsb\nisb":::"memory");
    if(W(STATUS))return fault(7);
    if(sdp_event_drain(unit,event)!=1)return fault(8);
    if(!identity(unit,event) || !shape() || W(STATUS) || W(SIGNAL))return fault(9);
    present=W(0x402c0024u);
    if((present&0x307u) || !(present&0x01000000u) || !(present&8u) ||
       (W(0x402c002cu)&0x07000000u))return fault(9);
    return 1;
}

static void admit(uint32_t address,uint32_t site) {
    uint32_t event=W(EVENT);
    for(;;) {
        if(!sdp_admission_state.fault && identity(0,event) &&
           ((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t))sdp_chunk_admit_port)(
                0,event,address,site)==1 && identity(0,event))break;
        delay();
    }
    sdp_admission_state.address=address;sdp_admission_state.site=site;
    sdp_admission_state.calls++;
    sdp_admission_state.prepared=site!=0;
}
KEEP void sdp_admission_begin(void) {
    /* Volatile scalar stores keep this inline-adapter call integer-only. */
    sdp_admission_state.address=0;sdp_admission_state.site=0;
    sdp_admission_state.task=W(TASK);sdp_admission_state.prepared=0;
    sdp_admission_state.calls=0;sdp_admission_state.fault=0;
    /* Hold before any native bounce fill/read-cache effects, not just before
     * its later DS_ADDR store. The registered parent still owns the SD token. */
    if(sdp_chunk_admit_port) {
        if(!sdp_chunk_finish_port)sdp_admission_state.fault=11;
        admit(0,0);
    }
}
KEEP void sdp_before_address(uint32_t address,uint32_t site) {
    if(!sdp_chunk_admit_port)return;
    if(!address || (site!=0x80069fecu && site!=0x8006a180u &&
                   site!=0x8006abf0u && site!=0x8006adacu) ||
       sdp_admission_state.prepared || sdp_chunk_state.active)
        sdp_admission_state.fault=10;
    admit(address,site);
}

KEEP int32_t sdp_native_chunk_join(uint32_t unit,uint32_t event,uint32_t address,uint32_t bytes) {
    /* The enclosing native wait already requires success-only flags and a
     * fresh raw TC. This bounded candidate checks the admitted exact span and
     * host-RAM activity; it makes no card persistence or fault-recovery claim.
     * Entry/source exclusion and hardware bus semantics still need binding. */
    /* Mode/gap evidence is a permanent fault for this owned operation. Clearing
     * a later register must not turn a possibly partial completion into success. */
    if(!shape() || ((sdp_chunk_state.raw|W(STATUS))&4u))return fault(12);
    if(!sdp_chunk_admit_port || sdp_admission_state.fault ||
       sdp_admission_state.calls<2 || sdp_admission_state.prepared ||
       !identity(unit,event) || !sdp_chunk_state.active ||
       sdp_admission_state.address!=address || sdp_chunk_state.address!=address ||
       sdp_chunk_state.bytes!=bytes || sdp_chunk_state.task!=W(TASK) ||
       !(sdp_chunk_state.raw&2u) || (sdp_chunk_state.raw&REJECT_STATUS) || !shape())return 0;
    if((W(0x402c0024u)&0x300u) || (W(0x402c002cu)&0x07000000u) ||
       (W(STATUS)&REJECT_STATUS) ||
       ((W(0xe000e10cu)|W(0xe000e20cu)|W(0xe000e30cu))&(1u<<15)))return 0;
    __asm__ volatile("dsb":::"memory");
    return 1;
}
