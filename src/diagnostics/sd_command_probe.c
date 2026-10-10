/* Passive native command/buffer journal. It never grants a physical join,
 * changes an event/controller, waits for an observer lock or retains buffers. */
#include <stdint.h>
#define W(a) (*(volatile uint32_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
typedef struct { uint32_t sequence,site,address,task,ipsr,raw,present,system; } Program;
typedef struct {
    uint32_t sequence,unit,task,event,code,request,address,bytes;
    uint32_t program_sequence,program_site,program_task,program_address,program_raw,program_present;
    uint32_t entry_raw,entry_present,entry_system,irq_raw,irq_count,tc_count,command_status;
    uint32_t wait_site,wait_status,wait_flags,wait_present,wait_dma,reasons,skipped_before;
} CommandSample;
typedef struct {
    uint32_t epoch,skipped,programs,program_sites,commands,data_commands,waits,unmatched,anomalies,active,consumed_program;
    Program program;
    CommandSample current,last,last_anomaly;
} CommandTrace;
__attribute__((section(".probe_state"),aligned(32),used)) CommandTrace command_trace={0};
_Static_assert(sizeof(CommandSample)==112,"command sample ABI");
_Static_assert(sizeof(CommandTrace)==412,"command trace ABI");
enum { NO_PROGRAM=1, ENTRY_ACTIVITY=2, ENTRY_RAW=4, RAW_ERROR=8, NO_TC=16,
       BAD_WAIT=32, OWNER_EVENT=64, COMMAND_ERROR=128, WAIT_ACTIVITY=256,
       BAD_SHAPE=512, OVERLAP=1024, OBSERVER_GAP=2048, RESET=4096 };
static uint32_t claim(CommandTrace *t) {
    uint32_t e=LD(&t->epoch);
    if((e&1) || !__atomic_compare_exchange_n(&t->epoch,&e,e+1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
        (void)__atomic_fetch_add(&t->skipped,1,__ATOMIC_RELAXED);return 0;
    }
    return e+1;
}
static void copy_sample(CommandSample *out,const CommandSample *in) {
    volatile uint32_t *d=(volatile uint32_t*)out;
    const volatile uint32_t *s=(const volatile uint32_t*)in;
    for(uint32_t i=0;i<28;i++)d[i]=s[i];
}
static void publish(CommandTrace *t) {
    CommandSample *s=&t->current;
    if(LD(&t->skipped)!=s->skipped_before)s->reasons|=OBSERVER_GAP;
    copy_sample(&t->last,s);
    if(s->reasons){t->anomalies++;copy_sample(&t->last_anomaly,s);}
    t->active=0;
}
/* Called immediately BEFORE each of the four native DS_ADDR stores. */
void command_program_sample(uint32_t address,uint32_t site) {
    CommandTrace *t=&command_trace;uint32_t e=claim(t);if(!e)return;
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    const uint32_t sites[]={0x80069fecu,0x8006a180u,0x8006abf0u,0x8006adacu};
    for(uint32_t i=0;i<4;i++)if(site==sites[i])t->program_sites|=1u<<i;
    Program *p=&t->program;p->sequence=++t->programs;p->site=site;p->address=address;
    p->task=W(0x808e291cu);p->ipsr=ipsr;p->raw=W(0x402c0030u);
    p->present=W(0x402c0024u);p->system=W(0x402c002cu);
    if(t->active)t->current.reasons|=OVERLAP;
    ST(&t->epoch,e+1);
}
extern int32_t command_stock(void *,uint32_t);
__attribute__((noinline)) int32_t command_probe(void *request,uint32_t unit) {
#ifdef SD_STARTUP_OBSERVER
    extern void startup_command_sample(const void *,uint32_t);
    startup_command_sample(request,unit);
#endif
    CommandTrace *t=&command_trace;uint32_t e=claim(t),ticket=0;
    if(e) {
        t->commands++;uint32_t code=*(const uint8_t*)request;
        /* Only known block packet layouts are read beyond their first byte. */
        if(code==22 || code==23 || code==32 || code==33) {
            const uint32_t *w=request;
            if(t->active){t->unmatched++;t->current.reasons|=OVERLAP;}
            else {
                CommandSample *s=&t->current;
                volatile uint32_t *v=(volatile uint32_t*)s;
                for(uint32_t i=0;i<28;i++)v[i]=0;
                s->sequence=++t->data_commands;if(!s->sequence)s->sequence=++t->data_commands;
                s->unit=unit;s->task=W(0x808e291cu);
                s->event=unit<2?W(0x808e28e0u+unit*16u):0;s->code=code;
                s->request=(uint32_t)request;s->address=W(0x402c0000u);
                /* Native packet +16 is a block COUNT. The original command
                 * engine supplies the fixed 512-byte length for these packets;
                 * it is not the packed BLK_ATT register layout. */
                s->bytes=(w[4]&0xffffu)*512u;
                s->entry_raw=W(0x402c0030u);s->entry_present=W(0x402c0024u);
                s->entry_system=W(0x402c002cu);s->skipped_before=LD(&t->skipped);
                Program *p=&t->program;s->program_sequence=p->sequence;s->program_site=p->site;
                s->program_task=p->task;s->program_address=p->address;
                s->program_raw=p->raw;s->program_present=p->present;
                if(!p->sequence || p->sequence==t->consumed_program || p->ipsr ||
                   p->task!=s->task || p->address!=s->address)s->reasons|=NO_PROGRAM;
                t->consumed_program=p->sequence;
                if((p->present|s->entry_present)&0x307u)s->reasons|=ENTRY_ACTIVITY;
                if((p->raw|s->entry_raw)&0x157f003fu)s->reasons|=ENTRY_RAW;
                if((p->system|s->entry_system)&0x07000000u)s->reasons|=RESET;
                if(!s->task || !s->event || unit>=2)s->reasons|=OWNER_EVENT;
                if(w[5]!=1 || (w[4]>>16) || !s->bytes)s->reasons|=BAD_SHAPE;
                t->active=1;ticket=s->sequence;
            }
        }
        ST(&t->epoch,e+1);
    }
    int32_t result=command_stock(request,unit);
    if(ticket) {
        e=claim(t);
        if(e) {
            if(t->active && t->current.sequence==ticket) {
                t->current.command_status=(uint32_t)result;
                if(result){t->current.reasons|=COMMAND_ERROR;publish(t);}
            } else t->unmatched++;
            ST(&t->epoch,e+1);
        }
    }
    return result;
}
/* Full raw status supplied before native W1C. A software sequence is only
 * temporal association; old physical IRQs could still be attributed here. */
void command_irq_sample(uint32_t unit,uint32_t raw) {
    CommandTrace *t=&command_trace;uint32_t e=claim(t);if(!e)return;
    if(t->active) {
        CommandSample *s=&t->current;
        if(unit!=s->unit){t->unmatched++;s->reasons|=OWNER_EVENT;}
        else {s->irq_raw|=raw;s->irq_count++;if(raw&2u)s->tc_count++;
              if(raw&0x157f0000u)s->reasons|=RAW_ERROR;}
    }
    ST(&t->epoch,e+1);
}
uint32_t command_wait_begin(uint32_t event,uint32_t site) {
    CommandTrace *t=&command_trace;uint32_t e=claim(t),ticket=0;if(!e)return 0;
    if(t->active) {
        CommandSample *s=&t->current;ticket=s->sequence;s->wait_site=site;
        if(event!=s->event || W(0x808e291cu)!=s->task)s->reasons|=OWNER_EVENT;
    } else t->unmatched++;
    ST(&t->epoch,e+1);return ticket;
}
void command_wait_end(uint32_t ticket,int32_t result,uint32_t flags) {
    CommandTrace *t=&command_trace;uint32_t e=claim(t);if(!e)return;
    t->waits++;
    if(ticket && t->active && t->current.sequence==ticket) {
        CommandSample *s=&t->current;s->wait_status=(uint32_t)result;s->wait_flags=flags;
        s->wait_present=W(0x402c0024u);s->wait_dma=W(0x402c0000u);
        if(result || !(flags&4u) || (flags&0x181u))s->reasons|=BAD_WAIT;
        if(!s->tc_count)s->reasons|=NO_TC;
        if(s->wait_present&0x307u)s->reasons|=WAIT_ACTIVITY;
        if(W(0x808e291cu)!=s->task)s->reasons|=OWNER_EVENT;
        publish(t);
    } else t->unmatched++;
    ST(&t->epoch,e+1);
}
static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127u);value>>=7;}
}
extern uint32_t raw_completion_dispatch(const uint8_t *);
uint32_t command_completion_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x71 || p[5]<1 || p[5]>3 || p[6]>127 || p[7]!=0xf7 ||
       *(volatile uint8_t*)0x80629b60u!=2)return raw_completion_dispatch(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    CommandTrace *t=&command_trace;
    uint32_t values[39],n=0;values[n++]=1;values[n++]=LD(&t->epoch);
    values[n++]=LD(&t->skipped);values[n++]=LD(&t->programs);values[n++]=LD(&t->program_sites);
    values[n++]=LD(&t->commands);values[n++]=LD(&t->data_commands);values[n++]=LD(&t->waits);
    values[n++]=LD(&t->unmatched);values[n++]=LD(&t->anomalies);values[n++]=LD(&t->active);
    if(p[5]!=3) {
        const volatile uint32_t *s=(const volatile uint32_t*)(p[5]==1?&t->last:&t->last_anomaly);
        for(uint32_t i=0;i<28;i++)values[n++]=LD(s+i);
    }
    /* 11 common + 28 sample + epoch/ticks = 41 words (213 bytes). */
    uint32_t bytes=8+(n+2)*5;
    uint8_t output[213]={0xf0,0x52,0,0,0x70,p[5],p[6]};
    for(uint32_t i=0;i<n;i++)encode(output+7+i*5,values[i]);
    encode(output+7+n*5,LD(&t->epoch));encode(output+12+n*5,W(0x801f9050u));
    output[bytes-1]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(output,bytes,2);
    return 1;
}
