#ifndef OD_PLAYBACK_SHUTDOWN_H
#define OD_PLAYBACK_SHUTDOWN_H
#include "playback_session.h"
#include "control_coordinator.h"
enum {SD_IDLE,SD_HOLD,SD_DRAIN,SD_STOP,SD_FENCE,SD_PROMOTE,SD_HELD,
      SD_REOPEN,SD_UNHOLD,SD_FAILED};
typedef struct {
    int32_t (*disable_streams)(void);
    uint32_t (*quiet)(void);
} OdShutdownPort;
typedef struct {
    OdSession *session;
    OcCoordinator *control;
    const OdShutdownPort *port;
    uint32_t lock,phase,epoch,owner,requested,promotion,last_fenced;
} OdShutdown;
/* Zero once, set permanent pointers before enabling participants. Sole owner
 * of session hold/unhold/quiesce and control close/request/reopen during a cycle.
 * All starts/scans must use this session; all mode changes must use control.
 * Poll returns OK only with exclusive ledger ownership retained in promotion.
 * It may perform progress then return BUSY. Audio and workers keep running.
 * Bind session fence/rearm to adapters for THIS instance. No installed hooks. */
int32_t od_shutdown_poll(OdShutdown *);
int32_t od_shutdown_finish(OdShutdown *,uint32_t promotion,uint32_t failed);
/* Fence runs only from session quiesce while its operation latch is held. */
int32_t od_shutdown_fence(OdShutdown *,uint32_t owner,uint32_t *ack);
int32_t od_shutdown_rearm(OdShutdown *,uint32_t old,uint32_t next);
/* Trusted publisher owns the returned child until release. Parent finish must
 * wait for it. These APIs do not provide missing card/recorder ingress coverage. */
int32_t od_shutdown_publish_begin(OdShutdown *,uint32_t *child);
int32_t od_shutdown_publish_end(OdShutdown *,uint32_t child,uint32_t failed);
#endif
