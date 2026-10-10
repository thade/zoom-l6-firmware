/* Fixed read-only query for code published over consumed startup input.
 * No capture, allocation, storage operation or mutable query state. */
#include <stdint.h>
extern uint32_t loader_dispatch(const uint8_t *);
static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127u);value>>=7;}
}
uint32_t source_reuse_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x6f || p[5]!=4 || p[6]>127 || p[7]!=0xf7 ||
       *(volatile const uint8_t*)0x80629b60u!=2)return loader_dispatch(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    uint8_t reply[78]={0xf0,0x52,0,0,0x6e,4,p[6]};
    encode(reply+7,1);
    encode(reply+12,((uint32_t (*)(void))0x800a9689u)());
    const volatile uint32_t *zero=(const volatile uint32_t*)0x800b0a00u;
    uint32_t value=0;for(uint32_t i=0;i<4;i++)value|=zero[i];
    encode(reply+17,value);
    encode(reply+22,*(volatile const uint32_t*)0xe000ed14u); /* CCR snapshot. */
    const volatile uint32_t *records=(const volatile uint32_t*)0x800a691cu;
    for(uint32_t i=0;i<8;i++)encode(reply+27+5*i,records[i]);
    encode(reply+67,records[9]); /* Zero destination. */
    encode(reply+72,records[10]); /* Zero length. */
    reply[77]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,sizeof(reply),2);
    return 1;
}
