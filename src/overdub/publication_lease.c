#include "playback_shutdown.h"
#include "overdub.h"
#define KEEP __attribute__((used,retain))
/* Emulator-only permanent port context. The ordinary publisher's State.busy
 * serializes its sole worker. No other caller may own or release this child. */
typedef struct {OdShutdown *shutdown;State *state;uint32_t child;} PublicationLease;
#define LEASE ((PublicationLease *)0x21003e00)
KEEP int32_t od_emulator_publication_enter(void) {
    PublicationLease *p=LEASE;
    if(p->child)return 1;
    int32_t r=od_shutdown_publish_begin(p->shutdown,&p->child);
    if(r && r!=OWN_BUSY)p->state->fault=1;
    return r?1:0;
}
KEEP void od_emulator_publication_leave(void) {
    PublicationLease *p=LEASE;
    if(od_shutdown_publish_end(p->shutdown,p->child,p->state->fault)) {
        p->state->fault=1;
        od_gate_fail(&p->shutdown->session->ledger->gate);
    } else p->child=0;
}
