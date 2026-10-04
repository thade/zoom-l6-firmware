#ifndef OD_USB_OWNERSHIP_H
#define OD_USB_OWNERSHIP_H
#include "reload_manager.h"
/* Zero controller/task storage once before init; never reset live ownership.
 * Proposed tagged worker transport, NOT the native two-word USB mailbox. Both
 * endpoints must be replaced together after draining the old transport. */
typedef struct {uint32_t owner,child,operation,selector,parameter;} UsRequest;
enum {US_START=1,US_STOP=2};
typedef struct {
    /* Continuous caller-owned pad/control/ordinary-recorder exclusion. Native
     * ingress coverage remains incomplete; this must not use idle flags. */
    int32_t (*quiescent)(void);
    void (*enter)(uint32_t profile); /* stock c220(1,profile), redirected request */
    int32_t (*send)(const UsRequest *); /* Copy before return: ACCEPTED/NOT_SENT/UNCERTAIN. */
    /* Checked start/stop implementation; zero means positive completion. Stop
     * must close host/driver ingress and join in-flight work or attach children
     * before returning. Native driver proof is still an unbound port. */
    int32_t (*worker)(const UsRequest *);
    void (*remount)(void); /* c288 suffix after stop; defer stock reload */
    int32_t (*local_ready)(void); /* OWN_OK/BUSY/FAULT; checked mount evidence */
} UsPort;
enum {US_IDLE,US_ADMIT,US_ENTER,US_ENTER_WAIT,US_HOST,US_STOP_SEND,US_STOP_WAIT,
      US_MOUNT,US_READY,US_RELOAD_START,US_RELOAD_WAIT,US_RELEASE,US_DONE,US_FAILED};
typedef struct {
    uint32_t lock,phase,error,owner,profile,command,reload_intent;
    OwnLedger *ledger;RmManager *reload;const UsPort *port;RmPlan plan;
} UsOwner;
typedef struct {uint32_t lock,phase,error;UsRequest request;} UsTask;
extern const RmPort us_reload_port;
int32_t us_init(UsOwner *,OwnLedger *,RmManager *,const UsPort *);
int32_t us_begin(UsOwner *,uint32_t profile);
/* Trusted intended plan supplied after host use, not inferred from reload output. */
int32_t us_exit(UsOwner *,uint32_t owner,const RmPlan *);
int32_t us_step(UsOwner *);
int32_t us_queue(UsOwner *,uint32_t selector,uint32_t parameter);
int32_t us_defer_reload(UsOwner *);
int32_t us_receive(UsTask *,const UsRequest *);
int32_t us_run(UsOwner *,UsTask *);
/* Attribution captured by native boundary wrappers, never by the stock mode
 * bit. Stale tokens cannot poison a newer session. First error wins. */
int32_t us_error(UsOwner *,uint32_t owner,uint32_t error);
int32_t us_fenced(void);
void us_stock_enter(uint32_t);
void us_stock_remount(void);
#endif
