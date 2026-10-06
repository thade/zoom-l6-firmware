/* Offline-only candidate addresses. This is not a device RAM allocation or
 * storage admission provider. Normal builds do not contain this fixture. */
#include "../../src/capture/native_worker.h"
#define KEEP __attribute__((used,retain))
#define W(a) (*(volatile uint32_t *)(a))
/* One cold runtime: 0 unseen, 1 observed success, 2 observed failure, 3 tried.
 * The scatter fixture zeros this with all permanent globals before hook entry. */
KEEP uint32_t startup_status;
#define MANAGER ((SessionManager*)0x80961d80u)
#define WORKER ((NativeWorker*)0x80962620u)
_Static_assert(sizeof(SessionManager)==2208,"candidate manager arena changed");
_Static_assert(sizeof(NativeWorker)==64,"candidate worker arena changed");

KEEP void startup_observe(uint32_t unused,uint32_t first_result) {
    (void)unused;
    if(!startup_status)startup_status=first_result?2:1;
}
KEEP void startup_register(uint32_t unused,uint32_t selected) {
    (void)unused;(void)selected;
    if(startup_status!=1)return;
    startup_status=3; /* No implicit retry, including optional failure. */
    typedef void (*Zero)(uint32_t,void*,uint32_t);
    Zero zero=(Zero)0x800794a9u;
    zero(0,MANAGER,sizeof(*MANAGER));zero(0,WORKER,sizeof(*WORKER));
    /* These input arrays are copied into manager/worker by registration. They
     * need no permanent descriptor/config arenas. Slots are not touched here. */
    const uint32_t d[]={0x809600e0u,0x809607a0u,0x809607c0u,0x809608c0u,
        0x80960900u,0x80960d40u,0x809626c0u,4096,1,W(0x801f8f38u)};
    const WorkerConfig config={4096,1,4,1,25}; /* Unmeasured experiment budgets. */
    WORKER->last_status=native_worker_register(WORKER,MANAGER,d,&config,0,1);
    /* Success leaves W_WAITING. No release, file work or pad mutation. */
}
