/* Offline composition of cold startup, heap-owned controls and fixed history.
 * Neither these external spans nor code/globals are device reservations. There
 * is deliberately no storage release: a booted worker only sleeps. */
#include "../../src/capture/native_arena.h"
#include "../../src/capture/retention.h"
#define W(a) (*(volatile uint32_t *)(a))
#define RING 0x81429800u
#define STRIDE 960000u
#define CAPACITY 223104u
#define SEGMENTS 8u
#define PER_SEGMENT 128u

KEEP uint32_t startup_status;
KEEP NativeCaptureArena *startup_arena;
_Static_assert(CAPACITY*sizeof(float)+PER_SEGMENT*sizeof(Slot)==STRIDE,
               "history must occupy exactly each proposed lane tail");

KEEP void startup_observe(uint32_t unused,uint32_t first_result) {
    (void)unused;
    if(!startup_status)startup_status=first_result?2:1;
}
KEEP void startup_register(uint32_t unused,uint32_t selected) {
    (void)unused;(void)selected;
    if(startup_status!=1)return;
    startup_status=3; /* One attempt; retain any allocation until reboot. */
    HistoryStorage h={.segment_count=SEGMENTS,.slots_per_segment=PER_SEGMENT};
    for(uint32_t i=0;i<SEGMENTS;i++) {
        h.segments[i].slots=(Slot *)(RING+i*STRIDE+CAPACITY*sizeof(float));
        h.segments[i].bytes=PER_SEGMENT*sizeof(Slot);
    }
    startup_arena=native_arena_alloc_external(&h,SEGMENTS*PER_SEGMENT,1,W(0x801f8f38u));
    if(!startup_arena)return;
    const WorkerConfig config={4096,1,4,1,25}; /* Experimental, not measured. */
    NativeWorker *w=startup_arena->worker;
    w->last_status=native_worker_register(w,startup_arena->manager,
                                        startup_arena->descriptor,&config,0,1);
#ifdef L6_CAPTURE_STORAGE_LEASE
    if(!w->last_status) {
        w->last_status=storage_lease_bind(&startup_arena->lease,startup_arena->manager);
        if(w->last_status)w->state=W_FAILED;
    }
#endif
    /* No history accesses, file operations, hook activation or release here. */
}
