/* Emulator-only stop-command observation. No physical recovery implementation. */
#ifndef L6_SD_STOP_PROBE_H
#define L6_SD_STOP_PROBE_H
#include <stdint.h>
typedef struct {
    uint32_t active,unit,event,request,attempted,status,raw,errors;
    uint32_t present_after,system_after;
} SdStopProbe;
extern volatile SdStopProbe sdp_stop_state;
extern volatile uint32_t sdp_join_port;
int32_t sdp_failed_scope(uint32_t unit,uint32_t buffer,uint32_t bytes);
void sdp_stop_begin(uint32_t unit,uint32_t event);
int32_t sdp_stop_attempt(uint32_t unit,uint32_t buffer,uint32_t bytes);
int32_t sdp_stop_join(uint32_t unit,uint32_t buffer,uint32_t bytes,uint32_t reason);
#endif
