/* Fixed passive configuration reads only. The reported windows describe
 * controller configuration, not physical chip density or unused RAM. */
#include <stdint.h>
#define W(a) (*(volatile const uint32_t *)(a))
extern uint32_t command_completion_dispatch(const uint8_t *);
static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127u);value>>=7;}
}
uint32_t memory_capacity_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x6f || p[5]!=1 || p[6]>127 || p[7]!=0xf7 ||
       *(volatile const uint8_t*)0x80629b60u!=2)return command_completion_dispatch(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    /* MCR/IOCR, four SDRAM BRs, SDRAMCR0..3, GPR16/17, core TCM/ID
     * and USB_ANALOG silicon revision. No command/status/FIFO registers. */
    static const uint32_t addresses[]={
        0x402f0000u,0x402f0004u,0x402f0010u,0x402f0014u,
        0x402f0018u,0x402f001cu,0x402f0040u,0x402f0044u,
        0x402f0048u,0x402f004cu,0x400ac040u,0x400ac044u,
        0xe000ef94u,0xe000ef90u,0xe000ed00u,0x400d8260u};
    uint32_t values[18]={1,1};
    for(uint32_t i=0;i<16;i++)values[i+2]=W(addresses[i]);
    /* Two agreeing sequential reads are observation consistency only. */
    for(uint32_t i=0;i<16;i++)if(values[i+2]!=W(addresses[i]))values[1]=0;
    uint8_t output[98]={0xf0,0x52,0,0,0x6e,1,p[6]};
    for(uint32_t i=0;i<18;i++)encode(output+7+i*5,values[i]);
    output[97]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(output,sizeof(output),2);
    return 1;
}
