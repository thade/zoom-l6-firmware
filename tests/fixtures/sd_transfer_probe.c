/* Offline SD ownership experiment ONLY. No physical cancellation implementation.
 * Fixed 0x2102bd00/04 callbacks are emulator models. Never bind on a device.
 * L6_SD_RETAIN_ONLY excludes both callbacks and all stop/recovery code: faults
 * yield forever with the original frames owned. Its source port remains unbound.
 * Entry admission assumes prior hardware work/IRQs joined and stale status
 * drained; a per-unit software lock does not establish that precondition. */
#include <stdint.h>
#ifndef L6_SD_RETAIN_ONLY
#include "sd_stop_probe.h"
#include "sd_recovery_probe.h"
#endif
#include "sd_chunk_probe.h"
#include "sd_admission_probe.h"
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
#ifndef L6_SD_RETAIN_ONLY
KEEP volatile uint32_t sdp_join_port=0x2102bd01u;
/* Capture composition selects this separate MODEL port explicitly. Check
 * completion while the original unit token AND transfer/file frames are live,
 * including nominal success. Zero leaves older experiments unchanged.
 * It is not a physical completion detector and must never be device-bound. */
KEEP volatile uint32_t sdp_finish_port;
#endif
/* Per-chunk checkpoint BEFORE bounce copy/reuse or direct-driver unwind.
 * This opt-in MODEL port is not a physical completion implementation. */
KEEP volatile uint32_t sdp_chunk_finish_port;
KEEP volatile SdChunkProbe sdp_chunk_state;
#ifdef L6_SD_RETAIN_ONLY
extern int32_t sdp_stock_enumerate(uint32_t);
extern int32_t sdp_stock_startup_read(void *,uint32_t);
#endif
/* Opt-in offline cache experiment. Its caller additionally MODELS physical
 * read completion and exclusive cache-line ownership. The leaf helper writes
 * real candidate SCB maintenance registers; Unicorn models their effects.
 * Raw TC/event success here still does not establish freshness or DMA join.
 * Zero preserves all prior experiments. Never bind this port on the device. */
KEEP volatile uint32_t sdp_cache_read_port;
static volatile uint32_t cache_read_address,cache_read_bytes,cache_read_raw;
enum { RAW_ERROR=1, BAD_FLAGS=2, TIMEOUT=4, COMMAND_ERROR=8, BAD_CHUNK=16 };

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
    if(cache_read_address)cache_read_raw|=raw;
    if(sdp_chunk_state.active)sdp_chunk_state.raw|=raw;
#ifndef L6_SD_RETAIN_ONLY
    if(sdp_stop_state.active && unit==sdp_stop_state.unit) {
        sdp_stop_state.raw|=raw;
        sdp_stop_state.errors|=raw & 0x157f0000u;
    }
#endif
}

static void fail_join(uint32_t reason) {
    sdp_state.reasons|=reason;
#ifndef L6_SD_RETAIN_ONLY
    if(sdp_state.failed)return; /* Serialized owner already handles this fault. */
#endif
    /* Retained builds have no recovery owner which may authorize a return.
     * Even an unexpected second entry must keep an already failed scope held. */
    sdp_state.failed=1;
    for(;;) {
        sdp_state.join_calls++;
        /* Research recovery requires explicit modeled JOINED (1). The retained
         * variant has no exit: the original SD mutex/buffers stay owned. */
#ifndef L6_SD_RETAIN_ONLY
        if(((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t))sdp_join_port)(
              sdp_state.unit,sdp_state.buffer,sdp_state.bytes,sdp_state.reasons)==1)break;
#endif
        ((void (*)(uint32_t))0x80032251u)(1);
    }
    sdp_state.joined++;
}

static int32_t chunk_identity(void) {
    return sdp_chunk_state.active && !sdp_state.unit &&
           *(volatile uint32_t *)0x808e28e0u==sdp_state.event &&
           *(volatile uint32_t *)0x808e291cu==sdp_chunk_state.task;
}
#ifdef L6_SD_RETAIN_ONLY
/* Enumeration is a separate retained scope. These checks close the native
 * ANY-event failure path, not the initial physical-source contract. No source
 * port is granted here, and normal block IO still requires its own admission. */
static int32_t enumeration_identity(uint32_t event) {
    return !sdp_state.unit && event && event==sdp_state.event &&
        *(volatile uint32_t *)0x808e28e0u==event &&
        sdp_admission_state.task &&
        *(volatile uint32_t *)0x808e291cu==sdp_admission_state.task &&
        !((*(volatile uint32_t *)0xe000e10cu |
           *(volatile uint32_t *)0xe000e20cu |
           *(volatile uint32_t *)0xe000e30cu)&(1u<<15));
}
static void startup_read_finish(void) {
    if(!chunk_identity() || !(sdp_chunk_state.raw&2u))fail_join(BAD_CHUNK);
    for(;;) {
        uint32_t raw=sdp_chunk_state.raw|*(volatile uint32_t *)0x402c0030u;
        uint32_t protocol=*(volatile uint32_t *)0x402c0028u;
        if(!chunk_identity() || (raw&0x157f0004u) ||
           (protocol&0x30330u)!=0x20u || (protocol&6u)>2u ||
           (*(volatile uint32_t *)0x402c0048u&0x11u)!=0x10u ||
           *(volatile uint32_t *)0x402c0004u!=(0x10000u|sdp_chunk_state.bytes))
            fail_join(BAD_CHUNK);
        if(!(*(volatile uint32_t *)0x402c0024u&0x300u) &&
           !(*(volatile uint32_t *)0x402c002cu&0x07000000u))break;
        ((void (*)(uint32_t))0x80032251u)(1);
    }
    sdp_chunk_state.active=0;sdp_chunk_state.completed++;
}
#endif
static int32_t chunk_finish(void) {
    if(!chunk_identity() || !(sdp_chunk_state.raw&2u) || (sdp_chunk_state.raw&4u)) {
        fail_join(BAD_CHUNK);return -50;
    }
    for(;;) {
        if(!chunk_identity() || (sdp_chunk_state.raw&4u)) { fail_join(BAD_CHUNK);return -50; }
        if(sdp_state.errors) { fail_join(RAW_ERROR);return -50; }
        /* Host read/write-transfer activity and reset must be clear. DAT0,
         * CDIHB and DLA can describe trailing card busy after host DMA ends;
         * they are not substituted for the separate MODEL join permission. */
        if(!(*(volatile uint32_t *)0x402c0024u&0x300u) &&
           !(*(volatile uint32_t *)0x402c002cu&0x07000000u)) {
            sdp_chunk_state.checks++;
            int32_t joined=((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t))
                    sdp_chunk_finish_port)(sdp_state.unit,sdp_state.event,
                        sdp_chunk_state.address,sdp_chunk_state.bytes);
            /* The provider cannot override a late visible error, changed
             * owner/event, host activity or reset at its return boundary. */
            if(!chunk_identity() || (sdp_chunk_state.raw&4u)) { fail_join(BAD_CHUNK);return -50; }
            if(sdp_state.errors) { fail_join(RAW_ERROR);return -50; }
            if(joined==1 && !(*(volatile uint32_t *)0x402c0024u&0x300u) &&
               !(*(volatile uint32_t *)0x402c002cu&0x07000000u))break;
        }
        ((void (*)(uint32_t))0x80032251u)(1);
    }
    sdp_chunk_state.active=0;sdp_chunk_state.completed++;return 0;
}

KEEP int32_t sdp_wait(uint32_t event,uint32_t mask,uint32_t mode,
                      uint32_t *flags,uint32_t timeout) {
    uint32_t site=(uint32_t)__builtin_return_address(0)&~1u;
    uint32_t data_site=site==0x8006a06eu || site==0x8006a1f8u ||
                       site==0x8006ac72u || site==0x8006ae14u;
#ifdef L6_SD_RETAIN_ONLY
    if(sdp_state.active==2 &&
       (!enumeration_identity(event) || mode!=1 ||
        (mask!=0x183u && mask!=0x185u && mask!=8u))) {
        fail_join(BAD_CHUNK);return -50;
    }
#endif
    if(sdp_chunk_finish_port && sdp_state.active && data_site &&
       (event!=sdp_state.event || mask!=0x185u || !chunk_identity())) {
        fail_join(BAD_CHUNK);return -50;
    }
    if(!sdp_state.active || event!=sdp_state.event)
        return ((Wait)0x800326c1u)(event,mask,mode,flags,timeout);
    sdp_state.waits++;
    /* Model when a hardware IRQ is delivered; its original handler, observer
     * and native event predicate execute on this same CPU and stack. */
#ifndef L6_SD_RETAIN_ONLY
    if(((int32_t (*)(uint32_t,uint32_t,uint32_t))0x2102bd05u)(event,mask,timeout))
        ((void (*)(uint32_t))0x8006ea99u)(sdp_state.unit);
#endif
    int32_t status=((Wait)0x800326c1u)(event,mask,mode,flags,timeout);
    uint32_t expected=mask==0x183?2:mask==0x185?4:mask;
    uint32_t reason=sdp_state.errors?RAW_ERROR:0;
    /* Stock ANY predicates can return success plus error/software-wakeup bits.
     * A success bit cannot turn a mixed fault notification into safe completion. */
    uint32_t bad_flags=!status && (!(*flags & expected) || (*flags & 0x181u));
    if(status)reason|=TIMEOUT;
    else if(bad_flags)reason|=BAD_FLAGS;
#ifndef L6_SD_RETAIN_ONLY
    if(sdp_stop_state.active && event==sdp_stop_state.event) {
        /* The failed data operation remains sticky. Inspect only this stop's
         * raw errors; the outer join retains ownership regardless of its result. */
        if(status || sdp_stop_state.errors || bad_flags)return -50;
        return status;
    }
#endif
    if(reason) { fail_join(reason);return -50; }
#ifdef L6_SD_RETAIN_ONLY
    if(sdp_state.active==2) {
        if(!enumeration_identity(event))fail_join(BAD_CHUNK);
        if(mask==0x185u) {
            if(site!=0x80069d68u)fail_join(BAD_CHUNK);
            startup_read_finish();
        }
    }
#endif
    if(sdp_chunk_finish_port && data_site && chunk_finish())return -50;
    if(sdp_cache_read_port && mask==0x185u) {
        uint32_t mix=*(volatile uint32_t *)0x402c0048u;
        uint32_t dma=cache_read_address;
        /* DMA read, excluding the exact native per-unit bounce area. Its
         * address is not cache-line aligned; never invalidate its neighbours.
         * The data wait must remain inside its owned native stack and token. */
        if((mix&0x11u)==0x11u && dma!=0x2000c4d4u+(sdp_state.unit<<12)) {
            if(!(cache_read_raw&2u) ||
               ((int32_t (*)(uint32_t,uint32_t))sdp_cache_read_port)(dma,cache_read_bytes)) {
                fail_join(BAD_FLAGS);return -50;
            }
        }
    }
    return status;
}

KEEP int32_t sdp_command(void *request,uint32_t unit) {
    if(!sdp_state.active || unit!=sdp_state.unit)
        return sdp_stock_command(request,unit);
    sdp_state.commands++;
#ifndef L6_SD_RETAIN_ONLY
    if(sdp_stop_state.active && unit==sdp_stop_state.unit &&
       (uint32_t)request==sdp_stop_state.request && *(uint8_t *)request==14)
        return sdp_stock_command(request,unit);
#endif
    if(sdp_state.failed)return 11; /* No diagnostic/follow-up resubmission. */
    if(sdp_chunk_finish_port && sdp_state.active==1) {
        const uint32_t *words=request;
        uint32_t code=*(const uint8_t *)request;
        if(code==22u || code==23u || code==32u || code==33u) {
            uint32_t address=*(volatile uint32_t *)0x402c0000u;
            uint32_t bytes=(words[4]&0xffffu)*512u;
            uint32_t bounce=address==0x2000c4d4u;
            uint32_t caller=sdp_state.buffer<=UINT32_MAX-sdp_state.bytes &&
                bytes<=sdp_state.bytes && address>=sdp_state.buffer &&
                address-sdp_state.buffer<=sdp_state.bytes-bytes;
            if(sdp_chunk_state.active || sdp_state.unit || words[5]!=1 ||
               (words[4]>>16) || !address || !bytes || address>UINT32_MAX-bytes ||
               !(caller || (bounce && bytes<=4096u))) {
                fail_join(BAD_CHUNK);return 11;
            }
            if(sdp_chunk_admit_port &&
               (!sdp_admission_state.prepared || sdp_admission_state.fault ||
                sdp_admission_state.address!=address ||
                sdp_admission_state.task!=*(volatile uint32_t *)0x808e291cu)) {
                fail_join(BAD_CHUNK);return 11;
            }
            sdp_admission_state.prepared=0;
            sdp_chunk_state.code=code;sdp_chunk_state.address=address;
            sdp_chunk_state.bytes=bytes;sdp_chunk_state.raw=0;
            sdp_chunk_state.task=*(volatile uint32_t *)0x808e291cu;
            sdp_chunk_state.active=1;
        } else if(code!=15u) {
            /* Only block IO and its non-data CMD13 status are supported.
             * Auxiliary diagnostic/PIO formats must not escape this guard.
             * The separately authorized retained-error stop is handled above. */
            fail_join(BAD_CHUNK);return 11;
        }
    }
    if(sdp_cache_read_port) {
        const uint32_t *words=request;
        uint32_t code=*(const uint8_t *)request;
        /* The exercised block-read opcodes use 512-byte sectors. Snapshot the
         * programmed start BEFORE the command starts DMA. A completion-time
         * DS_ADDR value need not still identify the beginning of the buffer.
         * Every such command gets a new raw latch; an earlier chunk's TC must
         * never satisfy this chunk. Prior hardware/IRQ joining stays modeled. */
        if((code==22u || code==23u) && words[5]) {
            cache_read_address=*(volatile uint32_t *)0x402c0000u;
            cache_read_bytes=(words[4]&0xffffu)*512u;
            cache_read_raw=0;
        }
    }
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
#ifndef L6_SD_RETAIN_ONLY
    sdp_stop_begin(unit,sdp_state.event);
    sdp_recovery_begin(unit,sdp_state.event);
#endif
    sdp_state.buffer=words[0];sdp_state.bytes=words[1]*512u;
    sdp_state.raw=0;sdp_state.errors=0;sdp_state.failed=0;sdp_state.reasons=0;
    sdp_state.waits=0;sdp_state.commands=0;sdp_state.join_calls=0;
    sdp_state.joined=0;sdp_state.finished=0;sdp_state.active=1;
    cache_read_address=0;cache_read_bytes=0;cache_read_raw=0;
    sdp_chunk_state=(SdChunkProbe){0};
#ifdef L6_SD_RETAIN_ONLY
    /* This combined experiment never uses a recovery/JOINED model. Missing
     * admission or completion bindings hold before any native buffer effect. */
    if(!sdp_chunk_admit_port || !sdp_chunk_finish_port)fail_join(BAD_CHUNK);
#endif
    if(sdp_chunk_admit_port)sdp_admission_begin();
    int32_t status=stock(request,unit);
    /* Original dispatcher owns its unit token around this driver callback.
     * Check here before returning to its unlock, with all native buffers live.
     * Even nominal success needs explicit completion in this experiment. */
#ifndef L6_SD_RETAIN_ONLY
    if(sdp_finish_port)for(;;) {
        if(((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t,int32_t,uint32_t))sdp_finish_port)(
              unit,sdp_state.event,sdp_state.buffer,sdp_state.bytes,status,sdp_state.failed)==1)break;
        ((void (*)(uint32_t))0x80032251u)(1);
    }
#else
    if(sdp_chunk_state.active)fail_join(BAD_CHUNK);
#endif
    sdp_chunk_state.active=0;sdp_state.finished=1;sdp_state.active=0;
    return sdp_state.failed?17:status;
}
KEEP int32_t sdp_read(void *request,uint32_t unit) {
    return transfer(request,unit,sdp_stock_read);
}
KEEP int32_t sdp_write(void *request,uint32_t unit) {
    return transfer(request,unit,sdp_stock_write);
}

#ifdef L6_SD_RETAIN_ONLY
KEEP int32_t sdp_enumerate(uint32_t unit) {
    /* Called under the original dispatcher token, before card-ready changes.
     * Only the first unit-zero enumeration is supported; no retry/remount. */
    if(unit || sdp_state.active || sdp_state.finished || sdp_state.failed)
        fail_join(BAD_CHUNK);
    sdp_state=(SdProbe){.active=2,.event=*(volatile uint32_t *)0x808e28e0u};
    sdp_chunk_state=(SdChunkProbe){0};
    sdp_admission_state.task=*(volatile uint32_t *)0x808e291cu;
    if(!enumeration_identity(sdp_state.event))fail_join(BAD_CHUNK);
    int32_t status=sdp_stock_enumerate(unit);
    if(status || sdp_chunk_state.active || !enumeration_identity(sdp_state.event))
        fail_join(COMMAND_ERROR);
    sdp_state.finished=1;sdp_state.active=0;
    return status;
}

KEEP int32_t sdp_startup_read(void *request,uint32_t unit) {
    if(sdp_state.active!=2)return sdp_stock_startup_read(request,unit);
    const uint32_t *words=request;
    uint32_t code=*(const uint8_t *)request;
    /* Traced startup status/SCR/CMD6 reads: one 8- or 64-byte PIO block.
     * Reject other formats before the native driver can touch its buffer. */
    uint32_t bytes=code==41u?8u:64u;
    /* High count bits carry RCA for application commands. The original PIO
     * branch supplies DMA=0 itself; its caller's unused word[5] is not an ABI
     * field and can contain stack data. Do not require it to be initialized. */
    if(unit || (code!=5u && code!=17u && code!=41u) || (words[4]&0xffffu)!=1u ||
       !words[3] || words[3]>UINT32_MAX-bytes ||
       sdp_chunk_state.active || !enumeration_identity(sdp_state.event))
        fail_join(BAD_CHUNK);
    sdp_chunk_state.code=code;sdp_chunk_state.address=words[3];
    sdp_chunk_state.bytes=bytes;sdp_chunk_state.raw=0;
    sdp_chunk_state.task=sdp_admission_state.task;sdp_chunk_state.active=1;
    int32_t status=sdp_stock_startup_read(request,unit);
    if(status || sdp_chunk_state.active || !enumeration_identity(sdp_state.event))
        fail_join(BAD_CHUNK);
    return status;
}
#endif
