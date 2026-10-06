/* Emulator-only: observe ONE stock CMD12 while the failed transfer is retained.
 * A successful command does not mean DMA/card recovery. The default stop join
 * delegates to MODEL port 0x2102bc00; checked recovery reuses the attempt alone.
 * This fixture does not explicitly request reset, recreate events, retry data
 * or admit I/O. The original command engine's own error paths are preserved.
 * Fixture state is reset for each model transfer, never on a device. */
#include "sd_stop_probe.h"
#define KEEP __attribute__((used,retain))
KEEP volatile SdStopProbe sdp_stop_state;

KEEP void sdp_stop_begin(uint32_t unit,uint32_t event) {
    sdp_stop_state.active=0;sdp_stop_state.unit=unit;sdp_stop_state.event=event;
    sdp_stop_state.request=0;sdp_stop_state.attempted=0;sdp_stop_state.status=0;
    sdp_stop_state.raw=0;sdp_stop_state.errors=0;
    sdp_stop_state.present_after=0;sdp_stop_state.system_after=0;
}

KEEP int32_t sdp_stop_attempt(uint32_t unit,uint32_t buffer,uint32_t bytes) {
    if(!sdp_failed_scope(unit,buffer,bytes) || sdp_stop_state.active)return 0;
    if(!sdp_stop_state.attempted) {
        uint32_t response=0;
        uint32_t request[6]={14,0,(uint32_t)&response,0,0,0};
        sdp_stop_state.unit=unit;
        sdp_stop_state.event=*(volatile uint32_t *)(0x808e28e0u+unit*16);
        sdp_stop_state.request=(uint32_t)request;
        sdp_stop_state.attempted=1;
        sdp_stop_state.raw=0;sdp_stop_state.errors=0;sdp_stop_state.active=1;
        /* Original public command wrapper -> scoped command trampoline -> stock
         * engine. Separate stop observations avoid the failed transfer's sticky
         * error recursively reentering join or suppressing this one command. */
        sdp_stop_state.status=(uint32_t)((int32_t (*)(void *,uint32_t))0x8006b0b9u)(request,unit);
        sdp_stop_state.present_after=*(volatile uint32_t *)0x402c0024u;
        sdp_stop_state.system_after=*(volatile uint32_t *)0x402c002cu;
        sdp_stop_state.active=0;sdp_stop_state.request=0;
    }
    return 1;
}

KEEP int32_t sdp_stop_join(uint32_t unit,uint32_t buffer,uint32_t bytes,uint32_t reason) {
    if(!sdp_stop_attempt(unit,buffer,bytes))return 0;
    return ((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t))0x2102bc01u)(
          unit,buffer,bytes,reason);
}
