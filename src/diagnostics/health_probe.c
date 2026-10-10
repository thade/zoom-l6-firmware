/* Observation-only v1.10 experiment. No allocation, new task, file operation,
 * MMIO access, recording tap, reset, retry or physical-completion permission. */
#include <stdint.h>
#define W(a) (*(volatile uint32_t *)(a))
#define B(a) (*(volatile uint8_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define TICKS W(0x801f9050u)
typedef struct {uint32_t epoch,reads,writes,skipped,result,last_ticks,max_ticks;} SdStats;
/* PROGBITS inside the original loaded MAIN span; no BSS/scatter gap. */
__attribute__((section(".probe_state"),aligned(32),used))
SdStats health_sd_stats[2]={0};
extern uint32_t health_sd_original(const uint8_t *packet);
static void inc(uint32_t *p){__atomic_fetch_add(p,1,__ATOMIC_RELAXED);}
uint32_t health_sd(const uint8_t *p) {
    uint32_t unit=p[1],op=p[0];
    if((unit!=1 && unit!=2) || (op!=2 && op!=3))return health_sd_original(p);
    SdStats *s=&health_sd_stats[unit-1];uint32_t epoch=LD(&s->epoch);
    /* Never wait for an observer slot: preserve stock admission/scheduling.
     * A failed weak claim is counted, and that call proceeds unobserved. */
    if((epoch&1) || !__atomic_compare_exchange_n(&s->epoch,&epoch,epoch+1,1,
                                                 __ATOMIC_ACQ_REL,__ATOMIC_RELAXED)) {
        inc(&s->skipped);return health_sd_original(p);
    }
    inc(op==2?&s->reads:&s->writes);
    uint32_t start=TICKS,result=health_sd_original(p),elapsed=TICKS-start;
    ST(&s->result,result);ST(&s->last_ticks,elapsed);
    if(elapsed>LD(&s->max_ticks))ST(&s->max_ticks,elapsed);
    ST(&s->epoch,epoch+2);return result;
}
static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127);value>>=7;}
}
/* Exact experimental requests only: F0 52 00 00 7D kind token F7.
 * kind=1 heap/card RAM; kind=2/3 SD packet unit=1/2. Session must already be 2.
 * All other messages continue through the displaced original prologue. */
uint32_t health_query(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8)return 0;
    if(p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] || p[4]!=0x7d ||
       p[5]<1 || p[5]>3 || p[6]>127 || p[7]!=0xf7 || B(0x80629b60u)!=2)return 0;
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    uint8_t reply[73];reply[0]=0xf0;reply[1]=0x52;reply[2]=reply[3]=0;
    reply[4]=0x7c;reply[5]=p[5];reply[6]=p[6];uint32_t n;
    if(p[5]==1) {
        /* Individual aligned observations, not an atomic multi-field snapshot.
         * The first heap word is its initialized sentinel, NOT free space. */
        for(uint32_t i=0;i<5;i++)encode(reply+7+i*5,W(0x801f901cu+i*4));
        encode(reply+32,TICKS);encode(reply+37,W(0x8020f664u));
        encode(reply+42,W(0x808e28e0u));encode(reply+47,W(0x808e28f0u));
        encode(reply+52,W(0x801f8e48u));encode(reply+57,W(0x801f8e58u));
        encode(reply+62,W(0x801f8e54u));encode(reply+67,W(0x801f8e64u));n=73;
    } else {
        SdStats *s=&health_sd_stats[p[5]-2];
        encode(reply+7,LD(&s->epoch));
        encode(reply+12,LD(&s->reads));encode(reply+17,LD(&s->writes));
        encode(reply+22,LD(&s->skipped));encode(reply+27,LD(&s->result));
        encode(reply+32,LD(&s->last_ticks));encode(reply+37,LD(&s->max_ticks));
        encode(reply+42,LD(&s->epoch));encode(reply+47,TICKS);n=53;
    }
    reply[n-1]=0xf7;
    /* Original sender copies into its protected MIDI ring before returning.
     * Route 2 is the original editor reply route. No shared reply scratch. */
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,n,2);
    return 1;
}
