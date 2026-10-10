/* Observation only. Original calls run once, with their original arguments.
 * No allocation, task, file request, retry, reset or ownership permission.
 * Each fixed slot has one stable Thread-mode TCB writer. Queries use epochs;
 * an epoch is never held odd across a native call that can block or schedule.
 * Token return -> give entry is a HELD-BODY LOWER BOUND, not the exact instant
 * of acquisition/release. Native take/give elapsed includes scheduling. */
#include <stdint.h>
#define W(a) (*(volatile uint32_t *)(a))
#define B(a) (*(volatile uint8_t *)(a))
#define LOAD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define STORE(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define TICKS W(0x801f9050u)
#define TASKS 8u
#define LOCKS 4u
enum { WAIT=1, HELD=2, GIVING=4 };
typedef struct {
    _Atomic uint32_t operation,handle,bytes,entry_tick,job,calls,errors,last_result;
    _Atomic uint32_t last_ticks,max_ticks,peak_job,peak_operation,peak_handle,peak_bytes;
    _Atomic uint32_t peak_state,peak_tick,nested_calls;
} File;
typedef struct {
    _Atomic uint32_t object,flags,phase_tick,held_job,held_operation,held_amount;
    _Atomic uint32_t held_identity,held_state,calls,errors,last_wait,max_wait;
    _Atomic uint32_t peak_wait_job,peak_wait_amount,peak_wait_identity;
    _Atomic uint32_t releases,release_errors,last_held,max_held,peak_held_job;
    _Atomic uint32_t peak_held_amount,peak_held_identity,peak_held_state;
    _Atomic uint32_t last_give_ticks,max_give_ticks;
} Lock;
typedef struct { uint32_t owner,epoch; File file; Lock lock[LOCKS]; } Task;
typedef struct {
    uint32_t claim_misses,slots_full,context_skips,ambiguous_tokens;
    uint32_t nested_takes,unpaired_gives;
} Meta;
typedef struct { Meta meta; Task task[TASKS]; } State;
_Static_assert(sizeof(File)==68 && sizeof(Lock)==100 && sizeof(Task)==476,
               "fixed observation wire layout");
__attribute__((section(".probe_state"),aligned(32),used)) State service_stats={0};
__attribute__((used)) const uint32_t service_layout[]={sizeof(State),sizeof(Task),
    sizeof(File)/4,sizeof(Lock)/4,TASKS,LOCKS};
extern uint32_t timing_read(uint32_t,void *,uint32_t,uint32_t *);
extern uint32_t timing_write(uint32_t,const void *,uint32_t,uint32_t *);
extern uint32_t service_take_original(uint32_t);
extern uint32_t service_give_original(uint32_t);
extern uint32_t health_query(const uint8_t *);
static void count(uint32_t *p){__atomic_fetch_add(p,1,__ATOMIC_RELAXED);}
static Task *task(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(ipsr || W(0x801f9048u)!=1 || !W(0x808e291cu)) {
        count(&service_stats.meta.context_skips);return 0;
    }
    uint32_t owner=W(0x808e291cu);
    for(uint32_t i=0;i<TASKS;i++)if(LOAD(&service_stats.task[i].owner)==owner)
        return &service_stats.task[i];
    for(uint32_t i=0;i<TASKS;i++)if(!LOAD(&service_stats.task[i].owner)) {
        uint32_t zero=0;
        if(__atomic_compare_exchange_n(&service_stats.task[i].owner,&zero,owner,1,
                                      __ATOMIC_ACQ_REL,__ATOMIC_RELAXED))
            return &service_stats.task[i];
        count(&service_stats.meta.claim_misses);return 0;
    }
    count(&service_stats.meta.slots_full);return 0;
}
/* One task owns each slot, IRQ writers are excluded, and updates finish before
 * any native call. Task deletion/TCB reuse is outside this bounded trial. */
static void begin(Task *s){__atomic_fetch_add(&s->epoch,1,__ATOMIC_ACQ_REL);}
static void end(Task *s){STORE(&s->epoch,LOAD(&s->epoch)+1);}
static uint32_t state(void){return B(0x80578ebcu)|((uint32_t)B(0x801f8c50u)<<8);}
static int classify(uint32_t object) {
    if(!object)return -1;
    const uint32_t addresses[]={0x801f8da4u,0x801f8da8u,0x801f5fc0u,0x801f5fdcu};
    int found=-1;
    for(uint32_t i=0;i<LOCKS;i++)if(W(addresses[i])==object) {
        if(found>=0){count(&service_stats.meta.ambiguous_tokens);return -1;}
        found=(int)i;
    }
    return found;
}
static uint32_t file(uint32_t op,uint32_t h,void *b,uint32_t n,uint32_t *a) {
    Task *s=task();uint32_t started=0,observed=0;
    if(s) {
        begin(s);File *f=&s->file;
        if(f->operation)f->nested_calls++;
        else {
            observed=1;started=TICKS;f->operation=op;f->handle=h;f->bytes=n;
            f->entry_tick=started;f->job=++f->calls;
        }
        end(s);
    }
    uint32_t result=op==1?timing_read(h,b,n,a):timing_write(h,b,n,a);
    if(observed) {
        uint32_t elapsed=TICKS-started;begin(s);File *f=&s->file;
        f->last_result=result;f->last_ticks=elapsed;if(result)f->errors++;
        if(elapsed>f->max_ticks) {
            f->max_ticks=elapsed;f->peak_job=f->job;f->peak_operation=op;
            f->peak_handle=h;f->peak_bytes=n;f->peak_state=state();f->peak_tick=TICKS;
        }
        f->operation=0;end(s);
    }
    return result;
}
uint32_t service_read(uint32_t h,void *b,uint32_t n,uint32_t *a){return file(1,h,b,n,a);}
uint32_t service_write(uint32_t h,const void *b,uint32_t n,uint32_t *a){return file(2,h,(void*)b,n,a);}
uint32_t service_take(uint32_t object) {
    int index=classify(object);Task *s=index<0?0:task();Lock *l=0;
    uint32_t started=0;
    if(s) {
        begin(s);l=&s->lock[index];
        if(l->flags){count(&service_stats.meta.nested_takes);l=0;}
        else {
            l->object=object;l->flags=WAIT;l->phase_tick=started=TICKS;
            l->held_operation=s->file.operation;
            l->held_job=s->file.operation?s->file.job:0;
            l->held_amount=s->file.operation?s->file.bytes:0;
            l->held_identity=s->file.operation?s->file.handle:0;
            l->held_state=state();l->calls++;
        }
        end(s);
    }
    uint32_t result=service_take_original(object);
    if(l) {
        uint32_t now=TICKS,elapsed=now-started;begin(s);
        l->last_wait=elapsed;
        if(elapsed>l->max_wait){l->max_wait=elapsed;l->peak_wait_job=l->held_job;
            l->peak_wait_amount=l->held_amount;l->peak_wait_identity=l->held_identity;}
        l->flags=result?0:HELD;l->phase_tick=now;if(result)l->errors++;
        end(s);
    }
    return result;
}
uint32_t service_give(uint32_t object) {
    /* Match retained opaque identity, even if card teardown changed its slot. */
    Task *s=0;Lock *l=0;uint32_t owner=W(0x808e291cu),ipsr;
    __asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(!ipsr && owner && W(0x801f9048u)==1) {
        for(uint32_t i=0;i<TASKS;i++)if(LOAD(&service_stats.task[i].owner)==owner)
            s=&service_stats.task[i];
        if(s)for(uint32_t i=0;i<LOCKS;i++)
            if(s->lock[i].object==object && s->lock[i].flags==HELD)l=&s->lock[i];
    }
    uint32_t started=TICKS;
    if(l) {
        begin(s);uint32_t held=started-l->phase_tick;l->last_held=held;l->releases++;
        if(held>l->max_held){l->max_held=held;l->peak_held_job=l->held_job;
            l->peak_held_amount=l->held_amount;l->peak_held_identity=l->held_identity;
            l->peak_held_state=l->held_state;}
        l->flags=HELD|GIVING;end(s);
    } else if(classify(object)>=0)count(&service_stats.meta.unpaired_gives);
    uint32_t result=service_give_original(object);
    if(l) {
        uint32_t elapsed=TICKS-started;begin(s);l->last_give_ticks=elapsed;
        if(elapsed>l->max_give_ticks)l->max_give_ticks=elapsed;
        if(result)l->release_errors++;
        /* A failed give is retained as unresolved observation, never cleared. */
        l->flags=result?HELD:0;end(s);
    }
    return result;
}
static void encode(uint8_t *out,uint32_t v){for(uint32_t i=0;i<5;i++){out[i]=v&127;v>>=7;}}
uint32_t service_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x77 || p[5]<1 || p[5]>41 || p[6]>127 || p[7]!=0xf7 ||
       B(0x80629b60u)!=2)return health_query(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    uint8_t reply[160]={0xf0,0x52,0,0,0x76,p[5],p[6]};uint32_t count=0;
    if(p[5]==1) {
        uint32_t fixed[]={1,TASKS,LOCKS};
        for(uint32_t i=0;i<3;i++)encode(reply+7+5*count++,fixed[i]);
        for(uint32_t i=0;i<5;i++)encode(reply+7+5*count++,W(0x801f901cu+4*i));
        const uint32_t *m=(const uint32_t*)&service_stats.meta;
        for(uint32_t i=0;i<sizeof(Meta)/4;i++)encode(reply+7+5*count++,LOAD(m+i));
    } else {
        uint32_t index=p[5]<10?p[5]-2:(p[5]-10)/LOCKS;
        Task *s=&service_stats.task[index];
        encode(reply+7+5*count++,LOAD(&s->owner));
        encode(reply+7+5*count++,LOAD(&s->epoch));
        const uint32_t *data;uint32_t words;
        if(p[5]<10){data=(const uint32_t*)&s->file;words=sizeof(File)/4;}
        else {data=(const uint32_t*)&s->lock[(p[5]-10)%LOCKS];words=sizeof(Lock)/4;}
        for(uint32_t i=0;i<words;i++)encode(reply+7+5*count++,LOAD(data+i));
        encode(reply+7+5*count++,LOAD(&s->epoch));
    }
    encode(reply+7+5*count++,TICKS);uint32_t length=8+5*count;reply[length-1]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,length,2);return 1;
}
