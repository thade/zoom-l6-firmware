#ifndef OD_PUBLICATION_WORKFLOW_H
#define OD_PUBLICATION_WORKFLOW_H
#include "reload_manager.h"
#include "playback_shutdown.h"
#include "../extra_capture/session_manager.h"
/* Integer/pointer-only bridge between the separate soft/hard-float emulator
 * images. Device task scheduling and ordinary recorder/card/USB ingress remain
 * unbound. external_held must attest their continuous exclusion until DONE. */
typedef struct {
    uint32_t (*bind)(SessionManager *,uint32_t);
    uint32_t (*hold)(SessionManager *,uint32_t);
    uint32_t (*release)(SessionManager *,uint32_t);
    int32_t (*publish)(SessionManager *,State *,const Port *,uint32_t);
    int32_t (*external_held)(void);
} PwPort;
typedef struct {
    SessionManager *capture;State *publication;const Port *files;
    OdShutdown *shutdown;RmManager *reload;const PwPort *port;
} PwConfig;
enum {PW_IDLE,PW_HOLD,PW_SHUTDOWN,PW_CHILD,PW_BASELINE,PW_PUBLISH,PW_PLAN,
      PW_START,PW_WAIT,PW_CHILD_END,PW_REOPEN,PW_RELEASE,PW_DONE,PW_FAILED};
typedef struct {
    uint32_t lock,phase,error,child,promotion,session,last_session,publish_result;
    PwConfig config;RmPlan plan;
} PwWorkflow;
/* One permanent binding. Owns shutdown finish and capture release exclusively.
 * Caller must initialize RmManager with pw_reload_port before calling init. */
extern const RmPort pw_reload_port;
int32_t pw_init(PwWorkflow *,const PwConfig *);
int32_t pw_start(PwWorkflow *);
int32_t pw_step(PwWorkflow *);
int32_t pw_fenced(void);
/* Main must defer ordinary controls/mode setup until the entire handoff ends. */
int32_t pw_main_ready(void);
#endif
