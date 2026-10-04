#ifndef OD_PLAYBACK_SESSION_H
#define OD_PLAYBACK_SESSION_H
#include "work_ownership.h"
typedef struct {
    uint32_t (*loaded)(uint32_t pad);
    int32_t (*start)(uint32_t pad);
    int32_t (*stop)(uint32_t pad);
    /* OK must mean renderer access is prevented and previous audio readers joined.
     * It must also disable stream production. BUSY retains ownership.
     * The fence persists across session retirement and promotion until rearm.
     * Session retirement separately joins ledger-tracked file worker children.
     * Epoch is the non-reused owner ticket; never accept stale acknowledgments. */
    int32_t (*fence)(uint32_t epoch,uint32_t *acknowledged_epoch);
    uint32_t (*quiet)(void);
    int32_t (*rearm)(uint32_t fenced_epoch,uint32_t new_owner);
    int32_t (*scan)(uint32_t parent);
} OdSessionPort;
typedef struct {
    OwnLedger *ledger;
    const OdSessionPort *port;
    uint32_t operation,owner,playing,closing,fenced_epoch,held;
} OdSession;
/* Zero once before enabling participants, then set ledger/port. Every start,
 * stop, callback and release must use this coordinator. Operation is a try-only
 * serialization latch: no caller spins/waits for it. Workers/renderer MUST NOT
 * require it to progress while a stock operation waits for them. */
int32_t od_session_start(OdSession *,uint32_t pad);
int32_t od_session_stop(OdSession *,uint32_t pad);
int32_t od_session_scan(OdSession *);
int32_t od_session_quiesce(OdSession *);
/* Persistent external shutdown hold; unlike ordinary quiesce it also covers
 * the idle interval before exclusive publication ownership is acquired. */
int32_t od_session_hold(OdSession *);
int32_t od_session_unhold(OdSession *);
#endif
