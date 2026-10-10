/* Fixed read-only identity for the dormant full-payload trial. The sole added
 * query state is a count of worker passes; no release command exists. */
#include "native_arena.h"
#include "storage_boot.h"
#include "retention.h"
#define W(a) (*(volatile const uint32_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
extern NativeCaptureArena *startup_arena;
extern uint32_t startup_status,storage_boot_phase;
extern struct CaptureTransport *ct_active;
extern struct CaptureBridge *emulator_bridge_current;
extern volatile uint32_t sdp_source_port,sdp_chunk_admit_port,sdp_chunk_finish_port,sdp_cache_read_port;
KEEP uint32_t boot_probe_polls;
KEEP uint32_t boot_probe_query(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x6f || p[5]!=5 || p[6]>127 || p[7]!=0xf7 ||
       *(volatile const uint8_t*)0x80629b60u!=2)return 0;
    uint32_t ipsr;__asm__ volatile("mrs %0,ipsr":"=r"(ipsr));if(ipsr)return 0;
    NativeCaptureArena *a=startup_arena;
    NativeWorker *w=a?a->worker:0;
    const uint32_t values[]={1,0x4c3701,startup_status,LD(&storage_boot_phase),
        (uint32_t)a,a?a->requested_bytes:0,w?LD(&w->state):0,w?w->last_status:0,
        w?w->task:0,a?a->manager->state:0,a?LD(&a->lease.control):0,
        W(0x801f9020u),W(0x801f9024u),W(0x801f9050u),W(0xe000ed14u),
        W(0x800a6930u),W(0x800a6930u)+W(0x800a6934u),
        W(0x800a6940u),W(0x800a6940u)+W(0x800a6944u),
        LD(&boot_probe_polls),sdp_source_port|sdp_chunk_admit_port|sdp_chunk_finish_port|sdp_cache_read_port,
        (uint32_t)LD(&ct_active)|(uint32_t)LD(&emulator_bridge_current)};
    uint8_t reply[8+5*(sizeof(values)/sizeof(values[0]))];
    reply[0]=0xf0;reply[1]=0x52;reply[2]=reply[3]=0;
    reply[4]=0x6e;reply[5]=5;reply[6]=p[6];
    for(uint32_t i=0;i<sizeof(values)/sizeof(values[0]);i++) {
        uint32_t v=values[i];
        for(uint32_t j=0;j<5;j++){reply[7+5*i+j]=v&127;v>>=7;}
    }
    reply[sizeof(reply)-1]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,sizeof(reply),2);
    return 1;
}
