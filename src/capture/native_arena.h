#ifndef L6_NATIVE_ARENA_H
#define L6_NATIVE_ARENA_H
#include "native_worker.h"
#include "history_storage.h"
#ifdef L6_CAPTURE_STORAGE_LEASE
#include "storage_lease.h"
#endif

typedef struct {
    void *allocation;
    uint32_t requested_bytes;
    SessionManager *manager;
    NativeWorker *worker;
    uint32_t descriptor[10];
    HistoryStorage history;
#ifdef L6_CAPTURE_STORAGE_LEASE
    StorageLease lease;
#endif
} NativeCaptureArena;

/* Optional v1.10 heap-backed alternative to the fixed audio-buffer gap.
 * Call only from cold, exclusive Thread-mode initialization, before publishing
 * hooks or starting the optional worker. A successful allocation remains owned
 * until reboot, including after registration failure. No live free/reset API.
 * The caller must budget later stock allocations and worker stack separately.
 * Returning storage does not authorize worker release or establish SD readiness.
 * This adapter is built only in separate offline arena/composition fixtures. */
NativeCaptureArena *native_arena_alloc(uint32_t slots,uint32_t session,uint32_t queue);
/* Requested payload, including worst-case 32-byte alignment padding. Native
 * allocator metadata is additional. Zero means an invalid slot count. */
uint32_t native_arena_bytes(uint32_t slots);
/* Small heap-owned objects, history in separately owned regions. Copies the
 * caller's validated metadata into this permanent arena. External history must
 * remain exclusively owned until reboot, outside the native heap/control; this API does not reserve it in stock
 * firmware or establish storage admission. No sample payload is cleared here. */
NativeCaptureArena *native_arena_alloc_external(const HistoryStorage*,uint32_t slots,
                                               uint32_t session,uint32_t queue);
uint32_t native_arena_bytes_external(uint32_t slots);
#endif
