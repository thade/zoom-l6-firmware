/* Passive observation at four v1.10 DMA data-wait call sites. Never authorizes
 * buffer reuse, adds a transfer, changes controller state or joins a failure.
 * Register snapshots are sequential observations, not an atomic hardware state. */
#include <stdint.h>
#define W(a) (*(volatile uint32_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
typedef int32_t (*Wait)(uint32_t,uint32_t,uint32_t,uint32_t *,uint32_t);
typedef struct {
    uint32_t site,event,task,timeout,status,flags;
    uint32_t before_present,present,system,protocol,mix,vendor2,dma;
} CompletionSample;
#ifdef SD_COMPLETION_DETAIL
typedef struct {
    uint32_t waits,anomalies,reasons;
    CompletionSample last_anomaly;
} CompletionSite;
#endif
typedef struct {
    uint32_t epoch,waits,skipped,sites,anomalies;
    CompletionSample first,last;
#ifdef SD_COMPLETION_DETAIL
    CompletionSite by_site[4];
#endif
} CompletionTrace;
__attribute__((section(".probe_state"),aligned(32),used))
CompletionTrace completion_trace={0};
static uint32_t site_bit(uint32_t pc) {
    const uint32_t sites[]={0x8006a06eu,0x8006a1f8u,0x8006ac72u,0x8006ae14u};
    for(uint32_t i=0;i<4;i++)if(pc==sites[i])return 1u<<i;return 0;
}
#ifdef SD_COMPLETION_DETAIL
/* A union identifies every category seen at a site, not the number of occurrences
 * in each category. Activity keeps its individual PRES_STATE bits at bit 8. */
static uint32_t reasons(const CompletionSample *s,uint32_t bit,uint32_t mask,uint32_t mode) {
    uint32_t r=0;
    if(s->status)r|=1;
    else if(!(s->flags&4))r|=2;
    if(s->flags&0x181u)r|=4;
    if(s->system&0x07000000u)r|=8;
    if((s->protocol&0x330u)!=0x20u || (s->vendor2&0x1000u) || !(s->mix&1u))r|=16;
    if(!bit || mask!=0x185u || mode!=1 || !s->event || !s->task || s->timeout!=5000)r|=32;
    return r|((s->present&0x307u)<<8);
}
#endif
__attribute__((noinline)) int32_t completion_wait(uint32_t event,uint32_t mask,
                              uint32_t mode,uint32_t *flags,uint32_t timeout) {
    CompletionTrace *t=&completion_trace;
    uint32_t epoch=LD(&t->epoch),site=(uint32_t)__builtin_return_address(0)&~1u;
#ifdef SD_COMMAND_OBSERVER
    extern uint32_t command_wait_begin(uint32_t,uint32_t);
    extern void command_wait_end(uint32_t,int32_t,uint32_t);
    uint32_t ticket=command_wait_begin(event,site);
#endif
    /* No observer lock is held by Main or an IRQ. Never wait for a claim. */
    if((epoch&1) || !__atomic_compare_exchange_n(&t->epoch,&epoch,epoch+1,0,
                                                __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
        (void)__atomic_fetch_add(&t->skipped,1,__ATOMIC_RELAXED);
        int32_t result=((Wait)0x800328c1u)(event,mask,mode,flags,timeout);
#ifdef SD_COMMAND_OBSERVER
        command_wait_end(ticket,result,result?0:LD(flags));
#endif
        return result;
    }
    CompletionSample s={0};s.site=site;s.event=event;s.task=W(0x808e291cu);s.timeout=timeout;
    s.before_present=W(0x402c0024u);
    int32_t result=((Wait)0x800328c1u)(event,mask,mode,flags,timeout);
#ifdef SD_COMMAND_OBSERVER
    command_wait_end(ticket,result,result?0:LD(flags));
#endif
    /* Before the original driver can copy/rewrite bounce data or submit the
     * next chunk. A failed wait does not promise a flags output was written. */
    s.status=(uint32_t)result;s.flags=result?0:LD(flags);
    s.present=W(0x402c0024u);s.system=W(0x402c002cu);s.protocol=W(0x402c0028u);
    s.mix=W(0x402c0048u);s.vendor2=W(0x402c00c8u);s.dma=W(0x402c0000u);
    uint32_t bit=site_bit(site);
    uint32_t anomaly=result || !bit || mask!=0x185u || mode!=1 ||
        !s.event || !s.task || timeout!=5000 || !(s.flags&4) || (s.flags&0x181u) ||
        (s.present&0x307u) || (s.system&0x07000000u) ||
        (s.protocol&0x330u)!=0x20u || (s.vendor2&0x1000u) || !(s.mix&1u);
    t->waits++;t->sites|=bit;t->last=s;
    if(anomaly){if(!t->anomalies)t->first=s;t->anomalies++;}
#ifdef SD_COMPLETION_DETAIL
    if(bit) {
        uint32_t i=0;while((1u<<i)!=bit)i++;
        CompletionSite *p=&t->by_site[i];p->waits++;
        if(anomaly){p->anomalies++;p->reasons|=reasons(&s,bit,mask,mode);p->last_anomaly=s;}
    }
#endif
    ST(&t->epoch,epoch+2);return result;
}
static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127);value>>=7;}
}
extern uint32_t health_query(const uint8_t *);
/* Fixed read-only F0 52 00 00 73 kind token F7; replies use 72. Kind 1 latest,
 * kind 2 first anomaly. Detail build adds 3 per-site counters/reason unions and
 * 4..7 latest anomaly per site. No query clears state or samples MMIO. */
uint32_t completion_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
#ifdef SD_COMPLETION_DETAIL
    const uint32_t max_kind=7;
#else
    const uint32_t max_kind=2;
#endif
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x73 || p[5]<1 || p[5]>max_kind || p[6]>127 || p[7]!=0xf7 ||
       *(volatile uint8_t*)0x80629b60u!=2)return health_query(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    uint8_t reply[113]={0xf0,0x52,0,0,0x72,p[5],p[6]};
    CompletionTrace *t=&completion_trace;CompletionSample *s=p[5]==1?&t->last:&t->first;
#ifdef SD_COMPLETION_DETAIL
    if(p[5]==3) {
        const uint32_t values[]={2,LD(&t->epoch),LD(&t->waits),LD(&t->skipped),
            LD(&t->sites),LD(&t->anomalies),
            LD(&t->by_site[0].waits),LD(&t->by_site[1].waits),
            LD(&t->by_site[2].waits),LD(&t->by_site[3].waits),
            LD(&t->by_site[0].anomalies),LD(&t->by_site[1].anomalies),
            LD(&t->by_site[2].anomalies),LD(&t->by_site[3].anomalies),
            LD(&t->by_site[0].reasons),LD(&t->by_site[1].reasons),
            LD(&t->by_site[2].reasons),LD(&t->by_site[3].reasons),
            LD(&t->epoch),W(0x801f9050u)};
        for(uint32_t i=0;i<20;i++)encode(reply+7+i*5,values[i]);reply[107]=0xf7;
        ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,108,2);
        return 1;
    }
    if(p[5]>=4)s=&t->by_site[p[5]-4].last_anomaly;
#endif
    const uint32_t values[]={1,LD(&t->epoch),LD(&t->waits),LD(&t->skipped),
        LD(&t->sites),LD(&t->anomalies),LD(&s->site),LD(&s->event),LD(&s->task),
        LD(&s->timeout),LD(&s->status),LD(&s->flags),LD(&s->before_present),
        LD(&s->present),LD(&s->system),LD(&s->protocol),LD(&s->mix),
        LD(&s->vendor2),LD(&s->dma),LD(&t->epoch),W(0x801f9050u)};
    for(uint32_t i=0;i<21;i++)encode(reply+7+i*5,values[i]);reply[112]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,sizeof(reply),2);
    return 1;
}
