/* Separate offline executor test seam, not a replacement for these native
 * callees. storage_main.c instead retains the complete original Main request. */
#include "storage_transition.h"
#include "retention.h"
#define W(a) (*(volatile uint32_t *)(a))
#define CURRENT ((uint32_t (*)(void))0x800770e9u)
typedef int32_t (*Native)(uint32_t,uint32_t);
KEEP StorageTransitionResult storage_transition_try(StorageLease *g,uint32_t op,
                                                    uint32_t argument,uint32_t profile) {
    StorageTransitionResult reply={12,0};
    uint32_t irq;__asm__ volatile("mrs %0, ipsr":"=r"(irq));
    /* Validate before revocation; an invalid optional request must not disable
     * recording. Restrict the executor to the native Main task and known bodies. */
    if(irq || !W(0x801f9048u) || !W(0x80446da4u) ||
       CURRENT()!=W(0x80446da4u) || op>ST_CARD_SETUP ||
       (op==ST_USB_START ? argument>1 || profile>2 :
        profile || (op==ST_CARD_RELEASE ? argument!=0 :
                    argument>(op==ST_CARD_SETUP?2u:1u))))return reply;
    reply.status=storage_lease_close(g);
    if(reply.status)return reply;
    reply.status=storage_lease_join(g);
    if(reply.status)return reply;
    /* The admitted generation is now permanently retired. No optional manager
     * operation can race this body, including automatic next-TMP preparation.
     * Nested mount/release calls stay stock; only this outer request is gated. */
    static const uint32_t entries[]={0x8000c221u,0x8000c289u,0x8000c2d9u,
                                     0x80009b19u,0x80009a41u};
    reply.native_result=((Native)entries[op])(argument,profile);
    return reply;
}
