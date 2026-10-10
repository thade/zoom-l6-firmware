/* One storage generation and one serialized manager, no queue or wait loop.
 * Outer transition and low-level physical completion bindings remain separate.
 * This must not be enabled on hardware without both of those bindings. */
#include "storage_lease.h"
#include "retention.h"
#ifdef L6_CAPTURE_BOOT_WITNESS
#include "storage_boot.h"
#endif
#include <stddef.h>
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
static StorageLease *owner;
extern uint32_t life_resources_released(const void *);
KEEP const uint32_t storage_lease_layout[]={sizeof(StorageLease),
    offsetof(StorageLease,manager),offsetof(StorageLease,control),offsetof(StorageLease,generation),
    offsetof(StorageLease,may_have_file)};
static uint32_t thread(void){uint32_t v;__asm__ volatile("mrs %0, ipsr":"=r"(v));return !v;}
static uint32_t matches(StorageLease *g){return g && g==LD(&owner);}

KEEP uint32_t storage_lease_bind(StorageLease *g,SessionManager *m) {
    if(!thread() || *(volatile uint32_t*)0x801f9048u || !g || !m || LD(&owner) ||
       g->manager || g->control || g->generation || g->may_have_file ||
       m->state!=M_RESET || m->session==UINT32_MAX || m->descriptor[8]!=m->session+1 ||
       m->zero_index || m->zero_offset || m->count ||
       !manager_storage_disjoint(m,m->descriptor,(uint32_t)g,sizeof(*g)))return 12;
    g->manager=m;ST(&owner,g);return 0;
}
KEEP uint32_t storage_lease_admit(StorageLease *g,uint32_t generation,int32_t mount,int32_t directory) {
#ifdef L6_CAPTURE_BOOT_WITNESS
    if(!storage_boot_ready())return 12;
#endif
    if(!thread() || !matches(g) || !generation || mount!=2 || directory)return 12;
    /* Serialized setup owner, before worker release. Closed is never restored:
     * a concurrent close either wins now or revokes the admitted generation. */
    uint32_t closed=SL_CLOSED;
    if(!__atomic_compare_exchange_n(&g->control,&closed,SL_PIN,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 12;
    g->generation=generation;
    uint32_t pinned=SL_PIN;
    if(!__atomic_compare_exchange_n(&g->control,&pinned,SL_ADMITTED,0,__ATOMIC_RELEASE,__ATOMIC_ACQUIRE)) {
        (void)__atomic_fetch_and(&g->control,~SL_PIN,__ATOMIC_RELEASE);return 16;
    }
    return 0;
}
KEEP uint32_t storage_lease_close(StorageLease *g) {
    if(!thread() || !matches(g))return 12;
    uint32_t c=LD(&g->control);
    for(;;) {
        if((c&3)==SL_RETIRED)return 0;
        uint32_t closing=(c&SL_PIN)|SL_CLOSING;
        if(__atomic_compare_exchange_n(&g->control,&c,closing,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))break;
    }
    manager_cancel(g->manager);return 0;
}
KEEP uint32_t storage_lease_enter(SessionManager *m,uint32_t cleanup) {
    StorageLease *g=LD(&owner);
    if(!thread() || !g || g->manager!=m)return 12;
    uint32_t c=LD(&g->control),s=c&3;
    if(c&SL_PIN)return 11;
    if(s!=SL_ADMITTED && !(cleanup && s==SL_CLOSING))return cleanup?11:12;
    if(!__atomic_compare_exchange_n(&g->control,&c,c|SL_PIN,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
    /* Written under the same pin read by join. RESET is reached only at boot
     * or after the manager's file/hook fence. PREPARE is the first file step. */
    if(m->state==M_RESET)g->may_have_file=0;
    if(m->state==M_PREPARE)g->may_have_file=1;
    if(s==SL_CLOSING) {
        manager_cancel(m);
        /* RESET already has no file or published hooks. Do not create another
         * TMP just to cancel it; join may retire directly at this boundary. */
        if(m->state==M_RESET){storage_lease_leave(m);return 11;}
    }
    return 0;
}
KEEP void storage_lease_leave(SessionManager *m) {
    StorageLease *g=LD(&owner);
    if(g && g->manager==m)(void)__atomic_fetch_and(&g->control,~SL_PIN,__ATOMIC_RELEASE);
}
KEEP uint32_t storage_lease_closing(SessionManager *m) {
    StorageLease *g=LD(&owner);
    return g && g->manager==m && LD(&g->control)==(SL_CLOSING|SL_PIN);
}
KEEP uint32_t storage_lease_join(StorageLease *g) {
    if(!thread() || !matches(g))return 12;
    uint32_t c=LD(&g->control);
    if(c==SL_RETIRED)return 0;
    if(c!=SL_CLOSING)return 11;
    if(!__atomic_compare_exchange_n(&g->control,&c,SL_CLOSING|SL_PIN,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
    SessionManager *m=g->manager;uint32_t zero=0,result=11;
    if(__atomic_compare_exchange_n(&m->busy,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
        /* A fresh or completed RESET is fenced before any clearing/preparation.
         * Its lifecycle storage may still be dirty or partly zeroed; do not
         * inspect it. STOPPED requires positively released lifecycle resources.
         * BLOCKED/unknown handles never authorize an outer storage mutation. */
        if(m->state==M_RESET || ((m->state==M_STOPPED || m->state==M_STORAGE_STOPPED) &&
           (!g->may_have_file || life_resources_released((void*)m->descriptor[4]))))result=0;
        ST(&m->busy,0);
    }
    ST(&g->control,result?SL_CLOSING:SL_RETIRED);return result;
}
