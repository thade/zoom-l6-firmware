#ifndef OD_NATIVE_SCAN_H
#define OD_NATIVE_SCAN_H
#include "playback_session.h"
typedef struct {
    OdSession *session;uint32_t task,queue;
    /* OWN_ACCEPTED / OWN_UNCERTAIN / positively established OWN_NOT_SENT. */
    uint32_t (*send)(uint32_t,const uint32_t *);
    void (*yield)(void);
} NsBinding;
/* Single cold caller after pi_bind, before callbacks/worker traffic. Stable
 * session and port; session scan port must already be ns_scan. */
int32_t ns_bind(const NsBinding *);
/* No-argument AudioSubProcess callback, not a port that accepts incidental r0. */
void ns_callback(void);
/* Session scan port; requires native AudioSubProcess and the session latch. */
int32_t ns_scan(uint32_t parent);
/* Publication interception before both pending/request stores at 0x8003664a. */
void ns_publish(uint32_t,uint32_t,uint32_t,uint32_t);
void ns_publish_entry(void);
/* Uses the stock queue send forwarder; nonzero results mean uncertain delivery. */
uint32_t ns_stock_send(uint32_t,const uint32_t *);
#endif
