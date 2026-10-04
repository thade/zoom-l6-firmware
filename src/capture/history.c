/* Offline sample-range experiment. ALL calls are externally serialized,
 * including Capture access. This is NOT a lock-free audio/worker protocol.
 * Storage and 64-bit sample labels are supplied by the harness, not stock hooks.
 * One continuous history and at most one selected recording range per instance.
 */
#include "capture.h"
#include <stddef.h>
#define KEEP __attribute__((used,retain))
enum { IDLE,SELECTED,ENDING,COMPLETE,FAILED };
enum { DONE=0,MORE=10,WAIT=11,INVALID=12,MISSING=17,TIMELINE=18 };
typedef struct {
    float *samples;
    Capture *capture;
    uint32_t capacity,head,count,phase,error;
    uint64_t next,start,cursor,end;
} History;
KEEP const uint32_t history_layout[]={sizeof(History),offsetof(History,next),
    offsetof(History,start),offsetof(History,cursor),offsetof(History,end),
    offsetof(History,phase),offsetof(History,error)};
static uint32_t fail(History *h,uint32_t reason) {
    if(!h->error)h->error=reason;
    h->phase=FAILED;
    if(h->capture)extra_invalidate_quiesced(h->capture);
    return h->error;
}
/* Requires unused/quiescent state and non-overlapping valid caller storage. */
KEEP uint32_t history_init(History *h,float *storage,uint32_t capacity,const uint64_t *origin) {
    h->samples=storage;h->capture=0;h->capacity=capacity;
    h->head=h->count=h->error=0;h->phase=IDLE;
    h->next=*origin;h->start=h->cursor=h->end=0;
    if(!storage || capacity<64 || capacity>0x1fffffffu)return fail(h,INVALID);
    return DONE;
}
/* Accept exactly the next 64 frames; never invent silence for absent audio. */
KEEP uint32_t history_push(History *h,const float *left,const float *right,const uint64_t *first) {
    if(h->error)return h->error;
    if(*first!=h->next || h->next>UINT64_MAX-64)return fail(h,TIMELINE);
    uint32_t count=h->count>h->capacity-64?h->capacity:h->count+64;
    uint64_t oldest=h->next+64-count;
    if((h->phase==SELECTED || h->phase==ENDING) &&
       (h->phase!=ENDING || h->cursor<h->end) && oldest>h->cursor)
        return fail(h,MISSING);
    uint32_t slot=h->head;
    for(uint32_t i=0;i<64;i++) {
        h->samples[slot*2]=left[i];h->samples[slot*2+1]=right[i];
        if(++slot==h->capacity)slot=0;
    }
    h->head=slot;h->count=count;h->next+=64;return DONE;
}
/* Bind a freshly started optional file before anything can invalidate history.
 * Failure after binding poisons Capture, preventing lifecycle verification. */
KEEP uint32_t history_begin(History *h,Capture *c,const uint64_t *start) {
    if(h->error)return h->error;
    if(h->phase!=IDLE)return WAIT;
    if(!c->active || c->fault || c->bytes || c->write || c->read || c->range_pending)return INVALID;
    h->capture=c;
    c->range_pending=1;
    if(*start>h->next || *start<h->next-h->count)return fail(h,MISSING);
    h->start=h->cursor=*start;h->phase=SELECTED;return DONE;
}
/* Endpoint is exclusive. A late stop behind already queued samples invalidates
 * the file; this prototype never truncates or silently keeps excess audio. */
KEEP uint32_t history_end(History *h,const uint64_t *end) {
    if(h->error)return h->error;
    if(h->phase!=SELECTED)return WAIT;
    if(*end<=h->start || *end<h->cursor)return fail(h,INVALID);
    h->end=*end;h->phase=ENDING;return DONE;
}
/* Copies at most 64 frames into the existing writer queue; no filesystem IO.
 * While still open, retain partial blocks until more audio or an endpoint. */
KEEP uint32_t history_pump(History *h) {
    if(h->error)return h->error;
    if(h->phase==COMPLETE)return DONE;
    if(h->phase!=SELECTED && h->phase!=ENDING)return WAIT;
    if(h->capture->fault)return fail(h,INVALID);
    if(h->phase==ENDING && h->cursor==h->end) {
        extra_stop_quiesced(h->capture);h->capture->range_pending=0;
        h->capture=0;h->phase=COMPLETE;
        return DONE;
    }
    if(h->cursor<h->next-h->count)return fail(h,MISSING);
    uint64_t limit=h->next;
    if(h->phase==ENDING && h->end<limit)limit=h->end;
    uint64_t available=limit-h->cursor;
    if(!available || (h->phase==SELECTED && available<64))return WAIT;
    uint32_t n=available>64?64:(uint32_t)available;
    uint32_t behind=(uint32_t)(h->next-h->cursor);
    uint32_t slot=(h->head+h->capacity-behind)%h->capacity;
    float left[64],right[64];
    for(uint32_t i=0;i<n;i++) {
        left[i]=h->samples[slot*2];right[i]=h->samples[slot*2+1];
        if(++slot==h->capacity)slot=0;
    }
    if(extra_capture_frames(h->capture,left,right,n))return fail(h,INVALID);
    h->cursor+=n;return MORE;
}
/* Completed range is detached; caller may finalize its file independently.
 * Failures require a separate recovery audit, not automatic reuse. */
KEEP uint32_t history_rearm(History *h) {
    if(h->phase!=COMPLETE || h->error)return WAIT;
    h->phase=IDLE;return DONE;
}
