/* OFFLINE ONLY. Fixed MODEL port 0x2102bb00 supplies IRQ/post serialization,
 * kernel-signal draining (unless the native test port is selected), prior
 * hardware/cache/card validity for admission,
 * permission to reset AFTER accepted abort, and final cache/card/filesystem
 * validity. None of those physical contracts is bound.
 * Candidate RSTD/MMIO/W1C semantics are simulated. Do not install this code.
 * No RSTA, card reinit, kernel-object recreation, automatic retry or mode repair.
 * Stalled/failed checks retain the original transfer; do not repeat its reset. */
#include "sd_recovery_probe.h"
#include "sd_stop_probe.h"
#include "sd_event_probe.h"
#define KEEP __attribute__((used,retain))
#define MMIO(a) (*(volatile uint32_t *)(a))
#define PRESENT 0x402c0024u
#define SYSTEM 0x402c002cu
#define STATUS 0x402c0030u
#define SIGNAL 0x402c0038u
#define RESETS 0x07000000u
#define RSTD 0x04000000u
#define ACTIVE 0x307u
#define DAT0 0x01000000u
#define CREQ 0x20000u
#define STATUS_MASK 0x157f003fu
#define CLOCK_MASK 0x00ffffffu
KEEP volatile SdRecoveryProbe sdp_recovery_state;
/* Disabled in every existing probe experiment unless selected explicitly. */
KEEP volatile uint32_t sdp_admit_port;
extern int32_t sdp_stock_data_read(void *,uint32_t);
extern int32_t sdp_stock_data_write(void *,uint32_t);

static int32_t model(uint32_t step) {
    return ((int32_t (*)(uint32_t,uint32_t,uint32_t))0x2102bb01u)(
          step,sdp_recovery_state.unit,sdp_recovery_state.event);
}
static void delay(void) { ((void (*)(uint32_t))0x80032251u)(1); }
static int32_t block(uint32_t why) {
    if(!sdp_recovery_state.fault)sdp_recovery_state.fault=why;
    sdp_recovery_state.phase=SDP_REC_BLOCKED;return 0;
}
static int32_t identity(void) {
    if(MMIO(0x808e28e0u)!=sdp_recovery_state.event)return block(SDP_EVENT_CHANGED);
    return 1;
}
static int32_t flags(uint32_t *out) {
    return ((int32_t (*)(uint32_t,uint32_t *))0x80032879u)(sdp_recovery_state.event,out);
}
static int32_t drain(uint32_t quiet,uint32_t kernel) {
    uint32_t software=0;
    MMIO(SIGNAL)=0;
    /* Masking alone is not serialization. MODEL must join running ISR/posts
     * and exclude old completion delivery through the subsequent checks/arm. */
    if(model(quiet)!=1)return 0;
    if(!identity())return 0;
    sdp_recovery_state.raw_before=MMIO(STATUS);
    MMIO(STATUS)=STATUS_MASK; /* W1C, candidate hardware effects are modeled. */
    if(MMIO(STATUS))return block(SDP_DIRTY_HW);
    /* Selected only in the native-event offline suite. The surrounding QUIET
     * contract still pins the object and excludes old hardware/task posts.
     * Do not run stock peek before the native context check: its critical
     * helper would overwrite a preexisting BASEPRI mask. */
    if(sdp_kernel_port) {
        int32_t result=((int32_t (*)(uint32_t,uint32_t))sdp_kernel_port)(
              sdp_recovery_state.unit,sdp_recovery_state.event);
        sdp_recovery_state.flags_before=sdp_event_state.flags_before;
        if(result!=1)return block(SDP_DIRTY_SW);
    } else {
        if(flags(&software))return block(SDP_DIRTY_SW);
        sdp_recovery_state.flags_before=software;
        if(model(kernel)!=1)return 0;
    }
    if(!identity())return 0;
    if(flags(&software) || software)return block(SDP_DIRTY_SW);
    if(MMIO(STATUS))return block(SDP_DIRTY_HW);
    sdp_recovery_state.drains++;return 1;
}
static int32_t ready(void) {
    uint32_t software=0;
    if(sdp_kernel_port && !sdp_event_context_ready())return block(SDP_DIRTY_SW);
    if(!identity())return 0;
    if(MMIO(SYSTEM)&RESETS)return block(SDP_RESET_STALLED);
    if(MMIO(PRESENT)&ACTIVE)return block(SDP_STILL_ACTIVE);
    if(!(MMIO(PRESENT)&DAT0))return block(SDP_DAT0_BUSY);
    if(!(MMIO(PRESENT)&8))return block(SDP_CLOCK_UNSTABLE);
    if((MMIO(0x402c0028u)&~CREQ)!=sdp_recovery_state.protocol ||
       MMIO(0x402c00c8u)!=sdp_recovery_state.vendor2 ||
       (MMIO(SYSTEM)&CLOCK_MASK)!=sdp_recovery_state.clock)
        return block(SDP_CONFIG_CHANGED);
    if(MMIO(STATUS))return block(SDP_DIRTY_HW);
    if(flags(&software) || software)return block(SDP_DIRTY_SW);
    return 1;
}
KEEP void sdp_recovery_begin(uint32_t unit,uint32_t event) {
    sdp_recovery_state=(SdRecoveryProbe){.unit=unit,.event=event};
}
KEEP int32_t sdp_recovery_admit(uint32_t unit,uint32_t event) {
    if(unit || !sdp_scope_matches(unit,event) ||
       unit!=sdp_recovery_state.unit || event!=sdp_recovery_state.event)return 0;
    sdp_recovery_state.admit_calls++;
    if(sdp_recovery_state.fault)return 0;
    if(!drain(SDP_QUIET_ADMIT,SDP_KERNEL_ADMIT))return 0;
    sdp_recovery_state.protocol=MMIO(0x402c0028u)&~CREQ;
    sdp_recovery_state.vendor2=MMIO(0x402c00c8u);
    sdp_recovery_state.clock=MMIO(SYSTEM)&CLOCK_MASK;
    /* This experiment supports only the examined simple-DMA, little-endian
     * SD bus modes; it does not silently accept unrelated controller modes. */
    if((sdp_recovery_state.protocol&0x330u)!=0x20 ||
       (sdp_recovery_state.protocol&6u)>2 ||
       (sdp_recovery_state.vendor2&0x1000u))return block(SDP_CONFIG_CHANGED);
    if(!ready())return 0;
    sdp_recovery_state.admitted=1;return 1;
}
KEEP int32_t sdp_recovery_join(uint32_t unit,uint32_t buffer,uint32_t bytes,uint32_t reason) {
    (void)reason;
    if(unit || !sdp_failed_scope(unit,buffer,bytes) ||
       !sdp_scope_matches(unit,sdp_recovery_state.event))return 0;
    sdp_recovery_state.join_calls++;
    if(sdp_recovery_state.fault || !sdp_recovery_state.admitted)return 0;
    if(!identity())return 0;
    /* A repeated call must not reuse a cached success after state has changed. */
    if(sdp_recovery_state.phase==SDP_REC_DONE)sdp_recovery_state.phase=SDP_REC_VERIFY;
    if(sdp_recovery_state.phase==SDP_REC_START) {
        if(MMIO(SYSTEM)&RESETS)return block(SDP_RESET_STALLED);
        if(!drain(SDP_QUIET_BEFORE,SDP_KERNEL_BEFORE))return 0;
        /* Counterfactual abort-type row exists ONLY in emulator memory.
         * The stock row is not silently accepted or patched by this fixture. */
        if(MMIO(0x800a0894u)!=12 || MMIO(0x800a0898u)!=0x00db0000u ||
           MMIO(0x800a089cu)!=0x10)return block(SDP_NOT_ABORT);
        sdp_recovery_state.phase=SDP_REC_STOP;
        if(!sdp_stop_attempt(unit,buffer,bytes))return block(SDP_STOP_FAILED);
        MMIO(SIGNAL)=0;
        if(sdp_stop_state.status || sdp_stop_state.errors)return block(SDP_STOP_FAILED);
        if(sdp_stop_state.raw!=1)return block(SDP_NO_FRESH_CC);
        sdp_recovery_state.phase=SDP_REC_PERMIT;
    }
    if(sdp_recovery_state.phase==SDP_REC_PERMIT) {
        /* CMD12 success/busy expiry is NOT permission to reset live DMA.
         * MODEL attests abort acceptance + reset safety under the candidate
         * manual's incomplete-transfer constraint. It never attests JOINED. */
        if(model(SDP_RESET_PERMITTED)!=1)return 0;
        if(!identity())return 0;
        if(MMIO(SYSTEM)&RESETS)return block(SDP_RESET_STALLED);
        sdp_recovery_state.phase=SDP_REC_RESET;sdp_recovery_state.resets++;
        MMIO(SYSTEM)|=RSTD;
        for(uint32_t n=0;n<10 && (MMIO(SYSTEM)&RESETS);n++) {
            sdp_recovery_state.polls++;delay();
        }
        if(MMIO(SYSTEM)&RESETS)return block(SDP_RESET_STALLED);
        sdp_recovery_state.phase=SDP_REC_CLEAN;
    }
    if(sdp_recovery_state.phase==SDP_REC_CLEAN) {
        if(!drain(SDP_QUIET_AFTER,SDP_KERNEL_AFTER))return 0;
        if(!ready())return 0;
        sdp_recovery_state.phase=SDP_REC_VERIFY;
    }
    if(sdp_recovery_state.phase==SDP_REC_VERIFY) {
        if(!ready() || model(SDP_UNWIND_SAFE)!=1)return 0;
        /* Final MODEL attestation cannot bypass the compiled register checks. */
        if(!ready())return 0;
        sdp_recovery_state.phase=SDP_REC_DONE;
    }
    return sdp_recovery_state.phase==SDP_REC_DONE;
}

static int32_t admit_transfer(void *request,uint32_t unit,
                             int32_t (*stock)(void *,uint32_t)) {
    uint32_t event=sdp_recovery_state.event;
    if(sdp_admit_port && sdp_scope_matches(unit,event)) {
        if(sdp_scope_failed(unit,event))return 11;
        /* Called at the lower public data entry, AFTER the registered parent
         * acquired the SD token, BEFORE its first DMA address is programmed.
         * A pending admission holds that same parent stack/token. */
        while(!sdp_recovery_state.admitted) {
            if(((int32_t (*)(uint32_t,uint32_t))sdp_admit_port)(unit,event)==1)break;
            delay();
        }
    }
    return stock(request,unit);
}
KEEP int32_t sdp_admit_read(void *request,uint32_t unit) {
    return admit_transfer(request,unit,sdp_stock_data_read);
}
KEEP int32_t sdp_admit_write(void *request,uint32_t unit) {
    return admit_transfer(request,unit,sdp_stock_data_write);
}
