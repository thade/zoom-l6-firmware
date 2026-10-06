#ifndef OD_ORDINARY_IO_H
#define OD_ORDINARY_IO_H
#include "pad_file.h"
#define OI_SLOTS 8
#define OI_MAGIC UINT32_C(0x4f494f31)
enum {OI_EMPTY,OI_NEW,OI_RESERVED,OI_PINNED,OI_OFFERED,OI_SUBMITTED,OI_READY,
      OI_QUEUED,OI_RUNNING,OI_OBSERVED,OI_RETURNED,OI_UNPINNED,OI_DONE};
typedef struct {uint32_t kind,pad,first,second,pin_slot,parent;} OiRequest;
typedef struct {
    uint32_t lock,phase,ticket;RlCoordinator *coordinator;OiRequest request;
    OwnRequest scope;uint32_t handle,pin,status,actual;
} OiIo;
typedef struct {uint32_t lock;OiIo *io;uint32_t ticket;} OiTask;
/* Zero-once context and a unique permanent pin slot 2..9 per context. Native
 * producer/task binding and transport hooks are NOT installed by this module.
 * kind 0 preserves read buffer/count; kind 1 preserves seek offset/origin.
 * parent is an explicit live session/refill owner, or zero for ordinary root
 * admission. No inferred reload ownership or implicit promotion bypass. */
int32_t oi_begin(RlCoordinator *,OiIo *,const OiRequest *);
int32_t oi_prepare(OiIo *);
/* Publish exactly once after prepare; uncertain delivery retains ownership. */
int32_t oi_packet(OiIo *,uint32_t slot,uint32_t out[4]);
int32_t oi_decode(OiIo *const slots[OI_SLOTS],OiTask *,const uint32_t words[4],uint32_t out[4]);
/* Before stock IO, compare its actual handle/arguments with the snapshot.
 * Does not revalidate raw handle-table writes outside the pad-file guard. */
int32_t oi_check(OiTask *,uint32_t handle,uint32_t first,uint32_t second);
int32_t oi_observe(OiTask *,uint32_t status,uint32_t actual);
/* Only after stock IO, callbacks, zero fill and semaphore signal have returned. */
int32_t oi_return(OiTask *);
/* Producer joins its matching completion before unpin/retirement. Short reads
 * and IO errors are retained as results, not coerced into reload failure.
 * OK here proves lifetime completion, not successful IO. */
int32_t oi_finish(OiIo *);
int32_t oi_result(OiIo *,uint32_t out[2]);
#endif
