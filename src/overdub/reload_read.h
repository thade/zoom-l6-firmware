#ifndef OD_RELOAD_READ_H
#define OD_RELOAD_READ_H
#include "reload_ownership.h"
enum {RR_EMPTY,RR_RESERVED,RR_OFFERED,RR_SUBMITTED,RR_RUNNING,RR_OBSERVED,RR_JOIN,RR_DONE};
#define RR_SHORT_READ UINT32_C(0xffff0003)
typedef struct {
    uint32_t lock,phase,ticket;
    RlEnvelope tag;
    OwnRequest request;
    uint32_t actual,raw_status,error;
    RlCoordinator *coordinator;
    uint32_t queue_state;
} RrRead;
#define RR_QUEUE_SLOTS 8
#define RR_QUEUE_MAGIC UINT32_C(0x52525131)
#define RR_QUEUE_FORWARD 6
typedef struct {uint32_t lock;RrRead *read;uint32_t ticket;} RrQueueTask;
/* Existing 16-byte queue: [magic, slot, ticket, 0]. Table and task context are
 * permanent and caller-owned; bind both endpoints before admitting new reads.
 * Slot identities/pointers must remain stable; all slots share one coordinator
 * and its ticket-generating ledger. Packet slot must name the supplied read.
 * Native task identity checks and
 * hook installation are not supplied here. No packet contains a raw pointer.
 * Ordinary kind-0 reads/kind-1 seeks are forwarded without owned-read evidence. */
int32_t rr_queue_packet(RrRead *,uint32_t ticket,uint32_t slot,uint32_t words[4]);
int32_t rr_queue_decode(RrRead *const slots[RR_QUEUE_SLOTS],RrQueueTask *,const uint32_t words[4],uint32_t original[4]);
int32_t rr_queue_observe(RrQueueTask *,uint32_t raw_status,uint32_t actual);
/* Call after all file-worker buffer access and its semaphore signal return.
 * BUSY retains the task context; do not dequeue another message until resolved. */
int32_t rr_queue_return(RrQueueTask *);
/* Permanent zero-once context per outstanding read. Reuse only after DONE.
 * This scope is an internal lifetime reservation, NOT a replacement queue ABI.
 * Caller binds the envelope before send, transports the ticket to the file task,
 * and captures public-read status/count before they are masked. Those native
 * bindings are not installed. No lock spans file IO or a semaphore wait.
 * Initial sample reads require exactly requested bytes with raw status zero.
 * EOF is not exempted: periodic refill/intentional EOF padding is outside scope. */
int32_t rr_begin(RlCoordinator *,RrRead *,const RlEnvelope *,const uint32_t args[3]);
/* Native producer variant: args[3] is the nonzero file handle captured before
 * publication. It is immutable in the ledger request and checked by the reader. */
int32_t rr_begin_handle(RlCoordinator *,RrRead *,const RlEnvelope *,const uint32_t args[4]);
/* Retry BUSY with the same ticket; do not send until ready returns OK. */
int32_t rr_ready(RlCoordinator *,RrRead *,uint32_t ticket);
/* File-task observation after public read returns; one observation per ticket. */
int32_t rr_observe(RrRead *,uint32_t ticket,uint32_t raw_status,uint32_t actual);
/* Producer calls only after its matching file-worker completion/wait has joined.
 * An absent observation cannot be replaced by the wait result. Error metadata
 * precedes releasing the read scope; BUSY retries never repeat file IO. */
int32_t rr_finish(RlCoordinator *,RrRead *,uint32_t ticket);
#endif
