#ifndef OD_CONTROL_COORDINATOR_H
#define OD_CONTROL_COORDINATOR_H
#include <stdint.h>
#define OC_SLOTS 16
enum {OC_OK,OC_BUSY,OC_FULL,OC_STALE,OC_INVALID,OC_EXHAUSTED,OC_FAULT};
enum {OC_EFFECT_A=1,OC_EFFECT_B,OC_MODE_A,OC_MODE_B,OC_MODE_C};
enum {OC_FREE,OC_QUEUED,OC_RUNNING,OC_DONE};
typedef struct {uint32_t ticket,phase,kind,args[2];} OcJob;
typedef struct {
    uint32_t lock,sequence,epoch,closed,running;
    OcJob jobs[OC_SLOTS];
    uint32_t audio_request,audio_ack,audio_fault;
    uint32_t audio_sequence,audio_active,audio_epoch,audio_primary,audio_secondary;
} OcCoordinator;
typedef void (*OcDispatch)(uint32_t,const uint32_t *);
/* Offline proposed dispatcher ABI. Zero once before participants run; storage
 * remains permanent. Accepted is NOT completed. Every accepted job retains a
 * slot until its owner takes DONE. Only scalar payloads for these five complete
 * handlers are supported. No caller source pointers are retained.
 *
 * Submit/close/poll/reopen/take use a try-lock; BUSY means no operation. The
 * worker runs original blocking handlers outside that lock, on a task distinct
 * from audio. New original/UI callers are NOT transparently wrapped here: an
 * upstream dispatcher must defer their entire event and wait for DONE without
 * claiming synchronous completion. FULL requires upstream retention/retry.
 * These boundaries are not installed on the device. */
uint32_t oc_submit(OcCoordinator *,uint32_t kind,const uint32_t args[2],uint32_t *ticket);
uint32_t oc_run_one(OcCoordinator *,OcDispatch);
uint32_t oc_close(OcCoordinator *,uint32_t *epoch);
uint32_t oc_drained(OcCoordinator *,uint32_t epoch);
/* Reopen only after the EXTERNAL sampler/card/recording protocol is ready.
 * This coordinator proves control drain only; it is not a renderer fence. */
uint32_t oc_reopen(OcCoordinator *,uint32_t epoch);
uint32_t oc_take_done(OcCoordinator *,uint32_t ticket);
/* Optional completion barrier after control drain. One permanent coordinator,
 * one serialized audio producer, and serialized upstream mode changes required.
 * Request pins closure: ordinary reopen cannot bypass a pending acknowledgement.
 * Audio never waits for the control lock. Missing callbacks leave BUSY forever;
 * nested/unbalanced/unknown/changed callbacks latch FAULT, with no reset API.
 * begin gets the ACTUAL loaded branch target; end gets current selector slots.
 * The caller preserves machine state around these proposed hooks. No hooks are
 * installed here. Audio continues after ack: this is NOT a pad-reader fence. */
uint32_t oc_audio_request(OcCoordinator *,uint32_t epoch);
uint32_t oc_audio_poll(OcCoordinator *,uint32_t epoch);
uint32_t oc_audio_begin(OcCoordinator *,uint32_t primary,uint32_t secondary);
uint32_t oc_audio_end(OcCoordinator *,uint32_t token,uint32_t primary,uint32_t secondary);
#endif
