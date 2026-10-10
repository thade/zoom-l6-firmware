#ifndef L6_STORAGE_LEASE_H
#define L6_STORAGE_LEASE_H
#include "session_manager.h"
enum {SL_CLOSED,SL_ADMITTED,SL_CLOSING,SL_RETIRED,SL_PIN=4};
typedef struct {
    SessionManager *manager;
    uint32_t control,generation,may_have_file;
} StorageLease;
/* One cold binding to permanent, zeroed storage outside resettable objects.
 * This is compiled only into the separate storage fixture. No device hooks or
 * physical transfer provider are established by these APIs. */
uint32_t storage_lease_bind(StorageLease *,SessionManager *);
/* A trusted setup observer supplies the ACTUAL native mount result (2) and
 * target directory query result (0) from this generation, before release.
 * Flags/outer setup returns are not equivalent observations. Caller must also
 * establish physical completion/cache/memory and transition exclusion. This
 * endpoint cannot prove those external preconditions; no device caller exists.
 * Exactly one nonzero generation may be admitted before reboot. */
uint32_t storage_lease_admit(StorageLease *,uint32_t generation,int32_t mount_result,
                             int32_t directory_result);
/* Close admission immediately; idempotent and nonblocking. The worker keeps
 * its existing file/transfer frames and may execute cancellation cleanup.
 * Main must defer the ENTIRE outer transition before its first side effect;
 * returning BUSY at a lower detach/USB call is not a binding for this API. */
uint32_t storage_lease_close(StorageLease *);
/* Nonblocking 11 until optional file access has stopped and its file is closed,
 * then 0. This does NOT retire ordinary control callbacks or authorize memory
 * reclamation: all objects remain owned until reboot. RETIRED cannot resume or
 * be reauthorized before reboot. This trusts the lower physical-completion
 * contract; software returns alone do not prove it. */
uint32_t storage_lease_join(StorageLease *);
/* Worker-only query under its step pin; closure cannot be reversed. */
uint32_t storage_lease_closing(SessionManager *);
/* Internal manager scope: one pin spans each complete synchronous step,
 * including native file calls, cleanup and automatic next-TMP preparation.
 * Cleanup is allowed while closing; reset/rearm and explicit resume are not. */
uint32_t storage_lease_enter(SessionManager *,uint32_t cleanup);
void storage_lease_leave(SessionManager *);
#endif
