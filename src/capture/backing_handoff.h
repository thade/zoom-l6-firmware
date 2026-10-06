#ifndef L6_BACKING_HANDOFF_H
#define L6_BACKING_HANDOFF_H
#include "session_manager.h"
#include "native_worker.h"
#include "../overdub/overdub.h"
/* Serialized worker-only, stopped-state handoff. Zero the instance before init;
 * all storage and port functions remain valid for its entire lifetime.
 * No shared task/USB ownership overlay. Native operations use a scoped adapter.
 * enter must close admissions AND join audio, refill and file users, and exclude
 * recorder/card/catalogue changes until leave. enter BUSY/SAFE must leave no
 * reservations or admission changes. leave OK is the completed admission commit;
 * any other leave result must retain closed admissions and ownership. No callback
 * may report failure after admitting another actor. Native lock rules are in
 * backing_native.h; these guarantees require evidence before device binding.
 * All methods return BP_* (not OD_* or boolean results). SAFE means all I/O
 * has joined and no handle ownership is uncertain; assign/save may require
 * rollback. UNCERTAIN forbids rollback, retry and release. Adapters retain
 * unresolved resource identities in context. Unknown results are uncertain.
 * seal exclusively renames and verifies; SAFE means definitely unchanged.
 * Gate/seal contracts are not yet bound to the device. NULL ports cannot enable it.
 * No callback may reenter this state or run asynchronous unjoined work. */
enum {BP_OK=0,BP_BUSY=1,BP_SAFE=2,BP_UNCERTAIN=3};
typedef struct {
    void *context;
    int32_t (*enter)(void *);
    int32_t (*leave)(void *);
    int32_t (*seal)(void *,const uint16_t *,const uint16_t *);
    int32_t (*snapshot)(void *,uint32_t,Pad *);
    int32_t (*insert)(void *,uint32_t,const uint16_t *);
    int32_t (*assign)(void *,uint32_t,const uint16_t *,const Pad *);
    int32_t (*restore)(void *,uint32_t,const Pad *);
    int32_t (*save)(void *);
} BackingPort;
typedef struct {
    SessionManager *manager;BackingPort port;
    uint32_t busy,held,fault,error,last_session,pad;
    Path completed;Pad before,observed;
} BackingHandoff;
int32_t backing_init(BackingHandoff *,SessionManager *,const BackingPort *,uint32_t);
int32_t backing_step(BackingHandoff *);
/* Cold, after both initialization calls, before scheduler start. Validates
 * distinct permanent worker/controller storage and binds the actual step. */
int32_t backing_attach_worker(BackingHandoff *,NativeWorker *);
#endif
