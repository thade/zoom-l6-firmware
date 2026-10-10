/* Passive CPU-visible fingerprints of one fixed candidate interval. No RAM
 * patterns, cache maintenance, allocation, worker or capture. Unchanged digests
 * are not an ownership/alias proof and can miss DMA writes behind cached data. */
#include <stdint.h>
#define W(a) (*(volatile const uint32_t *)(a))
#define GAP_START 0x81f26000u
#define PAGE_BYTES 1024u
#define PAGE_COUNT 872u
#define READ_PERFORMED 1u
#define HASH_AGREES 2u
#define CONFIG_AGREES 4u
#define CONFIG_ACCEPTED 8u
extern uint32_t memory_capacity_dispatch(const uint8_t *);

static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127u);value>>=7;}
}
static uint32_t acceptable(uint32_t mcr,uint32_t br,uint32_t refresh) {
    /* Require the already-observed active CS0 32-MiB decode window. This is
     * configuration evidence only, not detection of fitted physical density. */
    return !(mcr&3u) && (br&0xfffff03fu)==0x8000001bu && (refresh&1u);
}
static void fingerprint(uint32_t address,uint32_t *hash,uint32_t *sum) {
    uint32_t h=2166136261u,s=0;
    for(uint32_t i=0;i<PAGE_BYTES/4u;i++) {
        uint32_t value=W(address+i*4u);
        h=(h^value)*16777619u;s+=value;
    }
    *hash=h;*sum=s;
}
uint32_t ram_activity_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=10 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x6f || p[5]!=2 || p[6]>127 || p[7]>127 || p[8]>127 || p[9]!=0xf7 ||
       *(volatile const uint8_t*)0x80629b60u!=2)return memory_capacity_dispatch(packet);
    uint32_t page=(uint32_t)p[7]+((uint32_t)p[8]<<7);
    if(page>=PAGE_COUNT)return 0;
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));if(ipsr)return 0;
    uint32_t address=GAP_START+page*PAGE_BYTES;
    /* schema,range,page,count,bytes,address,flags,hash0,sum0,hash1,sum1,
     * ticks0,ticks1,MCR0,BR0,refresh0,MCR1,BR1,refresh1. */
    uint32_t values[19]={1,1,page,PAGE_COUNT,PAGE_BYTES,address};
    values[11]=W(0x801f9050u);
    values[13]=W(0x402f0000u);values[14]=W(0x402f0010u);values[15]=W(0x402f004cu);
    if(acceptable(values[13],values[14],values[15])) {
        values[6]=READ_PERFORMED;
        fingerprint(address,values+7,values+8);
        fingerprint(address,values+9,values+10);
        if(values[7]==values[9] && values[8]==values[10])values[6]|=HASH_AGREES;
    }
    values[16]=W(0x402f0000u);values[17]=W(0x402f0010u);values[18]=W(0x402f004cu);
    if(values[13]==values[16] && values[14]==values[17] && values[15]==values[18])values[6]|=CONFIG_AGREES;
    if(acceptable(values[13],values[14],values[15]) && acceptable(values[16],values[17],values[18]))values[6]|=CONFIG_ACCEPTED;
    values[12]=W(0x801f9050u);
    uint8_t output[103]={0xf0,0x52,0,0,0x6e,2,p[6]};
    for(uint32_t i=0;i<19;i++)encode(output+7+i*5,values[i]);
    output[102]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(output,sizeof(output),2);
    return 1;
}
