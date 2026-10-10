/* Heap ownership is obtained from the original allocator, not a guessed gap.
 * Separate offline fixtures supply startup/placement. No storage release is
 * established by this allocator. */
#include "native_arena.h"
#include "capture.h"
#include "exchange.h"
#include "retention.h"
#include <stddef.h>

extern const uint32_t ct_layout[],rr_layout[],bridge_layout[],exchange_layout[],life_layout[];
#define ALLOC ((void *(*)(uint32_t))0x8006de79u)
KEEP const uint32_t native_arena_layout[]={sizeof(NativeCaptureArena),
    offsetof(NativeCaptureArena,allocation),offsetof(NativeCaptureArena,requested_bytes),
    offsetof(NativeCaptureArena,manager),offsetof(NativeCaptureArena,worker),
    offsetof(NativeCaptureArena,descriptor)
#ifdef L6_CAPTURE_STORAGE_LEASE
    ,offsetof(NativeCaptureArena,lease)
#endif
};

static uint32_t align32(uint32_t n){return (n+31u)&~31u;}
static uint32_t sizes(uint32_t slots,uint32_t external,uint32_t out[9]) {
    if(slots<2 || slots>EXCHANGE_MAX_SLOTS || (slots&(slots-1)))return 0;
    out[0]=ct_layout[0];out[1]=rr_layout[0];out[2]=bridge_layout[0];
    out[3]=exchange_layout[0];out[4]=life_layout[0];out[5]=sizeof(Capture);
    out[6]=external?0:slots*sizeof(Slot);out[7]=sizeof(SessionManager);out[8]=sizeof(NativeWorker);
    uint32_t n=align32(sizeof(NativeCaptureArena));
    for(uint32_t i=0;i<9;i++)n+=align32(out[i]);
    return n+31u;
}
KEEP uint32_t native_arena_bytes(uint32_t slots) {
    uint32_t lengths[9];return sizes(slots,0,lengths);
}
KEEP uint32_t native_arena_bytes_external(uint32_t slots) {
    uint32_t lengths[9];return sizes(slots,1,lengths);
}
static void zero(void *p,uint32_t n) {
    uint8_t *b=p;for(uint32_t i=0;i<n;i++)b[i]=0;
}
static NativeCaptureArena *allocate(uint32_t slots,uint32_t session,uint32_t queue,const HistoryStorage *h) {
    uint32_t lengths[9],n=sizes(slots,h!=0,lengths),ipsr;
    __asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(!n || !session || !queue || ipsr)return 0;
    void *raw=ALLOC(n);if(!raw)return 0;
    /* Before any writes to our objects, reject a collision with external
     * history. Failed reservations stay owned until reboot, as on task failure.
     * The caller must exclude native heap storage from external history: the
     * original allocator itself writes its headers before it returns. */
    if((uint32_t)raw>UINT32_MAX-n || (h && !hstorage_disjoint(h,(uint32_t)raw,n)))return 0;
    NativeCaptureArena *a=(void*)align32((uint32_t)raw);
    zero(a,sizeof(*a));a->allocation=raw;a->requested_bytes=n;
    uint32_t cursor=(uint32_t)a+align32(sizeof(*a));
    for(uint32_t i=0;i<7;i++) {
        a->descriptor[i]=cursor;cursor+=align32(lengths[i]);
    }
    a->descriptor[7]=slots;a->descriptor[8]=session;a->descriptor[9]=queue;
    if(h) {
        a->history=*h;
        a->descriptor[6]=(uint32_t)&a->history;a->descriptor[7]|=HISTORY_EXTERNAL;
    }
    a->manager=(void*)cursor;cursor+=align32(lengths[7]);a->worker=(void*)cursor;
    /* manager_boot requires a zero manager and native_worker_register a zero
     * worker. Other objects and history are initialized by the normal manager;
     * large sample payloads are never cleared here. */
    zero(a->manager,sizeof(*a->manager));zero(a->worker,sizeof(*a->worker));
    return a;
}
KEEP NativeCaptureArena *native_arena_alloc(uint32_t slots,uint32_t session,uint32_t queue) {
    return allocate(slots,session,queue,0);
}
KEEP NativeCaptureArena *native_arena_alloc_external(const HistoryStorage *storage,uint32_t slots,
                                                   uint32_t session,uint32_t queue) {
    HistoryStorage h;
    if((slots&HISTORY_EXTERNAL) || hstorage_decode(storage,slots|HISTORY_EXTERNAL,&h))return 0;
    /* v1.10 native heap and allocator control must never double as history.
     * Reject before ALLOC can write its headers, not just after it returns. */
    if(!hstorage_disjoint(&h,0x808e2fddu,0x7d000u) ||
       !hstorage_disjoint(&h,0x801f901cu,0x1cu))return 0;
    return allocate(slots,session,queue,&h);
}
