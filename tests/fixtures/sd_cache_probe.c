/* Offline completion experiment only. This is cache maintenance, NOT a DMA
 * completion detector. The caller must already have joined the actual read
 * and own every affected cache line exclusively. No normal build includes it.
 */
#include <stdint.h>
#define KEEP __attribute__((used,retain))

KEEP int32_t sdp_cache_read_complete(uint32_t address,uint32_t bytes) {
    /* Never discard a neighbour's dirty bytes, or round a wrapping range.
     * Native direct reads use whole aligned sectors. Bounce copies are CPU
     * copies from separate native storage and must not enter this helper. */
    if(!address || !bytes || ((address|bytes)&31u) || address>UINT32_MAX-bytes)return 12;
    __asm__ volatile("dsb sy":::"memory");
    uint32_t end=address+bytes;
    while(address<end) {
        *(volatile uint32_t *)0xe000ef5cu=address; /* SCB.DCIMVAC, invalidate only */
        address+=32u;
    }
    __asm__ volatile("dsb sy\n\tisb sy":::"memory");
    return 0;
}
