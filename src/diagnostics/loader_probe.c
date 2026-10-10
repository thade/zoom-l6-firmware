/* Read-only identity for the isolated startup-loader trial. The application
 * scatter record is fixed after boot. This does not inspect installed flash,
 * grant RAM ownership, create a worker or enable capture. */
#include <stdint.h>
extern uint32_t startup_dispatch(const uint8_t *);
static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127u);value>>=7;}
}
uint32_t loader_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x6f || p[5]!=3 || p[6]>127 || p[7]!=0xf7 ||
       *(volatile const uint8_t*)0x80629b60u!=2)return startup_dispatch(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    uint8_t reply[33]={0xf0,0x52,0,0,0x6e,3,p[6]};
    encode(reply+7,1);
    const volatile uint32_t *record=(const volatile uint32_t*)0x800a691cu;
    for(uint32_t i=0;i<4;i++)encode(reply+12+5*i,record[i]);
    reply[32]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,sizeof(reply),2);
    return 1;
}
