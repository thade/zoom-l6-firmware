#ifndef EXTRA_CAPTURE_H
#define EXTRA_CAPTURE_H
#include <stdint.h>
#include <stddef.h>
/* Worker staging; after stop/drain its samples double as lifecycle readback
 * scratch under the same serialized worker. The exchange owns audio history. */
#define EXTRA_SLOTS 8u
#define EXTRA_FRAMES 64u
typedef struct {
    uint32_t write,read,fault,active,handle,bytes;
    uint32_t hash,range_pending;
    /* The native sector driver requires 32-byte payload alignment. Keep the
     * metadata prefix full rather than allocating extra alignment padding. */
    _Alignas(32) float blocks[EXTRA_SLOTS][EXTRA_FRAMES*2];
    uint32_t frames[EXTRA_SLOTS];
} Capture;
_Static_assert(offsetof(Capture,blocks)==32,"aligned native I/O payload");
_Static_assert(sizeof(Capture)==4160,"staging footprint must remain unchanged");
void extra_init(Capture *,uint32_t);
uint32_t extra_capture(Capture *,const float *,const float *);
uint32_t extra_capture_frames(Capture *,const float *,const float *,uint32_t);
void extra_invalidate_quiesced(Capture *);
uint32_t extra_drain(Capture *);
void extra_stop_quiesced(Capture *);
uint32_t extra_ready(Capture *);
uint32_t extra_hash(uint32_t,const void *,uint32_t);
#endif
