#ifndef OD_READ_PRODUCER_H
#define OD_READ_PRODUCER_H
#include "reload_read.h"
#include "reload_transport.h"
typedef struct {
    RlCoordinator *coordinator;
    RtTask *tasks[2]; /* assignment worker, Main */
    uint32_t ids[2],queue,semaphore;
    RrRead *reads[2];uint32_t slots[2];
    int32_t (*send)(uint32_t,const uint32_t *);
    int32_t (*wait)(uint32_t,uint32_t);
    void (*yield)(void); /* Must give the file worker an opportunity to run. */
} RpBinding;
/* Cold, permanent binding. Both RrRead slots must also be in the file-worker
 * table under the supplied indices. Pointers remain valid; no task recycling. */
int32_t rp_bind(const RpBinding *);
/* Read-only preflight for the single cold integration caller. */
int32_t rp_can_bind(const RpBinding *);
/* Cold ordinary extension must share the already-bound coordinator/queue. */
int32_t rp_ordinary_ready(RlCoordinator *,uint32_t queue);
/* Called by a currently RUNNING, attributed reload branch before publication.
 * Takes a snapshot of the request, branch tag and native file handle. No IO.
 * With pf_bind, pins the pad against wrapped mutations until joined/released.
 * Ordinary reads use the optional ordinary producer binding or stock path. */
int32_t rp_begin(uint32_t pad,uint32_t buffer,uint32_t bytes);
/* Advance one retained phase. BUSY requires another step, NOT another begin.
 * Send and a bounded one-tick native wait are each invoked at most once. JOIN
 * retries use yield; a shared notification is never matching completion. The enclosing stock
 * prefetch must not resume until OK. Native synchronous callback glue remains
 * uninstalled; this component is not a drop-in return-code replacement. */
int32_t rp_step(void);
/* After OK: original send result, completion=1, read ticket. Retained I/O errors
 * still reject reload verification. Notification timeout alone is not failure. */
int32_t rp_result(uint32_t out[3]);
/* Synchronous adapter for an explicitly attributed initial-prefetch callback.
 * Same three arguments and wait-result return ABI as stock 0x80036208. BUSY
 * stays inside this call, including temporarily blocked begin/pin admission.
 * Invariant failures latch the gate and park forever;
 * the stock caller ignores return codes, so returning an error is not safe.
 * Bind before installing/calling. Ordinary callbacks use the dispatcher and
 * their separate adapter. This is not a global replacement by itself. */
int32_t rp_callback(uint32_t pad,uint32_t buffer,uint32_t bytes);
/* Entry forwarder captures the original LR before any C call. Dispatcher uses
 * native identity + complete task state + exact initial-prefetch continuation.
 * Other tasks and fully inactive bound tasks use op_read when cold-bound,
 * otherwise retain stock reads. Malformed or
 * transitional owned contexts park rather than being downgraded to ordinary.
 * Bind both endpoints before cold installation; no live cutover/task reuse.
 * These are compiled emulator hooks, not an installed firmware patch. */
int32_t rp_read_entry(uint32_t pad,uint32_t buffer,uint32_t bytes);
int32_t rp_dispatch(uint32_t pad,uint32_t buffer,uint32_t bytes,uint32_t caller_lr);
int32_t rp_seek_entry(uint32_t pad,uint32_t offset,uint32_t origin);
int32_t rp_seek_dispatch(uint32_t pad,uint32_t offset,uint32_t origin);
#endif
