#ifndef EXTRA_CAPTURE_H
#define EXTRA_CAPTURE_H
#include <stdint.h>
#define EXTRA_SLOTS 128u
#define EXTRA_FRAMES 64u
typedef struct {
    uint32_t write,read,fault,active,handle,bytes;
    float blocks[EXTRA_SLOTS][EXTRA_FRAMES*2];
    uint32_t hash;
    uint32_t frames[EXTRA_SLOTS];
    uint32_t range_pending;
} Capture;
void extra_init(Capture *,uint32_t);
uint32_t extra_capture(Capture *,const float *,const float *);
uint32_t extra_capture_frames(Capture *,const float *,const float *,uint32_t);
void extra_invalidate_quiesced(Capture *);
uint32_t extra_drain(Capture *);
void extra_stop_quiesced(Capture *);
uint32_t extra_ready(Capture *);
uint32_t extra_hash(uint32_t,const void *,uint32_t);
#endif
