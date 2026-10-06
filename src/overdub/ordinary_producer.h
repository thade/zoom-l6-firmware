#ifndef OD_ORDINARY_PRODUCER_H
#define OD_ORDINARY_PRODUCER_H
#include "read_worker.h"
typedef struct {
    RlCoordinator *coordinator;
    uint32_t ids[OI_SLOTS],id_words[OI_SLOTS];
    uint32_t queue,semaphores[2];
    int32_t (*send)(uint32_t,const uint32_t *);
    int32_t (*wait)(uint32_t,uint32_t);
    void (*yield)(void); /* Must give the file worker an opportunity to run. */
    /* Required explicit attribution: zero parent admits an ordinary root.
     * Nonzero is a live session/refill owner. BUSY retries before reservation.
     * Must run synchronously for the current task, without changing ownership
     * before the callback returns. Selecting pi_parent enables the explicit
     * playback_io Main-start/claimed-refill provider and shared preflight. */
    int32_t (*parent)(uint32_t,uint32_t *);
    int32_t (*seek)(uint32_t,uint32_t,uint32_t);
} OpBinding;
/* Cold, copied binding after rp/rw/pf bind, before traffic/hooks. Nonzero IDs
 * have distinct aligned permanent RAM identity words; unused pairs are zero.
 * All ordinary callback callers must be listed. No live cutover/task reuse. */
int32_t op_bind(const OpBinding *);
uint32_t op_enabled(void);
int32_t op_read(uint32_t,uint32_t,uint32_t);
int32_t op_seek(uint32_t,uint32_t,uint32_t);
#endif
