#ifndef L6_STORAGE_TRANSITION_H
#define L6_STORAGE_TRANSITION_H
#include "storage_lease.h"
enum {ST_USB_START,ST_USB_STOP,ST_USB_CHANGE,ST_CARD_RELEASE,ST_CARD_SETUP};
typedef struct {
    uint32_t status;
    int32_t native_result;
} StorageTransitionResult;
/* Offline caller-contract experiment, not an entry-point hook.
 * Main owns the ENTIRE request, preserves stock admission/ordering checks and
 * calls this before any request side effects. This only excludes extra capture;
 * it does not establish exclusion of other native storage users/sources.
 * 11 means no native transition ran: retain the request/continuation, allow
 * normal completion service and try later. 12 means invalid caller/arguments.
 * 0 means the original native body returned; native_result preserves its return
 * and is NOT evidence that mount/USB setup succeeded. Do not retry a completed
 * request. The caller must preserve ordering and backpressure for other requests.
 * No request storage, private input queue, wait loop or Main wakeup is added.
 * Returning this status from a stock callee is UNSAFE: stock callers ignore it.
 * Lower physical joining remains a prerequisite of the storage lease. */
StorageTransitionResult storage_transition_try(StorageLease *,uint32_t operation,
                                               uint32_t argument,uint32_t profile);
#endif
