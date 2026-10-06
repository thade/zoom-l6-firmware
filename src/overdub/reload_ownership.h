#ifndef OD_RELOAD_OWNERSHIP_H
#define OD_RELOAD_OWNERSHIP_H
#include "work_ownership.h"
#define RL_SLOTS 8
#define RL_MAGIC UINT32_C(0x524c4431)
enum {RL_WORKER=1,RL_UI=2};
enum {RL_UNVERIFIED,RL_VERIFIED,RL_REJECTED};
typedef struct {uint32_t magic,owner,child,role;} RlEnvelope;
typedef struct {
    uint32_t owner,worker,ui,worker_claimed,worker_done,worker_sent,producer_done;
    uint32_t ui_claimed,ui_done,ui_sent,error,verified;
} RlJob;
typedef struct {OwnLedger *ledger;uint32_t lock;RlJob jobs[RL_SLOTS];uint32_t cleanup,draining,manager;} RlCoordinator;
/* Single trusted transition owner: begin closes new admission while existing
 * jobs drain; ready acquires cleanup only after verified roots retire; end
 * reopens admission. No reset/cancel or automatic postcondition proof. */
int32_t rl_transition_begin(RlCoordinator *);
int32_t rl_transition_ready(RlCoordinator *);
int32_t rl_transition_end(RlCoordinator *);
/* Whole cleanup exclusion: begin only with no reload jobs; blocks new admission
 * until end, without holding the short metadata latch across stock calls. */
int32_t rl_cleanup_begin(RlCoordinator *);
int32_t rl_cleanup_end(RlCoordinator *);
/* Permanent zero-once storage, set ledger before participants run. The proposed
 * tagged transport is NOT the stock 32-byte callback or 20-byte UI event ABI.
 * Both endpoints must change together; old queues must drain before enabling.
 * Stock bodies run outside this short metadata latch. Busy retains work; a
 * consumer must retry a dequeued envelope, never discard it on contention.
 * Reserve before the original producer's first side effect. Its containing
 * USB/card owner is optional parent, not inferred from stock busy/status flags. */
/* Manager lease serializes a planned reload from before producer admission
 * until final retirement. Token is the permanent manager address, not a lock. */
int32_t rl_manage_begin(RlCoordinator *,uint32_t token);
int32_t rl_manage_end(RlCoordinator *,uint32_t token);
int32_t rl_begin_managed(RlCoordinator *,uint32_t token,uint32_t parent,uint32_t *owner);
int32_t rl_seal(RlCoordinator *,uint32_t token,uint32_t owner);
int32_t rl_begin(RlCoordinator *,uint32_t parent,uint32_t *owner);
int32_t rl_envelope(RlCoordinator *,uint32_t owner,uint32_t role,RlEnvelope *);
int32_t rl_prepare_ui(RlCoordinator *,uint32_t owner);
int32_t rl_sent(RlCoordinator *,uint32_t owner,uint32_t role,uint32_t outcome);
int32_t rl_producer_return(RlCoordinator *,uint32_t owner);
int32_t rl_claim(RlCoordinator *,const RlEnvelope *);
int32_t rl_complete(RlCoordinator *,const RlEnvelope *);
/* Record checked I/O failures; stock successful-looking returns cannot erase
 * them. This function takes the current task's attributed envelope, never a
 * global mutable current owner shared by unrelated worker/UI tasks. */
int32_t rl_io_error(RlCoordinator *,const RlEnvelope *,uint32_t error);
/* Reserve a synchronous read scope beneath a currently executing branch.
 * The caller must keep it until the attributed read and its wait have returned. */
int32_t rl_read_reserve(RlCoordinator *,const RlEnvelope *,const OwnRequest *,uint32_t *ticket);
/* External postcondition policy remains unbound by default. VERIFIED requires
 * both stock bodies and all descendants returned, plus caller-owned final
 * path/options/I/O evidence collected after those joins (not an older snapshot).
 * All asynchronous descendants must be attached under the envelope child. */
int32_t rl_verify(RlCoordinator *,uint32_t owner,uint32_t evidence);
int32_t rl_finish(RlCoordinator *,uint32_t owner);
#endif
