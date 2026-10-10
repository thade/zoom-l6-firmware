#ifndef L6_SESSION_MANAGER_H
#define L6_SESSION_MANAGER_H
#include <stdint.h>
enum {M_LIVE=1,M_FINISH,M_FENCE,M_RESET,M_PREPARE,M_STAGE,M_ACTIVATE,
      M_ABORT_STAGE,M_STOPPED,M_BLOCKED,M_ABORT_UNPUBLISHED,M_STORAGE_STOPPED};
typedef struct {uint32_t session;uint16_t path[261];uint16_t reserved;} ManagerResult;
typedef struct {
    uint32_t state,error,cancel,busy,session,serial,pad,head,count;
    uint32_t zero_index,zero_offset;
    uint32_t descriptor[10];
    ManagerResult results[4];
    uint32_t publication_owner,publication_hold,publication_session;
} SessionManager;
/* Synchronous worker callback, under the manager latch, at the completed take
 * boundary before arena reset. Return 11 for busy, 12 for an invalid caller. */
typedef void (*ManagerVisitor)(const ManagerResult *,uint32_t,uint32_t,void *);
/* Once per cold runtime, before hooks/callers can enter. Manager must be zeroed;
 * descriptor names valid, exclusively owned storage (not necessarily zeroed).
 * Queue must already exist. No allocation, task creation or file IO here.
 * Subsequent worker steps clear/prepare, then wait for audio-boundary adoption. */
uint32_t manager_boot(SessionManager *,const uint32_t descriptor[10],uint32_t pad,uint32_t serial);
uint32_t manager_step(SessionManager *);
void manager_cancel(SessionManager *);
uint32_t manager_resume(SessionManager *);
/* Check permanent worker/context storage against the manager, resettable
 * objects, history metadata and every full history region. This does not
 * validate physical RAM; external descriptors must be readable and stable. */
uint32_t manager_storage_disjoint(SessionManager *,const uint32_t *,uint32_t address,uint32_t bytes);
uint32_t manager_visit_results(SessionManager *,ManagerVisitor,void *);
/* Optional permanent publication owner. Once bound, the completed-take RESET
 * boundary waits for its release before clearing arenas or arming the next take.
 * Tokens are permanent owner addresses. Cancellation never overrides a hold. */
uint32_t manager_bind_publication(SessionManager *,uint32_t token);
uint32_t manager_hold_publication(SessionManager *,uint32_t token);
uint32_t manager_release_publication(SessionManager *,uint32_t token);
/* Decline a completed boundary without acquiring a hold (e.g. cancellation).
 * Only its bound owner may do this; a held transaction must release normally. */
uint32_t manager_skip_publication(SessionManager *,uint32_t token);
uint32_t manager_visit_held_results(SessionManager *,uint32_t token,ManagerVisitor,void *);
#endif
