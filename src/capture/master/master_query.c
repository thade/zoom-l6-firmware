/* Fixed read-only status query for the master-reference hardware trial.
 * Request F0 52 00 00 6F 07 <token> F7 over the Editor port; reply 6E 07.
 * Linked only into trial builds; it changes no state. */
#include "master_ref.h"
#include "../retention.h"
#define W(a) (*(volatile const uint32_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define VALUES 39u
#define AUX_MODE(i) (*(volatile const uint8_t *)(0x80440dc8u+0x30du+(i)))   /* A5 5A = stereo */
extern uint32_t sa_toggles __attribute__((weak)),sa_refused __attribute__((weak));
#ifdef PANEL_DIAG
/* Schema 6 (experiment 37): the panel switch diagnostics replace the AUX gain
 * rows: chain mode, chain toggles and refusals, the ticks when Main first
 * received and the mixer first issued a gain request, the worker's first
 * poll, longest poll interval and polls over 100 ms apart, the ring index,
 * then pd_counts (2 holds x 9) and pd_ring (32). */
#define SCHEMA 6u
#define CHAIN_MODE(i) (*(volatile const uint8_t *)(0x80440dc8u+0x30fu+(i)))
extern uint32_t mr_chain_toggles,mr_chain_refused,mr_first_receive,sa_first_ramp __attribute__((weak));
extern uint32_t pd_counts[2][9],pd_ring[32],pd_ring_next,pd_max_interval,pd_first_poll,pd_slow_polls;
#define AUX_WORDS (9u+18u+32u)
static uint32_t extra(uint32_t i) {
    uint32_t head[9]={CHAIN_MODE(0)|CHAIN_MODE(1)<<8,mr_chain_toggles,mr_chain_refused,mr_first_receive,
                      &sa_first_ramp?sa_first_ramp:0,pd_first_poll,pd_max_interval,pd_slow_polls,pd_ring_next};
    return i<9u?head[i]:i<27u?pd_counts[(i-9u)/9u][(i-9u)%9u]:pd_ring[i-27u];
}
#else
#define SCHEMA 5u
#define AUX_WORDS 20u
#define AUX_GAINS ((volatile const uint32_t *)(0x20010a48u+0x5e84u))   /* AUX1 then AUX2 rows, raw floats */
#endif
#define PAD_WORDS 4u     /* per pad: 16 characters, four 7-bit characters per word */
#define PATH_WORDS (MR_PADS*PAD_WORDS)
#define CONFIG_PATH(p) ((const volatile uint16_t *)(0x80440dc8u+0x798u+(p)*0x20au))
extern MasterRef *mr_state;
extern uint32_t mr_startup_status;
#ifdef MR_STACK_PAINT
extern uint32_t *mr_stack_low,*mr_stack_high;
/* Bytes below the worker's entry frame that have been written at least once. */
static uint32_t stack_used(void) {
    uint32_t *high=LD(&mr_stack_high),*low=mr_stack_low,*p=low;
    if(!high)return 0;
    while(p<high && *p==MR_STACK_PAINT)p++;
    return (uint32_t)high-(uint32_t)p+128u;
}
#else
static uint32_t stack_used(void){return 0;}
#endif
/* Word i of the reply: five 7-bit groups, low first. */
static void encode(uint8_t *reply,uint32_t i,uint32_t v) {
    for(uint32_t j=0;j<5;j++){reply[7+5*i+j]=v&127;v>>=7;}
}
KEEP uint32_t mr_query(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x6f || p[5]!=7 || p[6]>127 || p[7]!=0xf7 ||
       *(volatile const uint8_t*)0x80629b60u!=2)return 0;
    uint32_t ipsr;__asm__ volatile("mrs %0,ipsr":"=r"(ipsr));if(ipsr)return 0;
    const MasterRef *g=LD(&mr_state);
#define F(x) (g?(x):0)
    /* Words are encoded straight into the reply (Main's stack is not measured;
     * the larger diagnostic reply lives in the globals instead). */
#ifdef PANEL_DIAG
    static uint8_t reply[8+5*(VALUES+AUX_WORDS+PATH_WORDS)];
#else
    uint8_t reply[8+5*(VALUES+AUX_WORDS+PATH_WORDS)];
#endif
    uint32_t values[VALUES]={SCHEMA,0x4c4d01,mr_startup_status,F(g->task),
        F(LD(&g->admitted)),F(LD(&g->stopped)),F(LD(&g->stock_recording)),F(g->stop_faults),
        F(LD(&g->revoked)),F(g->revoke_packet),F(LD(&g->file_open)),F(g->polls),
        F(g->checked),F(g->refused),F(g->last_status),F(g->master_bytes),
        F(LD(&g->handoff_state)),F(g->handoff_result),F(g->handoff_serial),F(g->handoff_posts),
        stack_used(),W(0x801f9020u),W(0x801f9024u),W(0x801f9050u),W(0xe000ed14u),
        /* Published bounds, read back from the scatter records that placed them. */
        W(0x800a6930u),W(0x800a6930u)+W(0x800a6934u),W(0x800a6940u),W(0x800a6940u)+W(0x800a6944u),
        W(0x80578ec0u),F(g->chain_mask),
        F(g->history_written),F(g->history_failed),F(g->history_status),F(g->history_entries),F(g->stop_played_count),
        AUX_MODE(0)|AUX_MODE(1)<<8,&sa_toggles?sa_toggles:0xffffffffu,&sa_refused?sa_refused:0xffffffffu};
#undef F
    for(uint32_t i=0;i<VALUES;i++)encode(reply,i,values[i]);
#ifdef PANEL_DIAG
    for(uint32_t i=0;i<AUX_WORDS;i++)encode(reply,VALUES+i,extra(i));
#else
    for(uint32_t i=0;i<AUX_WORDS;i++)encode(reply,VALUES+i,AUX_GAINS[i]);
#endif
    /* Each pad's saved path as the stock loader left it: the take folder of
     * a take master, else '#' and the file name. Non-ASCII ends a name. */
    for(uint32_t p=0;p<MR_PADS;p++) {
        const volatile uint16_t *path=CONFIG_PATH(p);
        uint32_t start=0,end=0,take=1;
        static const char recorder[]="A:\\RECORDER\\",master[]="\\MASTER.WAV";
        for(uint32_t i=0;recorder[i];i++)if(path[i]!=(uint16_t)recorder[i])take=0;
        while(end<0x104u && path[end])end++;
        /* A take exactly as the chain carries it: shorter than MR_PATH, ending \MASTER.WAV. */
        if(end>=MR_PATH || end<sizeof(master)-1)take=0;
        else for(uint32_t i=0;master[i];i++)if(path[end-(sizeof(master)-1)+i]!=(uint16_t)master[i])take=0;
        if(take){start=sizeof(recorder)-1;end=start;while(end<0x104u && path[end] && path[end]!='\\')end++;}
        else for(uint32_t i=0;i<end;i++)if(path[i]=='\\')start=i+1;
        uint32_t out[PAD_WORDS]={0};
        for(uint32_t k=0,i=start;k<PAD_WORDS*4u;k++) {
            uint32_t c=!take && !k?'#':i<end?path[i++]:0;
            if(c>127)break;
            out[k/4u]|=c<<(7u*(k%4u));
            if(!c)break;
        }
        for(uint32_t k=0;k<PAD_WORDS;k++)encode(reply,VALUES+AUX_WORDS+p*PAD_WORDS+k,out[k]);
    }
    reply[0]=0xf0;reply[1]=0x52;reply[2]=reply[3]=0;reply[4]=0x6e;reply[5]=7;reply[6]=p[6];
    reply[sizeof(reply)-1]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,sizeof(reply),2);
    return 1;
}
