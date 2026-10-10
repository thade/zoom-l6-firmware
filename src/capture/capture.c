/* Offline experiment. Addresses and memory placement are NOT device bindings.
 * One audio producer, one file worker. Init/stop require producer quiescence.
 * Only the worker calls the filesystem. Caller keeps ordinary recording going
 * regardless of the optional capture's return status. No pad assignment here.
 */
#include "capture.h"
#include <stddef.h>
#include "retention.h"
#define SLOTS EXTRA_SLOTS
#define FRAMES 64u
#define BLOCK_BYTES 512u
#define BATCH 8u
#define LIMIT 0x7ffffc00u
#define LOAD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define STORE(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
enum { OK=0, EMPTY=1, INACTIVE=2, FULL=3, IO=4, SIZE=5, RANGE=6 };

KEEP const uint32_t extra_layout[]={sizeof(Capture),offsetof(Capture,blocks),SLOTS,FRAMES,BATCH,LIMIT};
static uint32_t fail(Capture *s,uint32_t reason) {
    uint32_t zero=0;
    __atomic_compare_exchange_n(&s->fault,&zero,reason,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
    STORE(&s->active,0);return LOAD(&s->fault);
}
/* Only before either participant can access this instance, including pending IO. */
KEEP void extra_init(Capture *s,uint32_t handle) {
    s->write=0;s->read=0;s->fault=0;s->bytes=0;s->handle=handle;s->active=1;s->hash=2166136261u;s->range_pending=0;
}
KEEP uint32_t extra_capture(Capture *s,const float *left,const float *right) {
    return extra_capture_frames(s,left,right,FRAMES);
}
KEEP uint32_t extra_capture_frames(Capture *s,const float *left,const float *right,uint32_t frames) {
    uint32_t fault=LOAD(&s->fault);if(fault)return fault;
    if(!LOAD(&s->active))return INACTIVE;
    if(!frames || frames>FRAMES)return fail(s,RANGE);
    uint32_t w=LOAD(&s->write),r=LOAD(&s->read);
    if(w-r>=SLOTS)return fail(s,FULL);
    float *out=s->blocks[w&(SLOTS-1)];
    /* Preserve the software conversion's round-to-nearest, gradual underflow
     * semantics independently of the stock task's FPSCR. Restore its complete
     * status after scaling; this worker never exposes new FP exception flags.
     * Memory barriers keep the sample loads/stores inside this FP scope. */
    uint32_t fpscr;
    __asm__ volatile("vmrs %0, fpscr\n\tvmsr fpscr, %1"
                     :"=&r"(fpscr):"r"(0u):"memory");
    for(uint32_t i=0;i<frames;i++) {
        out[i*2]=left[i]*0x1p-31f;out[i*2+1]=right[i]*0x1p-31f;
    }
    __asm__ volatile("vmsr fpscr, %0"::"r"(fpscr):"memory");
    s->frames[w&(SLOTS-1)]=frames;
    STORE(&s->write,w+1);return OK;
}
KEEP uint32_t extra_drain(Capture *s) {
    uint32_t fault=LOAD(&s->fault);if(fault)return fault;
    uint32_t r=LOAD(&s->read),w=LOAD(&s->write),n=w-r;
    if(!n)return EMPTY;
    if(n>SLOTS)return fail(s,FULL);
    uint32_t slot=r&(SLOTS-1);
    if(n>BATCH)n=BATCH;
    if(n>SLOTS-slot)n=SLOTS-slot;
    uint32_t first=s->frames[slot],bytes,actual=0;
    if(!first || first>FRAMES)return fail(s,RANGE);
    if(first<FRAMES){n=1;bytes=first*8;}
    else {
        /* Full blocks remain contiguous; never write the padding of a short
         * block. It is emitted separately on the next drain call. */
        uint32_t full=1;
        while(full<n && s->frames[slot+full]==FRAMES)full++;
        n=full;bytes=n*BLOCK_BYTES;
    }
    if(s->bytes>LIMIT-bytes)return fail(s,SIZE);
    typedef int32_t (*Write)(uint32_t,const void*,uint32_t,uint32_t*);
    int32_t result=((Write)0x800622b1u)(s->handle,s->blocks[slot],bytes,&actual);
    if(result || actual!=bytes)return fail(s,IO);
    s->hash=extra_hash(s->hash,s->blocks[slot],bytes);
    s->bytes+=bytes;
    STORE(&s->read,r+n);return OK;
}
/* Call only after stopping future capture and waiting for any current producer.
 * A real fence/stop binding has NOT been implemented in this experiment. */
KEEP void extra_stop_quiesced(Capture *s) {STORE(&s->active,0);}
KEEP void extra_invalidate_quiesced(Capture *s) {(void)fail(s,RANGE);}
/* Readiness to FINALIZE, not permission to assign. Checked close/verification
 * and pad reader exclusion must still succeed before assignment is allowed. */
KEEP uint32_t extra_ready(Capture *s) {
    return !LOAD(&s->active) && !LOAD(&s->fault) && !s->range_pending && s->bytes &&
           LOAD(&s->write)==LOAD(&s->read);
}

KEEP uint32_t extra_hash(uint32_t h,const void *p,uint32_t n) {
    const uint8_t *b=p;
    while(n--)h=(h^*b++)*16777619u;
    return h;
}
