/* Fixed-layout qualification only. No capture, allocation, worker, file request
 * or capacity repair. Kind 2 explicitly writes at most 2 KiB of tail guards;
 * kind 3 reads at most 2 KiB. Native IO always proceeds exactly once. */
#include <stdint.h>
#define W(a) (*(volatile uint32_t *)(a))
#define B(a) (*(volatile uint8_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define GET(p) __atomic_load_n((p),__ATOMIC_RELAXED)
#define SET(p,v) __atomic_store_n((p),(v),__ATOMIC_RELAXED)
#define AUDIO 0x20010a48u
#define REC 0x8077ca30u
#define RING 0x81429800u
#define CAP 223104u
#define STRIDE 960000u
#define TAIL_WORDS (240000u-CAP)
#define TOTAL_WORDS (12u*TAIL_WORDS)
#define CHUNK 512u
#define TICKS W(0x801f9050u)
typedef struct {
    uint32_t epoch,state,init_words,scan_word,sweeps,bad_words;
    uint32_t first_bad_address,expected,actual,layout_faults,busy_refusals,claim_skips;
    uint32_t samples,unstable_samples,invalid_cursors,active_mask,producer,max_lag[12];
} Guards;
typedef struct {
    uint32_t epoch,requests,overlaps,invalid_spans;
    uint32_t first_operation,first_address,first_bytes,first_tail_address,claim_skips;
} Spans;
_Static_assert(sizeof(Guards)==116 && sizeof(Spans)==36,"fixed state layout");
__attribute__((section(".probe_state"),aligned(32),used)) Guards ring_guards={0};
__attribute__((section(".probe_state"),aligned(32),used)) Spans ring_spans={0};
__attribute__((used)) const uint32_t ring_layout[]={116,36,CAP,STRIDE,TAIL_WORDS,CHUNK,12};
extern uint32_t health_query(const uint8_t *);
extern uint32_t health_sd(const uint8_t *);
extern uint32_t timing_read(uint32_t,void *,uint32_t,uint32_t *);
extern uint32_t timing_write(uint32_t,const void *,uint32_t,uint32_t *);
static void inc(uint32_t *p){__atomic_fetch_add(p,1,__ATOMIC_RELAXED);}
/* One weak claim, never a wait/retry or a claim across a native call/reply. */
static int claim(uint32_t *p,uint32_t *miss,uint32_t *e){
    *e=LD(p);
    if((*e&1) || !__atomic_compare_exchange_n(p,e,*e+1,1,__ATOMIC_ACQ_REL,__ATOMIC_RELAXED)){
        inc(miss);return 0;
    }
    return 1;
}
static int coherent(void){
    return W(AUDIO+0x53e0)==RING && W(AUDIO+0x53f0)==RING &&
        W(AUDIO+0x53e8)==CAP && W(AUDIO+0x53f8)==CAP &&
        W(REC+0x50)==CAP && W(REC+0x1e94)==CAP &&
        W(AUDIO+0x53e4)<CAP && W(AUDIO+0x53f4)<CAP && W(REC+0x1e8c)<CAP;
}
static int idle(void){
    return !B(0x80578ebcu) && !W(REC+0x440) && !W(AUDIO+0x53d0) && W(REC+0x1e88)!=2;
}
static uint32_t address(uint32_t word){
    return RING+(word/TAIL_WORDS)*STRIDE+CAP*4+(word%TAIL_WORDS)*4;
}
static uint32_t pattern(uint32_t a){return a^0xa56c0d3bu;}
static void fault(void){inc(&ring_guards.layout_faults);SET(&ring_guards.state,3);}
static void guards(uint32_t initialize){
    Guards *s=&ring_guards;uint32_t e;
    if(!claim(&s->epoch,&s->claim_skips,&e))return;
    uint32_t state=GET(&s->state);
    if(state==3 || (initialize && state==2) || (!initialize && state!=2))goto done;
    if(!coherent()){fault();goto done;}
    if(initialize && !idle()){inc(&s->busy_refusals);goto done;}
    uint32_t start=initialize?GET(&s->init_words):GET(&s->scan_word);
    if(start>=TOTAL_WORDS){fault();goto done;}
    uint32_t end=start+CHUNK;if(end>TOTAL_WORDS)end=TOTAL_WORDS;
    for(uint32_t i=start;i<end;i++){
        uint32_t a=address(i),want=pattern(a);
        if(initialize)W(a)=want;
        else {
            uint32_t actual=W(a);
            if(actual!=want){
                if(!GET(&s->bad_words)){
                    SET(&s->first_bad_address,a);SET(&s->expected,want);SET(&s->actual,actual);
                }
                inc(&s->bad_words);
            }
        }
    }
    if(initialize){SET(&s->init_words,end);SET(&s->state,end==TOTAL_WORDS?2:1);}
    else {
        SET(&s->scan_word,end==TOTAL_WORDS?0:end);
        if(end==TOTAL_WORDS)inc(&s->sweeps);
        if(GET(&s->bad_words))SET(&s->state,3);
    }
    if(!coherent())fault();
done:ST(&s->epoch,e+2);
}
/* Sampled modulo distance only: missed whole laps and unsampled peaks are
 * invisible. One unstable snapshot is skipped, never retried. */
static void backlog(void){
    Guards *s=&ring_guards;uint32_t e;
    if(!claim(&s->epoch,&s->claim_skips,&e))return;
    if(!coherent()){fault();goto done;}
    uint32_t mask=W(REC+0x440),producer=W(AUDIO+0x53e4),read[12];
    for(uint32_t i=0;i<12;i++)read[i]=W(REC+0x20+4*i);
    if(mask!=W(REC+0x440) || producer!=W(AUDIO+0x53e4)){
        inc(&s->unstable_samples);goto done;
    }
    SET(&s->active_mask,mask);SET(&s->producer,producer);inc(&s->samples);
    for(uint32_t i=0;i<12;i++)if(mask&(1u<<i)){
        if(read[i]>=CAP){inc(&s->invalid_cursors);continue;}
        uint32_t lag=(producer+CAP-read[i])%CAP;
        if(lag>GET(&s->max_lag[i]))SET(&s->max_lag[i],lag);
    }
done:ST(&s->epoch,e+2);
}
/* Requested CPU spans, not physical DMA/cache aliases or completion. */
static void span(uint32_t operation,uint32_t a,uint32_t n,uint32_t invalid){
    Spans *s=&ring_spans;uint32_t e;
    if(!claim(&s->epoch,&s->claim_skips,&e))return;
    inc(&s->requests);
    if(invalid || n>0xffffffffu-a){inc(&s->invalid_spans);goto done;}
    if(n)for(uint32_t i=0;i<12;i++){
        uint32_t tail=RING+i*STRIDE+CAP*4,end=RING+(i+1)*STRIDE;
        if(a<end && a+n>tail){
            if(!GET(&s->overlaps)){
                SET(&s->first_operation,operation);SET(&s->first_address,a);
                SET(&s->first_bytes,n);SET(&s->first_tail_address,a>tail?a:tail);
            }
            inc(&s->overlaps);break;
        }
    }
done:ST(&s->epoch,e+2);
}
uint32_t ring_sd(const uint8_t *p){
    if((p[1]==1 || p[1]==2) && (p[0]==2 || p[0]==3)){
        uint32_t blocks=*(const uint32_t*)(p+12);
        span(p[0]+1,*(const uint32_t*)(p+8),blocks*512,blocks>0x7fffffu);
    }
    return health_sd(p);
}
uint32_t ring_read(uint32_t h,void *b,uint32_t n,uint32_t *a){
    span(1,(uint32_t)b,n,0);return timing_read(h,b,n,a);
}
uint32_t ring_write(uint32_t h,const void *b,uint32_t n,uint32_t *a){
    span(2,(uint32_t)b,n,0);return timing_write(h,b,n,a);
}
static void encode(uint8_t *out,uint32_t v){
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(v&127);v>>=7;}
}
uint32_t ring_dispatch(const uint8_t *packet){
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
        p[4]!=0x75 || p[5]<1 || p[5]>5 || p[6]>127 || p[7]!=0xf7 || B(0x80629b60u)!=2)
        return health_query(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    if(p[5]==2 || p[5]==3)guards(p[5]==2);
    if(p[5]==5)backlog();
    uint8_t reply[123];uint32_t n=0;
    reply[0]=0xf0;reply[1]=0x52;reply[2]=reply[3]=0;reply[4]=0x74;reply[5]=p[5];reply[6]=p[6];
#define PUT(v) do{encode(reply+7+5*n,(v));n++;}while(0)
    PUT(1);
    if(p[5]<=3){
        Guards *s=&ring_guards;PUT(LD(&s->epoch));
        const uint32_t *fields=&s->state;
        for(uint32_t i=0;i<11;i++)PUT(LD(fields+i));
        PUT(W(AUDIO+0x53e0));PUT(W(AUDIO+0x53f0));PUT(W(AUDIO+0x53e8));PUT(W(AUDIO+0x53f8));
        PUT(W(REC+0x50));PUT(W(REC+0x1e94));PUT(W(AUDIO+0x53e4));PUT(W(AUDIO+0x53f4));PUT(LD(&s->epoch));
    } else if(p[5]==4){
        Spans *s=&ring_spans;PUT(LD(&s->epoch));const uint32_t *fields=&s->requests;
        for(uint32_t i=0;i<8;i++)PUT(LD(fields+i));PUT(LD(&s->epoch));
    } else {
        Guards *s=&ring_guards;PUT(LD(&s->epoch));const uint32_t *fields=&s->samples;
        for(uint32_t i=0;i<17;i++)PUT(LD(fields+i));PUT(LD(&s->epoch));
    }
    PUT(TICKS);reply[7+5*n]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,8+5*n,2);
    return 1;
#undef PUT
}
