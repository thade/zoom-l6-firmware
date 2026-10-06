#ifndef OD_READ_WORKER_H
#define OD_READ_WORKER_H
#include "reload_read.h"
#include "ordinary_io.h"
typedef struct {
    RlCoordinator *coordinator;OiIo *slots[OI_SLOTS];
    int32_t (*seek)(uint32_t,uint32_t,uint32_t);
} RwOrdinary;
typedef struct {
    RlCoordinator *coordinator;
    RrRead *slots[RR_QUEUE_SLOTS];
    uint32_t worker,queue;
    int32_t (*receive)(uint32_t,uint32_t *);
    int32_t (*read)(uint32_t,uint32_t,uint32_t,uint32_t *);
    void (*yield)(void);
} RwBinding;
/* Single cold caller before activation. Configuration copied once; pointed-to
 * coordinator and distinct read slots stay valid permanently. The stock worker
 * and queue handles must already exist. No installed hooks or addresses. */
int32_t rw_bind(const RwBinding *);
/* Read-only preflight for the single cold integration caller. */
int32_t rw_can_bind(const RwBinding *);
/* Optional, single cold caller AFTER rw_bind and BEFORE any rw_next call.
 * Once enabled, raw stock read/seek packets are rejected, not untracked. */
int32_t rw_can_bind_ordinary(const RwOrdinary *);
int32_t rw_bind_ordinary(const RwOrdinary *);
/* Replace ONLY file-worker receive call at 0x80036152. Zero supplies a request;
 * -1 retains/retries, yielding without executing the original request body.
 * The prior body must have fully returned, including its signal call. */
int32_t rw_next(uint32_t queue,uint32_t original[4]);
/* Replace ONLY public-read call at 0x80036184. The bound read port must call
 * the original public read (not recurse through this adapter). Raw result and
 * actual count are retained before returning unchanged to the stock body. */
int32_t rw_read(uint32_t handle,uint32_t buffer,uint32_t bytes,uint32_t *actual);
/* Activate only with the ordinary binding. Replace ONLY seek call at
 * 0x800361bc; bound port bypasses this call site. */
int32_t rw_seek(uint32_t handle,uint32_t offset,uint32_t origin);
#endif
