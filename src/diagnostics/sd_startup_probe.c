/* Passive first-enumeration observations. No allocation, task, extra command,
 * MMIO writes, wait extension, buffer retention or completion permission.
 * Raw flags have temporal association only; they do not identify their source. */
#include <stdint.h>
#define W(a) (*(volatile const uint32_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#ifdef SD_STARTUP_DETAIL
#define STARTUP_SLOTS 8
#define STARTUP_SCHEMA 2
#define STARTUP_KINDS 11
#define SAMPLE_WORDS 18
#else
#define STARTUP_SLOTS 4
#define STARTUP_SCHEMA 1
#define STARTUP_KINDS 6
#define SAMPLE_WORDS 16
#endif
typedef struct {
    uint32_t site,event,task,mask,mode,timeout,status,flags,raw,present,system,mix;
    uint32_t blocks,commands,irqs,sequence;
#ifdef SD_STARTUP_DETAIL
    uint32_t code,argument;
#endif
} StartupSample;
typedef struct {
    uint32_t epoch,skipped,resets,reset[8];
    uint32_t attempts,active,done,result,card,owner,commands,codes_lo,codes_hi;
    uint32_t irqs,raw_union,raw_current,waits,pio_waits,omitted,errors;
    StartupSample samples[STARTUP_SLOTS];
#ifdef SD_STARTUP_DETAIL
    uint32_t current_code,current_argument,first_command[8];
#endif
} StartupTrace;
__attribute__((section(".probe_state"),aligned(32),used)) StartupTrace startup_trace={0};
_Static_assert(sizeof(StartupSample)==4*SAMPLE_WORDS,"startup sample ABI");
#ifdef SD_STARTUP_DETAIL
_Static_assert(sizeof(StartupTrace)==724,"startup detail trace ABI");
#else
_Static_assert(sizeof(StartupTrace)==364,"startup trace ABI");
#endif

static uint32_t claim(void) {
    uint32_t e=LD(&startup_trace.epoch);
    if((e&1u) || !__atomic_compare_exchange_n(&startup_trace.epoch,&e,e+1,0,
                                                  __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
        (void)__atomic_fetch_add(&startup_trace.skipped,1,__ATOMIC_RELAXED);return 0;
    }
    return e+1;
}
/* Inline point 69c14: the native clock gate is enabled, after its reset request
 * and inhibit polling but BEFORE it issues initial clocks. Read once, no retry. */
void startup_reset_sample(void) {
    uint32_t e=claim();if(!e)return;
    StartupTrace *t=&startup_trace;
    if(!t->resets++) {
        t->reset[0]=W(0x402c002cu);t->reset[1]=W(0x402c0024u);
        t->reset[2]=W(0x402c0030u);t->reset[3]=W(0x402c0038u);
        t->reset[4]=W(0xe000e10cu);t->reset[5]=W(0xe000e20cu);
        t->reset[6]=W(0xe000e30cu);t->reset[7]=W(0x801f5fc0u);
    }
    ST(&t->epoch,e+1);
}
extern uint32_t health_sd(const uint8_t *);
uint32_t startup_sd(const uint8_t *p) {
    if(p[0]!=4 || p[1]!=1)return health_sd(p);
    StartupTrace *t=&startup_trace;uint32_t e=claim(),ticket=0;
    if(e) {
        t->attempts++;
        if(!t->done && !t->active && t->attempts==1) {
            t->active=1;t->owner=W(0x808e291cu);ticket=1;
        } else t->omitted++;
        ST(&t->epoch,e+1);
    }
    uint32_t result=health_sd(p);
    if(ticket) {
        e=claim();
        if(e) {
            t->result=result;t->card=W(0x801f8e48u);t->done=1;t->active=0;
            ST(&t->epoch,e+1);
        }
        /* A missed final sample leaves active/done visibly incomplete. */
    }
    return result;
}
void startup_command_sample(const void *request,uint32_t unit) {
    StartupTrace *t=&startup_trace;if(unit || !LD(&t->active))return;
    uint32_t e=claim();if(!e)return;
    uint32_t code=*(const uint8_t*)request;
#ifdef SD_STARTUP_DETAIL
    /* The native command callback runs inside the clock-enabled dispatcher.
     * The outer startup_sd entry/return do not have that guarantee. */
    if(!t->commands) {
        t->first_command[0]=W(0x402c002cu);t->first_command[1]=W(0x402c0024u);
        t->first_command[2]=W(0x402c0030u);t->first_command[3]=W(0x402c0038u);
        t->first_command[4]=W(0xe000e10cu);t->first_command[5]=W(0xe000e20cu);
        t->first_command[6]=W(0xe000e30cu);t->first_command[7]=W(0x801f5fc0u);
    }
    /* Software42 is the recursive CMD55 prefix. Keep the enclosing request
     * for the later PIO data sample; raw IRQ association remains temporal. */
    if(code!=42) {
        t->current_code=code;
        t->current_argument=*(const uint32_t*)((const uint8_t*)request+4);
    }
#endif
    t->commands++;t->raw_current=0;
    if(code<32)t->codes_lo|=1u<<code;
    else if(code<64)t->codes_hi|=1u<<(code-32);
    else t->errors++;
    if(W(0x808e291cu)!=t->owner)t->errors++;
    ST(&t->epoch,e+1);
}
void startup_irq_sample(uint32_t unit,uint32_t raw) {
    StartupTrace *t=&startup_trace;if(unit || !LD(&t->active))return;
    uint32_t e=claim();if(!e)return;
    t->irqs++;t->raw_union|=raw;t->raw_current|=raw;
    if(raw&0x157f0000u)t->errors++;
    ST(&t->epoch,e+1);
}
typedef int32_t (*Wait)(uint32_t,uint32_t,uint32_t,uint32_t *,uint32_t);
__attribute__((noinline)) int32_t startup_wait(uint32_t event,uint32_t mask,
                      uint32_t mode,uint32_t *flags,uint32_t timeout) {
    StartupTrace *t=&startup_trace;
    uint32_t site=(uint32_t)__builtin_return_address(0)&~1u;
    uint32_t active=LD(&t->active);
    int32_t result=((Wait)0x800328c1u)(event,mask,mode,flags,timeout);
    if(!active)return result;
    uint32_t e=claim();if(!e)return result;
    t->waits++;
    uint32_t f=result?0:LD(flags);
    if(result || (f&0x181u) || W(0x808e291cu)!=t->owner ||
       event!=W(0x808e28e0u))t->errors++;
    if(site==0x80069d68u || site==0x8006a908u) {
        uint32_t n=t->pio_waits++;
        if(n<STARTUP_SLOTS) {
            StartupSample *s=&t->samples[n];
            s->site=site;s->event=event;s->task=W(0x808e291cu);s->mask=mask;
            s->mode=mode;s->timeout=timeout;s->status=(uint32_t)result;s->flags=f;
            s->raw=t->raw_current;s->present=W(0x402c0024u);s->system=W(0x402c002cu);
            s->mix=W(0x402c0048u);s->blocks=W(0x402c0004u);
            s->commands=t->commands;s->irqs=t->irqs;s->sequence=n+1;
#ifdef SD_STARTUP_DETAIL
            s->code=t->current_code;s->argument=t->current_argument;
#endif
        } else t->omitted++;
    }
    ST(&t->epoch,e+1);return result;
}
static void encode(uint8_t *p,uint32_t v) {
    for(uint32_t i=0;i<5;i++){p[i]=(uint8_t)(v&127u);v>>=7;}
}
extern uint32_t ram_activity_dispatch(const uint8_t *);
/* Fixed 6D/6C queries: summary, first reset, bounded PIO samples; schema2
 * additionally supplies the first-command snapshot as kind11.
 * Each reply brackets its RAM reads with the observer epoch; queries never
 * clear state or read hardware. Frozen records survive later file transfers. */
uint32_t startup_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x6d || p[5]<1 || p[5]>STARTUP_KINDS || p[6]>127 || p[7]!=0xf7 ||
       *(volatile const uint8_t*)0x80629b60u!=2)return ram_activity_dispatch(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    StartupTrace *t=&startup_trace;
    uint8_t reply[28+5*SAMPLE_WORDS]={0xf0,0x52,0,0,0x6c,p[5],p[6]};
    encode(reply+7,STARTUP_SCHEMA);encode(reply+12,LD(&t->epoch));encode(reply+17,LD(&t->skipped));
    const uint32_t *body;
    uint32_t words;
    if(p[5]==1){body=&t->attempts;words=16;}
    else if(p[5]==2){body=&t->resets;words=9;}
#ifdef SD_STARTUP_DETAIL
    else if(p[5]==11){body=t->first_command;words=8;}
#endif
    else {body=(const uint32_t*)&t->samples[p[5]-3];words=SAMPLE_WORDS;}
    for(uint32_t i=0;i<words;i++)encode(reply+22+i*5,LD(body+i));
    encode(reply+22+words*5,LD(&t->epoch));uint32_t length=28+words*5;
    reply[length-1]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,length,2);
    return 1;
}
