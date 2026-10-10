#include "history_storage.h"
static int power2(uint32_t n){return n && !(n&(n-1));}
static int range(uint32_t a,uint32_t n){return a && n && a<=UINT32_MAX-n;}
static int overlap(uint32_t a,uint32_t n,uint32_t b,uint32_t k){return a<b+k && b<a+n;}
uint32_t hstorage_disjoint(const HistoryStorage *h,uint32_t a,uint32_t n) {
    if(!range(a,n))return 0;
    for(uint32_t i=0;i<h->segment_count;i++)
        if(overlap(a,n,(uint32_t)h->segments[i].slots,h->segments[i].bytes))return 0;
    return 1;
}
uint32_t hstorage_decode(const void *storage,uint32_t tagged,HistoryStorage *out) {
    uint32_t count=tagged&~HISTORY_EXTERNAL,a=(uint32_t)storage;
    if(!out || count<2 || count>EXCHANGE_MAX_SLOTS || !power2(count))return 12;
    if(tagged&HISTORY_EXTERNAL) {
        if((a&3) || !range(a,sizeof(*out)))return 12;
        const HistoryStorage *in=storage;
        /* Caller owns readable, stable metadata for the duration of this copy. */
        *out=*in;
        /* Count and segment_count are powers of two, so this equality also
         * establishes a nonzero power-of-two per-segment count. */
        if(!power2(out->segment_count) || out->segment_count>HISTORY_MAX_SEGMENTS || out->segment_count>count ||
           out->slots_per_segment!=count/out->segment_count)return 12;
    } else {
        out->segment_count=1;out->slots_per_segment=count;
        for(uint32_t i=0;i<HISTORY_MAX_SEGMENTS;i++) {
            out->segments[i].slots=i?0:(Slot*)storage;out->segments[i].bytes=i?0:count*sizeof(Slot);
        }
    }
    for(uint32_t i=0;i<HISTORY_MAX_SEGMENTS;i++) {
        uint32_t base=(uint32_t)out->segments[i].slots,n=out->segments[i].bytes;
        if(i>=out->segment_count){if(base || n)return 12;continue;}
        if((base&7) || n<out->slots_per_segment*sizeof(Slot) || !range(base,n))return 12;
        for(uint32_t j=0;j<i;j++)
            if(overlap(base,n,(uint32_t)out->segments[j].slots,out->segments[j].bytes))return 12;
    }
    if((tagged&HISTORY_EXTERNAL) && !hstorage_disjoint(out,a,sizeof(*out)))return 12;
    return 0;
}
