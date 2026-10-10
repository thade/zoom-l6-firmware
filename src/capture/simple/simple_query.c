/* Fixed read-only status query for the simplified-capture hardware trials.
 * Request F0 52 00 00 6F 06 <token> F7 over the Editor port; reply 6E 06.
 * Linked only into trial builds; it changes no state. */
#include "simple_capture.h"
#include "../retention.h"
#define W(a) (*(volatile const uint32_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
extern SimpleCapture *sc_state;
extern uint32_t sc_startup_status;
KEEP uint32_t sc_query(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x6f || p[5]!=6 || p[6]>127 || p[7]!=0xf7 ||
       *(volatile const uint8_t*)0x80629b60u!=2)return 0;
    uint32_t ipsr;__asm__ volatile("mrs %0,ipsr":"=r"(ipsr));if(ipsr)return 0;
    const SimpleCapture *g=LD(&sc_state);
#define F(x) (g?(x):0)
    const uint32_t values[]={1,0x4c3901,sc_startup_status,(uint32_t)g,F(g->task),
        F(LD(&g->frames)),F(LD(&g->epoch)),F(g->published_capacity),F(g->age),
        F(LD(&g->take)),F(g->skipped),F(g->event_faults),F(LD(&g->revoked)),
        F(LD(&g->state)),F(LD(&g->file_open)),F(g->completed),F(g->failed),F(g->last_status),
        F(g->polls),W(0x801f9020u),W(0x801f9024u),W(0x801f9050u),W(0xe000ed14u),
        /* Published bounds, read back from the scatter records that placed them. */
        W(0x800a6930u),W(0x800a6930u)+W(0x800a6934u),W(0x800a6940u),W(0x800a6940u)+W(0x800a6944u)};
#undef F
    uint8_t reply[8+5*(sizeof(values)/sizeof(values[0]))];
    reply[0]=0xf0;reply[1]=0x52;reply[2]=reply[3]=0;reply[4]=0x6e;reply[5]=6;reply[6]=p[6];
    for(uint32_t i=0;i<sizeof(values)/sizeof(values[0]);i++) {
        uint32_t v=values[i];
        for(uint32_t j=0;j<5;j++){reply[7+5*i+j]=v&127;v>>=7;}
    }
    reply[sizeof(reply)-1]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,sizeof(reply),2);
    return 1;
}
