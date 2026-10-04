#include "control_coordinator.h"
#include <stddef.h>
#define KEEP __attribute__((used,retain))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
KEEP const uint32_t oc_audio_layout[]={offsetof(OcCoordinator,audio_request),
    offsetof(OcCoordinator,audio_sequence),sizeof(OcCoordinator)};
static uint32_t fault(OcCoordinator *c){ST(&c->audio_fault,1);return 0;}
static int known(uint32_t primary,uint32_t secondary) {
    return secondary==0x2022a789 &&
        (primary==0x2022a791 || primary==0x80010961 ||
         primary==0x800124d9 || primary==0x800133e9);
}
/* Audio owns all non-atomic audio fields. Control touches only request/ack/fault
 * atomically. Entry returns a unique token or zero on a latched fault. A null
 * dispatch is skipped by the proposed adapter, not treated as a callback. */
KEEP uint32_t oc_audio_begin(OcCoordinator *c,uint32_t primary,uint32_t secondary) {
    if(!c)return 0;
    if(LD(&c->audio_fault))return 0;
    if(c->audio_active || c->audio_sequence==UINT32_MAX || !known(primary,secondary))return fault(c);
    c->audio_primary=primary;c->audio_secondary=secondary;
    c->audio_epoch=LD(&c->audio_request);
    c->audio_active=++c->audio_sequence;
    return c->audio_active;
}
KEEP uint32_t oc_audio_end(OcCoordinator *c,uint32_t token,uint32_t primary,uint32_t secondary) {
    if(!c)return OC_INVALID;
    if(LD(&c->audio_fault))return OC_FAULT;
    if(!token || token!=c->audio_active || primary!=c->audio_primary || secondary!=c->audio_secondary) {
        fault(c);return OC_FAULT;
    }
    uint32_t epoch=c->audio_epoch;
    c->audio_active=0;
    /* A request arriving mid-block cannot be acknowledged by that block. */
    if(epoch && LD(&c->audio_request)==epoch)ST(&c->audio_ack,epoch);
    return OC_OK;
}
