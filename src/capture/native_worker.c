/* Experimental v1.10 task adapter. No installed startup hook or device address.
 * Timed polling deliberately avoids introducing audio/ISR wakeup operations. */
#include "native_worker.h"
#include "../overdub/overdub.h"
#include <stddef.h>
#include "retention.h"
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define W(a) (*(volatile uint32_t *)(a))
typedef int32_t (*Create)(void (*)(void*),const char*,uint32_t,void*,uint32_t,uint32_t*);
#define CREATE ((Create)0x80076c61u)
#define DELAY ((void (*)(uint32_t))0x80074159u)
#define CURRENT ((uint32_t (*)(void))0x800770e9u)
KEEP const uint32_t native_worker_layout[]={sizeof(NativeWorker),offsetof(NativeWorker,task),
 offsetof(NativeWorker,state),offsetof(NativeWorker,last_status),offsetof(NativeWorker,last_steps)};
static uint32_t irq(void) {uint32_t v;__asm__ volatile("mrs %0, ipsr":"=r"(v));return v;}
extern void bridge_hook(uint32_t,uint32_t);
extern uint32_t bridge_audio_boot_ready(void);
KEEP uint32_t native_worker_bind_audio(NativeWorker *w,const WorkerAudio *p) {
    if(!w || !p || irq() || W(0x801f9048u) || LD(&w->state)!=W_WAITING ||
       w->audio_arm || w->audio_ready || !p->prepare || !p->arm || !p->ready ||
       !p->control || !p->audio_task || ((uintptr_t)p->control&3u))return 12;
    uint32_t a=(uint32_t)p->control,n=sizeof(*p->control),b=(uint32_t)w;
    if(!manager_storage_disjoint(w->manager,w->manager->descriptor,a,n) ||
       ((uint64_t)a<(uint64_t)b+sizeof(*w) && (uint64_t)b<(uint64_t)a+n))return 12;
    uint32_t (*arm)(void)=p->arm,(*ready)(void)=p->ready;
    if(p->prepare(p->control,p->audio_task,bridge_hook,bridge_audio_boot_ready)) {
        w->last_status=13;ST(&w->state,W_FAILED);return 13;
    }
    w->audio_arm=arm;w->audio_ready=ready;return 0;
}
static int config_ok(const WorkerConfig *c) {
    /* 0x400 is the smallest stack used by the stock file workers examined.
     * It is a floor for experiments, not a proof that it fits this call chain. */
    return c->stack_words>=0x400 && c->stack_words<=0xffff && c->priority<32 &&
           c->steps_per_pass>=1 && c->steps_per_pass<=16 && c->poll_ticks>=1 &&
           c->idle_ticks>=c->poll_ticks && c->idle_ticks<=1000;
}
KEEP uint32_t native_worker_register(NativeWorker *w,SessionManager *m,const uint32_t *d,
                                     const WorkerConfig *config,uint32_t pad,uint32_t serial) {
    if(!w || ((uintptr_t)w&3u) || !m || !d || !config || irq() || W(0x801f9048u) ||
       !W(0x801f8f38u) || d[9]!=W(0x801f8f38u) || !config_ok(config) ||
       !manager_storage_disjoint(m,d,(uint32_t)w,sizeof(*w)))return 12;
    const uint8_t *raw=(const uint8_t*)w;
    for(uint32_t i=0;i<sizeof(*w);i++)if(raw[i])return 12;
    WorkerConfig saved=*config;
    uint32_t result=manager_boot(m,d,pad,serial);if(result)return result;
    w->manager=m;w->config=saved;w->state=W_REGISTERING;
    int32_t created=CREATE(native_worker_entry,"L6Overdub",saved.stack_words,w,saved.priority,&w->task);
    if(created!=1 || !w->task){w->last_status=13;ST(&w->state,W_FAILED);return 13;}
    ST(&w->state,W_WAITING);return 0;
}
KEEP uint32_t native_worker_release(NativeWorker *w) {
    if(!w || irq() || !W(0x801f9048u) || !W(0x80446da4u) ||
       CURRENT()!=W(0x80446da4u))return 12;
    if(LD(&w->state)!=W_WAITING && LD(&w->state)!=W_AUDIO_WAIT)return 12;
    if(w->audio_arm) {
        if(w->audio_arm())return 12;
        uint32_t waiting=W_WAITING;
        (void)__atomic_compare_exchange_n(&w->state,&waiting,W_AUDIO_WAIT,0,
                                         __ATOMIC_RELEASE,__ATOMIC_RELAXED);
        uint32_t s=w->audio_ready();
        if(s) {
            if(s!=OC_BUSY){ST(&w->state,W_FAILED);return 12;}
            return 11;
        }
    }
    uint32_t waiting=w->audio_arm?W_AUDIO_WAIT:W_WAITING;
    return __atomic_compare_exchange_n(&w->state,&waiting,W_READY,0,
                                      __ATOMIC_RELEASE,__ATOMIC_RELAXED)?0:waiting==W_READY?0:12;
}
KEEP uint32_t native_worker_poll(NativeWorker *w) {
    if(!w || irq() || !W(0x801f9048u) || CURRENT()!=w->task)return 12;
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&w->busy,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
    w->last_steps=0;
    if(LD(&w->state)==W_AUDIO_WAIT) {
        uint32_t ready=w->audio_ready();
        if(ready) {
            if(ready!=OC_BUSY)ST(&w->state,W_FAILED);
            ST(&w->busy,0);return ready==OC_BUSY?11:12;
        }
        uint32_t waiting=W_AUDIO_WAIT;
        (void)__atomic_compare_exchange_n(&w->state,&waiting,W_READY,0,
                                         __ATOMIC_RELEASE,__ATOMIC_RELAXED);
    }
    if(LD(&w->state)!=W_READY){ST(&w->busy,0);return 12;}
    uint32_t status=w->manager->error;
    if(w->manager->state!=M_STOPPED && w->manager->state!=M_BLOCKED
#ifdef L6_CAPTURE_STORAGE_LEASE
       && w->manager->state!=M_STORAGE_STOPPED
#endif
      ) {
        do {
            SessionManager *m=w->manager;
            if(w->handoff && m->state==M_RESET && m->count &&
               m->results[(m->head+3)&3].session==m->session &&
               m->publication_session!=m->session && !m->zero_index && !m->zero_offset) {
                int32_t h=w->handoff(w->handoff_context);w->handoff_status=(uint32_t)h;
                if(h==OD_BUSY){status=11;break;}
                if(h==OD_FAULT || m->publication_hold){ST(&w->state,W_FAILED);status=13;break;}
                /* Safely failed handoff released the boundary. Capture can
                 * continue; its error remains available in handoff_status. */
            }
            status=manager_step(w->manager);w->last_steps++;
        } while(status==10 && w->last_steps<w->config.steps_per_pass);
    }
    w->last_status=status;ST(&w->busy,0);return status;
}
KEEP __attribute__((noreturn)) void native_worker_entry(void *arg) {
    NativeWorker *w=arg;
    for(;;) {
#ifdef L6_CAPTURE_BOOT_PROBE
        extern uint32_t boot_probe_polls;
        __atomic_fetch_add(&boot_probe_polls,1,__ATOMIC_RELAXED);
#endif
        (void)native_worker_poll(w);
        uint32_t ticks=w->config.poll_ticks;
        if(LD(&w->state)!=W_READY || w->manager->state==M_STOPPED || w->manager->state==M_BLOCKED
#ifdef L6_CAPTURE_STORAGE_LEASE
           || w->manager->state==M_STORAGE_STOPPED
#endif
          )
            ticks=w->config.idle_ticks;
        /* Always block, even after exhausting a MORE-work batch. No spin loop
         * while waiting for audio, queue acknowledgement or publication. */
        DELAY(ticks);
    }
}
