#ifndef OD_WORK_OWNERSHIP_H
#define OD_WORK_OWNERSHIP_H
#include "admission_gate.h"
#define OD_OWNER_SLOTS 16
enum { OWN_OK, OWN_BUSY, OWN_STALE, OWN_CONFLICT, OWN_FAULT, OWN_FULL };
enum { OWN_STREAM=1, OWN_READ, OWN_SEEK, OWN_CARD, OWN_PROMOTION, OWN_SCAN, OWN_SESSION };
enum { OWN_PREPARED=1, OWN_OFFERED, OWN_QUEUED, OWN_RUNNING,
       OWN_DONE, OWN_REJECTED, OWN_EXCLUSIVE, OWN_SEALED };
enum { OWN_ACCEPTED=1, OWN_NOT_SENT, OWN_UNCERTAIN };
typedef struct { uint32_t kind, args[4]; } OwnRequest;
typedef struct {
    uint32_t ticket, parent, children, phase, submission, producer_done, wait_failed;
    OwnRequest request;
} OwnEntry;
typedef struct {
    OdGate gate;
    uint32_t lock, sequence;
    OwnEntry entries[OD_OWNER_SLOTS];
} OwnLedger;

/* Zero once before participants start. Do not reset/reuse a live ledger.
 * All operations try a short atomic lock; BUSY means NO operation was done.
 * Callers must retry safely or retain ownership and stop. No lock is held while
 * executing stock code or waiting for another task. Tickets never wrap/reuse.
 * This ledger must be the only admission owner of its embedded gate. */
int32_t od_own_reserve(OwnLedger *,const OwnRequest *,uint32_t *ticket);
int32_t od_own_child(OwnLedger *,uint32_t parent,const OwnRequest *,uint32_t *ticket);
int32_t od_own_promote(OwnLedger *,uint32_t *ticket);
/* Non-retiring join for an exclusive owner before its next phase. */
int32_t od_own_exclusive_drained(OwnLedger *,uint32_t ticket);
int32_t od_own_promote_end(OwnLedger *,uint32_t ticket,uint32_t failed);
int32_t od_own_offer(OwnLedger *,uint32_t ticket);
int32_t od_own_submitted(OwnLedger *,uint32_t ticket,uint32_t outcome);
int32_t od_own_producer_done(OwnLedger *,uint32_t ticket,uint32_t wait_failed);
int32_t od_own_claim(OwnLedger *,uint32_t ticket,const OwnRequest *);
int32_t od_own_complete(OwnLedger *,uint32_t ticket);
int32_t od_own_cancel_prepared(OwnLedger *,uint32_t ticket);
/* Retire a synchronous session only after all attributed children finished. */
int32_t od_own_finish_session(OwnLedger *,uint32_t ticket);
/* Non-retiring check, for final result validation after all children join. */
/* Seal a drained session against any further child admission. No I/O latch. */
int32_t od_own_seal_session(OwnLedger *,uint32_t ticket);
int32_t od_own_session_drained(OwnLedger *,uint32_t ticket);
/* Ticket transport fits the existing 16-byte stream queue. Its interpretation
 * changes, so both endpoints must change together after draining old messages. */
int32_t od_own_stream_message(OwnLedger *,uint32_t ticket,uint32_t words[4]);
int32_t od_own_stream_decode(OwnLedger *,const uint32_t words[4],uint32_t args[4],uint32_t *ticket);
#endif
