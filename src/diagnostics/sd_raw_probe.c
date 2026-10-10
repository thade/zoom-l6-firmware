/* Passive raw IRQ observation. No completion permission, controller writes,
 * interrupt masking, buffer retention, reset, retry or capture is added. */
#include <stdint.h>
#define W(a) (*(volatile uint32_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
typedef struct {
    uint32_t unit,raw,signal,present,system,protocol,mix,dma,task,event;
    uint32_t ccr,dtcm,itcm;
} RawSample;
typedef struct {
    uint32_t epoch,skipped,irqs,tc,errors,tc_errors,dma_tc,units;
    RawSample first_tc,last_tc,last_error;
} RawTrace;
__attribute__((section(".probe_state"),aligned(32),used))
RawTrace raw_trace={0};
_Static_assert(sizeof(RawTrace)==188,"fixed raw trace ABI");

/* R0/R1 are the native handler's unit and FULL INT_STATUS snapshot, before
 * W1C and signal masking. The current task is the interrupted task; it is
 * deliberately not identified as the owner of the transfer. */
void raw_irq_sample(uint32_t unit,uint32_t raw) {
#ifdef SD_STARTUP_OBSERVER
    extern void startup_irq_sample(uint32_t,uint32_t);
    startup_irq_sample(unit,raw);
#endif
#ifdef SD_COMMAND_OBSERVER
    extern void command_irq_sample(uint32_t,uint32_t);
    command_irq_sample(unit,raw);
#endif
    RawTrace *t=&raw_trace;uint32_t epoch=LD(&t->epoch);
    if((epoch&1) || !__atomic_compare_exchange_n(&t->epoch,&epoch,epoch+1,0,
                                    __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
        (void)__atomic_fetch_add(&t->skipped,1,__ATOMIC_RELAXED);return;
    }
    t->irqs++;if(unit<32)t->units|=1u<<unit;
    uint32_t tc=raw&2u,error=raw&0x157f0000u;
    if(tc || error) {
        /* Core-register reads use the M7 architectural layout also present in
         * the stock setup. Queries later return these stored values only. */
        RawSample s={unit,raw,W(0x402c0038u),W(0x402c0024u),W(0x402c002cu),
            W(0x402c0028u),W(0x402c0048u),W(0x402c0000u),W(0x808e291cu),
            unit<2?W(0x808e28e0u+unit*16u):0,
            W(0xe000ed14u),W(0xe000ef94u),W(0xe000ef90u)};
        if(tc) {
            if(!t->tc)t->first_tc=s;
            t->last_tc=s;t->tc++;if(s.mix&1u)t->dma_tc++;
        }
        if(error){t->last_error=s;t->errors++;if(tc)t->tc_errors++;}
    }
    ST(&t->epoch,epoch+2);
}
static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127u);value>>=7;}
}
extern uint32_t completion_dispatch(const uint8_t *);
/* Fixed read-only 75/74 kinds 1 latest TC, 2 first TC, 3 latest raw error,
 * 4 counters. Existing completion 73/72 and health 7D/7C remain available. */
uint32_t raw_completion_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x75 || p[5]<1 || p[5]>4 || p[6]>127 || p[7]!=0xf7 ||
       *(volatile uint8_t*)0x80629b60u!=2)return completion_dispatch(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    RawTrace *t=&raw_trace;
    uint8_t reply[113]={0xf0,0x52,0,0,0x74,p[5],p[6]};
    if(p[5]==4) {
        const uint32_t values[]={2,LD(&t->epoch),LD(&t->irqs),LD(&t->skipped),
            LD(&t->tc),LD(&t->errors),LD(&t->tc_errors),LD(&t->dma_tc),LD(&t->units),
            LD(&t->last_tc.ccr),LD(&t->last_tc.dtcm),LD(&t->last_tc.itcm),
            LD(&t->epoch),W(0x801f9050u)};
        for(uint32_t i=0;i<14;i++)encode(reply+7+i*5,values[i]);reply[77]=0xf7;
        ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,78,2);return 1;
    }
    RawSample *s=p[5]==1?&t->last_tc:p[5]==2?&t->first_tc:&t->last_error;
    const uint32_t values[]={1,LD(&t->epoch),LD(&t->irqs),LD(&t->skipped),
        LD(&t->tc),LD(&t->errors),LD(&s->unit),LD(&s->raw),LD(&s->signal),
        LD(&s->present),LD(&s->system),LD(&s->protocol),LD(&s->mix),LD(&s->dma),
        LD(&s->task),LD(&s->event),LD(&s->ccr),LD(&s->dtcm),LD(&s->itcm),
        LD(&t->epoch),W(0x801f9050u)};
    for(uint32_t i=0;i<21;i++)encode(reply+7+i*5,values[i]);reply[112]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,sizeof(reply),2);return 1;
}
