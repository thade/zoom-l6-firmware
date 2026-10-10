/* Independent nonempty LZ4 blocks, with a little-endian size prefix. The default
 * helper is used by isolated loader diagnostic15. The source-reuse variant is
 * selected only by the explicit reuse experiment and diagnostic16; it must
 * never silently replace that helper.
 * No allocation, persistent state, FPU, speculative over-read or wide copies.
 * Format: https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md */
#include <stdint.h>
#define KEEP __attribute__((used,retain))

static int extend(const uint8_t *source,uint32_t bytes,uint32_t *at,
                  uint32_t *length,uint32_t maximum) {
    uint32_t more;
    if(*length>maximum)return 0;
    do {
        if(*at==bytes)return 0;
        more=source[(*at)++];
        if(more>maximum-*length)return 0;
        *length+=more;
    } while(more==255);
    return 1;
}

KEEP uint32_t scatter_lz4_decode(const uint8_t *source,uint32_t bytes,
                                 uint8_t *destination,uint32_t capacity) {
    uint32_t s=(uint32_t)source,d=(uint32_t)destination;
    if(!s || !d || !bytes || !capacity || bytes>UINT32_MAX-s ||
       capacity>UINT32_MAX-d || (s<d+capacity && d<s+bytes))return 12;
    uint32_t at=0,out=0;
    while(at<bytes) {
        uint32_t token=source[at++],length=token>>4;
        if(length==15 && !extend(source,bytes,&at,&length,capacity-out))return 12;
        if(length>bytes-at || length>capacity-out)return 12;
        if(at+length==bytes && (out+length!=capacity || (capacity>=5 && length<5)))return 12;
        while(length--){destination[out++]=source[at++];}
        if(at==bytes)return out==capacity?0:12;
        if(bytes-at<2 || capacity-out<12)return 12;
        uint32_t distance=(uint32_t)source[at]|((uint32_t)source[at+1]<<8);
        at+=2;
        if(!distance || distance>out)return 12;
        length=4+(token&15);
        if((token&15)==15 && !extend(source,bytes,&at,&length,capacity-out))return 12;
        if(length>capacity-out)return 12;
        while(length--){destination[out]=destination[out-distance];out++;}
    }
    return 12; /* A complete block must finish with its literal-only sequence. */
}

KEEP __attribute__((noreturn,noinline)) void scatter_lz4_failed(void) {
    for(;;)__asm__ volatile("nop");
}

KEEP uint32_t scatter_lz4(const uint8_t *source,uint8_t *destination,uint32_t bytes) {
    uint32_t address=(uint32_t)source,d=(uint32_t)destination;
    /* Source envelope is the already-loaded, original DSP source span. The
     * original initializer ignores a helper's status: a bad block must stop
     * before exposing partial code, rather than return an ignored error. */
    if(address<0x800a9408u || address>0x800b6ae0u)scatter_lz4_failed();
    if(bytes>UINT32_MAX-d)scatter_lz4_failed();
#ifdef L6_LZ4_SOURCE_REUSE
    /* Only the exact DSP and the explicitly linked code interval. Code may
     * overwrite consumed DSP input, never this live helper or unread input.
     * The original scatter order must be DSP, code, then globals zeroing. */
    if(d==0x20220000u) {
        if(bytes!=0xd6dcu)scatter_lz4_failed();
    } else if(d!=0x800a9688u || d+bytes>0x800b0a00u || d+bytes>address)
        scatter_lz4_failed();
#else
    if(d<0x800b6ae4u && d+bytes>0x800a9408u)scatter_lz4_failed();
#endif
    uint32_t length=(uint32_t)source[0]|((uint32_t)source[1]<<8)|
                    ((uint32_t)source[2]<<16)|((uint32_t)source[3]<<24);
    if(!length || length>0x800b6ae4u-address-4u ||
       scatter_lz4_decode(source+4,length,destination,bytes))scatter_lz4_failed();
    return 0;
}
