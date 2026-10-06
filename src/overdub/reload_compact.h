#ifndef OD_RELOAD_COMPACT_H
#define OD_RELOAD_COMPACT_H
#include "reload_transport.h"
#include "reload_manager.h"
#include "read_producer.h"
#include "read_worker.h"
/* Permanent single binding. Initialize before hooks/queues become active; no
 * rebinding or task-handle recycling is supported. Device placement unassigned. */
typedef struct {
    RtRuntime *runtime;RtTask *worker,*ui;
    uint32_t worker_id,ui_id,worker_queue,ui_queue;
    int32_t (*receive)(uint32_t,void *);
    void (*yield)(void);
    uint32_t deferred,unbound;
} RcBinding;
int32_t rc_bind(RcBinding *);
/* Optional cold integration, after rc_bind and before any admission/hooks.
 * Enforces the SAME coordinator/tasks/identities and producer/reader slot map.
 * Single caller with quiescent queues: preflight both before either mutation.
 * No live cutover, rollback or task recreation. All pointed storage is permanent;
 * RcBinding/runtime configuration stays fixed (diagnostic fields may change).
 * Only success permits activating the read hooks. */
int32_t rc_bind_reads(const RpBinding *,const RwBinding *);
/* Optional permanent completion manager, initialized before receive activation. */
int32_t rc_bind_manager(RmManager *);
int32_t rc_send_worker(const RtWorkerPacket *);
int32_t rc_send_ui(const RtUiPacket *);
int32_t rc_worker(const uint32_t *);
int32_t rc_ui(const uint32_t *);
/* Both receive ingress paths must use this before dequeuing another message.
 * It retries an already-copied task continuation first. UI buffer is 20 bytes;
 * worker buffer is 32. BUSY yields; caller must not dispatch an invalid buffer. */
int32_t rc_next(uint32_t queue,void *out);
/* Global UI queue send boundary: nonblocking kernel send avoids a full-queue
 * deadlock when cleanup is deferred. Other queue behavior is forwarded. */
int32_t rc_queue(uint32_t queue,const void *message);
uint32_t rc_filter(uint32_t count);
/* Clear/delete return OWN_OK when the body ran, OWN_BUSY when deferred. These
 * are new status contracts: surrounding mode-transition callers must honor them.
 * 'deferred' is a sticky diagnostic mask, not an automatic retry request. */
int32_t rc_clear(void);
int32_t rc_delete(uint32_t kind,uint32_t category,uint32_t code);
/* Retry only the copied UI delivery, retaining the same immutable tickets.
 * Called by Main before receive and by its mode-transition drain loop. */
int32_t rc_retry_ui(void);
int32_t rc_service_owned(void);
enum {RC_MODE_IDLE,RC_MODE_DRAIN,RC_MODE_RUN,RC_MODE_RELEASE,RC_MODE_DONE,RC_MODE_FAILED};
typedef struct {uint32_t lock,phase,error;} RcMode;
int32_t rc_mode5_step(RcMode *);
int32_t rc_mode5_poll(void);
void rc_pause(void);
#endif
