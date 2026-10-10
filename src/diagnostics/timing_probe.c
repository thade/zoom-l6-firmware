/* Observation only. No allocation, task, file/SD request, retry or recovery.
 * Each admitted observer calls its original routine exactly once. Busy/missed
 * claims proceed unobserved. Public-file timing includes native lock waits.
 * Tick measurements and software returns never authorize buffer reuse. */
#include <stdint.h>
#define W(a) (*(volatile uint32_t *)(a))
#define B(a) (*(volatile uint8_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define OBS(p) __atomic_load_n((p),__ATOMIC_RELAXED)
#define SET(p,v) __atomic_store_n((p),(v),__ATOMIC_RELAXED)
#define TICKS W(0x801f9050u)
typedef struct {
    uint32_t calls,errors,first_error,last_result,last_ticks,max_ticks;
    uint32_t peak_amount,peak_id,largest_amount,bins[8];
} Operation;
typedef struct {uint32_t epoch,busy_skips,claim_skips;Operation op[2];} Scope;
_Static_assert(sizeof(Operation)==68 && sizeof(Scope)==148,"wire layout");
/* Two SD packet units and one scope for the public file read/write entries. */
__attribute__((section(".probe_state"),aligned(32),used))
Scope timing_stats[3]={0};
extern uint32_t health_sd_original(const uint8_t *);
extern uint32_t timing_read_original(uint32_t,void *,uint32_t,uint32_t *);
extern uint32_t timing_write_original(uint32_t,const void *,uint32_t,uint32_t *);
static void inc(uint32_t *p){__atomic_fetch_add(p,1,__ATOMIC_RELAXED);}
static int begin(Scope *s,uint32_t *epoch) {
    *epoch=LD(&s->epoch);
    if(*epoch&1){inc(&s->busy_skips);return 0;}
    if(!__atomic_compare_exchange_n(&s->epoch,epoch,*epoch+1,1,
                                   __ATOMIC_ACQ_REL,__ATOMIC_RELAXED)) {
        inc(&s->claim_skips);return 0;
    }
    return 1;
}
static void finish(Scope *s,uint32_t op,uint32_t epoch,uint32_t result,
                   uint32_t elapsed,uint32_t amount,uint32_t id) {
    Operation *o=&s->op[op];
    /* The epoch serializes writers; atomic fields also make concurrent query
     * loads well-defined. Final release publishes the completed observation. */
    if(result){SET(&o->errors,OBS(&o->errors)+1);if(!OBS(&o->first_error))SET(&o->first_error,result);}
    SET(&o->last_result,result);SET(&o->last_ticks,elapsed);
    if(elapsed>OBS(&o->max_ticks)){SET(&o->max_ticks,elapsed);SET(&o->peak_amount,amount);SET(&o->peak_id,id);}
    if(amount>OBS(&o->largest_amount))SET(&o->largest_amount,amount);
    uint32_t bin=elapsed==0?0:elapsed<=4?1:elapsed<=16?2:elapsed<=64?3:
                 elapsed<=128?4:elapsed<=256?5:elapsed<=512?6:7;
    SET(&o->bins[bin],OBS(&o->bins[bin])+1);ST(&s->epoch,epoch+2);
}
uint32_t health_sd(const uint8_t *p) {
    uint32_t unit=p[1],op=p[0];
    if((unit!=1 && unit!=2) || (op!=2 && op!=3))return health_sd_original(p);
    Scope *s=&timing_stats[unit-1];uint32_t epoch;
    if(!begin(s,&epoch))return health_sd_original(p);
    /* Native packet length/layout are the original dispatcher's contract. */
    uint32_t amount=*(const uint32_t*)(p+12),sector=*(const uint32_t*)(p+16);
    SET(&s->op[op-2].calls,OBS(&s->op[op-2].calls)+1);
    uint32_t start=TICKS,result=health_sd_original(p);
    finish(s,op-2,epoch,result,TICKS-start,amount,sector);return result;
}
static uint32_t file(uint32_t write,uint32_t handle,void *buffer,uint32_t bytes,uint32_t *actual) {
    Scope *s=&timing_stats[2];uint32_t epoch,start=0;int observed=begin(s,&epoch);
    if(observed){SET(&s->op[write].calls,OBS(&s->op[write].calls)+1);start=TICKS;}
    uint32_t result=write?timing_write_original(handle,buffer,bytes,actual):
                          timing_read_original(handle,buffer,bytes,actual);
    if(observed)finish(s,write,epoch,result,TICKS-start,bytes,handle);
    return result;
}
uint32_t timing_read(uint32_t h,void *b,uint32_t n,uint32_t *a){return file(0,h,b,n,a);}
uint32_t timing_write(uint32_t h,const void *b,uint32_t n,uint32_t *a){return file(1,h,(void*)b,n,a);}
static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127);value>>=7;}
}
/* Separate fixed protocol from trial 04: request 7B, reply 7A. No memory-query
 * address, reset, mutation or recording command is accepted. */
uint32_t health_query(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8)return 0;
    if(p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] || p[4]!=0x7b ||
       p[5]<1 || p[5]>7 || p[6]>127 || p[7]!=0xf7 || B(0x80629b60u)!=2)return 0;
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    uint8_t reply[118];reply[0]=0xf0;reply[1]=0x52;reply[2]=reply[3]=0;
    reply[4]=0x7a;reply[5]=p[5];reply[6]=p[6];uint32_t n;
    if(p[5]==1) {
        for(uint32_t i=0;i<5;i++)encode(reply+7+i*5,W(0x801f901cu+i*4));
        encode(reply+32,TICKS);encode(reply+37,W(0x8020f664u));
        encode(reply+42,W(0x808e28e0u));encode(reply+47,W(0x808e28f0u));
        encode(reply+52,W(0x801f8e48u));encode(reply+57,W(0x801f8e58u));
        encode(reply+62,W(0x801f8e54u));encode(reply+67,W(0x801f8e64u));n=73;
    } else {
        uint32_t index=p[5]-2;Scope *s=&timing_stats[index>>1];
        const uint32_t *op=(const uint32_t*)&s->op[index&1];
        encode(reply+7,LD(&s->epoch));encode(reply+12,LD(&s->busy_skips));
        encode(reply+17,LD(&s->claim_skips));
        for(uint32_t i=0;i<17;i++)encode(reply+22+i*5,LD(op+i));
        encode(reply+107,LD(&s->epoch));encode(reply+112,TICKS);n=118;
    }
    reply[n-1]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,n,2);
    return 1;
}
