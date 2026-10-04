#ifndef L6_SESSION_MANAGER_H
#define L6_SESSION_MANAGER_H
#include <stdint.h>
enum {M_LIVE=1,M_FINISH,M_FENCE,M_RESET,M_PREPARE,M_STAGE,M_ACTIVATE,
      M_ABORT_STAGE,M_STOPPED,M_BLOCKED,M_ABORT_UNPUBLISHED};
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
uint32_t manager_visit_results(SessionManager *,ManagerVisitor,void *);
/* Optional permanent publication owner. Once bound, the completed-take RESET
 * boundary waits for its release before clearing arenas or arming the next take.
 * Tokens are permanent owner addresses. Cancellation never overrides a hold. */
uint32_t manager_bind_publication(SessionManager *,uint32_t token);
uint32_t manager_hold_publication(SessionManager *,uint32_t token);
uint32_t manager_release_publication(SessionManager *,uint32_t token);
uint32_t manager_visit_held_results(SessionManager *,uint32_t token,ManagerVisitor,void *);
#endif
