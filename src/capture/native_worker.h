#ifndef L6_NATIVE_WORKER_H
#define L6_NATIVE_WORKER_H
#include "session_manager.h"
#include "../overdub/control_coordinator.h"
typedef struct {
    uint32_t (*prepare)(OcCoordinator*,uint32_t,void (*)(uint32_t,uint32_t),uint32_t (*)(void));
    uint32_t (*arm)(void),(*ready)(void);
    OcCoordinator *control;
    uint32_t audio_task;
} WorkerAudio;
typedef struct {
    uint32_t stack_words,priority,steps_per_pass,poll_ticks,idle_ticks;
} WorkerConfig;
enum {W_EMPTY,W_REGISTERING,W_READY,W_FAILED,W_WAITING,W_AUDIO_WAIT};
typedef struct {
    SessionManager *manager;
    uint32_t task,state,last_status,last_steps,busy;
    WorkerConfig config;
    uint32_t (*audio_arm)(void),(*audio_ready)(void);
    int32_t (*handoff)(void *);
    void *handoff_context;
    uint32_t handoff_status;
} NativeWorker;
/* Optional shared-hook startup binding after successful registration, before
 * scheduler start. A prepare failure permanently fails this worker. Supplied
 * functions/storage outlive it. Does not establish device/storage readiness. */
uint32_t native_worker_bind_audio(NativeWorker *,const WorkerAudio *);
/* Cold, single-caller initialization before scheduler start and before hooks
 * can enter. Queue setup must have completed. Worker storage is permanent and
 * zeroed. Explicit configuration is experimental, not a measured device budget.
 * Registration failure leaves optional capture closed; no automatic retry.
 * Success leaves W_WAITING: task creation does not establish storage readiness. */
uint32_t native_worker_register(NativeWorker *,SessionManager *,const uint32_t descriptor[10],
                                const WorkerConfig *,uint32_t pad,uint32_t serial);
/* Explicit one-way release by the stock Main task AFTER verified initialization
 * and storage admission. Identity checks are not readiness checks. No production
 * caller/hook is wired yet; do not infer readiness from scheduler or mount flags.
 * With audio bound, first requests arming and returns 11 until one whole native
 * audio callback returns. The worker polls readiness after this authorization;
 * Main need not retry and may return to its ordinary indefinite event wait. */
uint32_t native_worker_release(NativeWorker *);
/* Only the registered task may poll. Returns the manager result; last_steps
 * reports work performed. Each manager call may block on IO; this is not a
 * wall-clock execution bound. No automatic resume from STOPPED/BLOCKED. */
uint32_t native_worker_poll(NativeWorker *);
void native_worker_entry(void *);
#endif
