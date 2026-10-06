/* Offline SD ownership experiment ONLY. No physical cancellation implementation.
 * Fixed 0x2102bd00/04 callbacks are emulator models. Never bind on a device.
 * Entry admission assumes prior hardware work/IRQs joined and stale status
 * drained; a per-unit software lock does not establish that precondition. */
#include <stdint.h>
#include "sd_stop_probe.h"
#include "sd_recovery_probe.h"
#define KEEP __attribute__((used,retain))
typedef int32_t (*Command)(void *,uint32_t);
typedef int32_t (*Wait)(uint32_t,uint32_t,uint32_t,uint32_t *,uint32_t);
extern int32_t sdp_stock_read(void *,uint32_t);
extern int32_t sdp_stock_write(void *,uint32_t);
extern int32_t sdp_stock_command(void *,uint32_t);
typedef struct {
    uint32_t active,unit,event,buffer,bytes,raw,errors,failed,reasons;
    uint32_t waits,commands,join_calls,joined,finished;
} SdProbe;
KEEP volatile SdProbe sdp_state;
/* Default keeps existing experiments unchanged. A stop experiment selects the
 * compiled sdp_stop_join explicitly; neither model port has a device binding. */
KEEP volatile uint32_t sdp_join_port=0x2102bd01u;
/* Capture composition selects this separate MODEL port explicitly. Check
 * completion while the original unit token AND transfer/file frames are live,
 * including nominal success. Zero leaves older experiments unchanged.
 * It is not a physical completion detector and must never be device-bound. */
KEEP volatile uint32_t sdp_finish_port;
enum { RAW_ERROR=1, BAD_FLAGS=2, TIMEOUT=4, COMMAND_ERROR=8 };

KEEP int32_t sdp_failed_scope(uint32_t unit,uint32_t buffer,uint32_t bytes) {
    return sdp_state.active && sdp_state.failed && unit==sdp_state.unit &&
           buffer==sdp_state.buffer && bytes==sdp_state.bytes;
}
KEEP int32_t sdp_scope_matches(uint32_t unit,uint32_t event) {
    return sdp_state.active && unit==sdp_state.unit && event==sdp_state.event;
}
KEEP int32_t sdp_scope_failed(uint32_t unit,uint32_t event) {
    return sdp_scope_matches(unit,event) && sdp_state.failed;
}

KEEP void sdp_irq_sample(uint32_t unit,uint32_t raw) {
    if(!sdp_state.active || unit!=sdp_state.unit)return;
    sdp_state.raw|=raw;
    sdp_state.errors|=raw & 0x157f0000u;
    if(sdp_stop_state.active && unit==sdp_stop_state.unit) {
        sdp_stop_state.raw|=raw;
        sdp_stop_state.errors|=raw & 0x157f0000u;
    }
}

static void fail_join(uint32_t reason) {
    sdp_state.reasons|=reason;
    if(sdp_state.failed)return; /* Serialized owner already handles this fault. */
    sdp_state.failed=1;
    for(;;) {
        sdp_state.join_calls++;
        /* Only an explicit modeled JOINED (1) permits native stack unwinding.
         * Other values retain the entire call, including SD mutex/buffers. */
        if(((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t))sdp_join_port)(
              sdp_state.unit,sdp_state.buffer,sdp_state.bytes,sdp_state.reasons)==1)break;
        ((void (*)(uint32_t))0x80032251u)(1);
    }
    sdp_state.joined++;
}

KEEP int32_t sdp_wait(uint32_t event,uint32_t mask,uint32_t mode,
                      uint32_t *flags,uint32_t timeout) {
    if(!sdp_state.active || event!=sdp_state.event)
        return ((Wait)0x800326c1u)(event,mask,mode,flags,timeout);
    sdp_state.waits++;
    /* Model when a hardware IRQ is delivered; its original handler, observer
     * and native event predicate execute on this same CPU and stack. */
    if(((int32_t (*)(uint32_t,uint32_t,uint32_t))0x2102bd05u)(event,mask,timeout))
        ((void (*)(uint32_t))0x8006ea99u)(sdp_state.unit);
    int32_t status=((Wait)0x800326c1u)(event,mask,mode,flags,timeout);
    uint32_t expected=mask==0x183?2:mask==0x185?4:mask;
    uint32_t reason=sdp_state.errors?RAW_ERROR:0;
    /* Stock ANY predicates can return success plus error/software-wakeup bits.
     * A success bit cannot turn a mixed fault notification into safe completion. */
    uint32_t bad_flags=!status && (!(*flags & expected) || (*flags & 0x181u));
    if(status)reason|=TIMEOUT;
    else if(bad_flags)reason|=BAD_FLAGS;
    if(sdp_stop_state.active && event==sdp_stop_state.event) {
        /* The failed data operation remains sticky. Inspect only this stop's
         * raw errors; the outer join retains ownership regardless of its result. */
        if(status || sdp_stop_state.errors || bad_flags)return -50;
        return status;
    }
    if(reason) { fail_join(reason);return -50; }
    return status;
}

KEEP int32_t sdp_command(void *request,uint32_t unit) {
    if(!sdp_state.active || unit!=sdp_state.unit)
        return sdp_stock_command(request,unit);
    sdp_state.commands++;
    if(sdp_stop_state.active && unit==sdp_stop_state.unit &&
       (uint32_t)request==sdp_stop_state.request && *(uint8_t *)request==14)
        return sdp_stock_command(request,unit);
    if(sdp_state.failed)return 11; /* No diagnostic/follow-up resubmission. */
    int32_t status=sdp_stock_command(request,unit);
    if(status || sdp_state.errors)
        fail_join((status?COMMAND_ERROR:0) | (sdp_state.errors?RAW_ERROR:0));
    return sdp_state.failed?11:status;
}

static int32_t transfer(void *request,uint32_t unit,Command stock) {
    if(sdp_state.active)return 11;
    const uint32_t *words=request;
    sdp_state.unit=unit;
    sdp_state.event=*(volatile uint32_t *)(0x808e28e0u+unit*16);
    sdp_stop_begin(unit,sdp_state.event);
    sdp_recovery_begin(unit,sdp_state.event);
    sdp_state.buffer=words[0];sdp_state.bytes=words[1]*512u;
    sdp_state.raw=0;sdp_state.errors=0;sdp_state.failed=0;sdp_state.reasons=0;
    sdp_state.waits=0;sdp_state.commands=0;sdp_state.join_calls=0;
    sdp_state.joined=0;sdp_state.finished=0;sdp_state.active=1;
    int32_t status=stock(request,unit);
    /* Original dispatcher owns its unit token around this driver callback.
     * Check here before returning to its unlock, with all native buffers live.
     * Even nominal success needs explicit completion in this experiment. */
    if(sdp_finish_port)for(;;) {
        if(((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t,int32_t,uint32_t))sdp_finish_port)(
              unit,sdp_state.event,sdp_state.buffer,sdp_state.bytes,status,sdp_state.failed)==1)break;
        ((void (*)(uint32_t))0x80032251u)(1);
    }
    sdp_state.finished=1;sdp_state.active=0;
    return sdp_state.failed?17:status;
}
KEEP int32_t sdp_read(void *request,uint32_t unit) {
    return transfer(request,unit,sdp_stock_read);
}
KEEP int32_t sdp_write(void *request,uint32_t unit) {
    return transfer(request,unit,sdp_stock_write);
}
