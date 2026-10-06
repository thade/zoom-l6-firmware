/* Test-only candidate-controller sequence. No physical attestation providers. */
#ifndef L6_SD_RECOVERY_PROBE_H
#define L6_SD_RECOVERY_PROBE_H
#include <stdint.h>
enum {
    SDP_QUIET_BEFORE=1,SDP_KERNEL_BEFORE,SDP_RESET_PERMITTED,
    SDP_QUIET_AFTER,SDP_KERNEL_AFTER,SDP_UNWIND_SAFE,
    SDP_QUIET_ADMIT,SDP_KERNEL_ADMIT
};
enum { SDP_REC_START,SDP_REC_STOP,SDP_REC_PERMIT,SDP_REC_RESET,
       SDP_REC_CLEAN,SDP_REC_VERIFY,SDP_REC_DONE,SDP_REC_BLOCKED };
enum { SDP_EVENT_CHANGED=1,SDP_DIRTY_HW,SDP_DIRTY_SW,SDP_NOT_ABORT,
       SDP_STOP_FAILED,SDP_NO_FRESH_CC,SDP_RESET_STALLED,SDP_STILL_ACTIVE,
       SDP_DAT0_BUSY,SDP_CONFIG_CHANGED,SDP_CLOCK_UNSTABLE };
typedef struct {
    uint32_t unit,event,phase,fault,admitted,drains,resets,polls;
    uint32_t raw_before,flags_before,protocol,vendor2,clock,admit_calls,join_calls;
} SdRecoveryProbe;
extern volatile SdRecoveryProbe sdp_recovery_state;
extern volatile uint32_t sdp_admit_port;
int32_t sdp_scope_matches(uint32_t unit,uint32_t event);
int32_t sdp_scope_failed(uint32_t unit,uint32_t event);
void sdp_recovery_begin(uint32_t unit,uint32_t event);
int32_t sdp_recovery_admit(uint32_t unit,uint32_t event);
int32_t sdp_recovery_join(uint32_t unit,uint32_t buffer,uint32_t bytes,uint32_t reason);
int32_t sdp_admit_read(void *request,uint32_t unit);
int32_t sdp_admit_write(void *request,uint32_t unit);
#endif
