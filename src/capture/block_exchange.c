/* Offline candidate: one audio producer, one worker. No filesystem calls.
 * Init/storage reclamation require external quiescence. Atomics assume coherent
 * normal RAM; actual placement/cache properties and hook coverage are unbound.
 */
#include <stdint.h>
#include <stddef.h>
#include "exchange.h"
#include "retention.h"
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
enum { FREE,WRITING,READY,READING };
enum { OK=0,WAIT=11,INVALID=12,MISSING=17,TIMELINE=18 };
KEEP const uint32_t exchange_layout[]={sizeof(Exchange),sizeof(Slot),offsetof(Slot,left),
    offsetof(Slot,right),offsetof(Exchange,version),offsetof(Exchange,pub_cursor),
    offsetof(Exchange,dropped)};
static int mode(const Observation *o) {
    return o->callback==0x2022a791u && o->copy_state!=2 &&
           o->capacity>=64 && o->capacity<=0x1fffffffu &&
           o->capacity%64==0 && o->cursor<o->capacity && o->cursor%64==0;
}
static uint32_t fault(Exchange *p) {
    p->fault=TIMELINE;ST(&p->pub_fault,TIMELINE);
    if(p->pending && p->owns)ST(&exchange_slot(p,(uint32_t)(p->next>>6))->state,FREE);
    p->pending=p->owns=0;return TIMELINE;
}
KEEP uint32_t exchange_prepare(Exchange *p,Slot *slots,uint32_t count) {
    /* A tagged count is invalid for this legacy API; invalidate preparation
     * as for every other bad count, without interpreting slots as metadata. */
    return exchange_prepare_storage(p,slots,(count&HISTORY_EXTERNAL)?0:count);
}
KEEP uint32_t exchange_prepare_storage(Exchange *p,const void *storage,uint32_t count) {
    if(!p)return INVALID;
    p->prepared=0;p->pending=p->owns=0;
    p->fault=p->pub_fault=TIMELINE;
    HistoryStorage h;
    if(hstorage_decode(storage,count,&h) || !hstorage_disjoint(&h,(uint32_t)p,sizeof(*p)))return INVALID;
    /* Copy validated metadata into the exchange; audio never reads the caller's
     * descriptor. Preparation and descriptor replacement require quiescence. */
    p->history=h;
    p->slot_shift=0;
    for(uint32_t n=h.slots_per_segment;n>1;n>>=1)p->slot_shift++;
    p->slots=h.segments[0].slots;p->mask=(count&~HISTORY_EXTERNAL)-1;
    for(uint32_t i=0;i<=p->mask;i++)exchange_slot(p,i)->state=FREE;
    p->prepared=1;return OK;
}
KEEP uint32_t exchange_begin(Exchange *p,const Observation *o) {
    if(!p || !o || p->prepared!=1)return INVALID;
    p->prepared=0;
    if(!mode(o))return fault(p);
    p->capacity=o->capacity;p->expected=o->cursor;
    p->pending=p->owns=p->dropped=p->fault=0;p->next=0;
    p->version=p->pub_lo=p->pub_hi=p->pub_fault=0;p->pub_cursor=o->cursor;
    return OK;
}
/* Legacy initialization-only API. Never call this from the live audio path. */
KEEP uint32_t exchange_init(Exchange *p,Slot *slots,uint32_t count,const Observation *o) {
    uint32_t s=exchange_prepare(p,slots,count);
    return s?s:exchange_begin(p,o);
}
/* Pre-master boundary: stage a private block; never spin or wait for a reader.
 * WAIT means this optional block is dropped, but commit must still be called
 * after the ordinary callback, to keep subsequent labels on the same timeline. */
KEEP uint32_t exchange_stage(Exchange *p,const float *l,const float *r,const Observation *o) {
    if(p->fault)return p->fault;
    if(p->pending || !mode(o) || o->capacity!=p->capacity || o->cursor!=p->expected ||
       p->next>UINT64_MAX-64)return fault(p);
    p->pending=1;p->owns=0;
    Slot *s=exchange_slot(p,(uint32_t)(p->next>>6));
    uint32_t old=LD(&s->state);
    if(old!=FREE && old!=READY){p->dropped++;return WAIT;}
    if(!__atomic_compare_exchange_n(&s->state,&old,WRITING,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
        p->dropped++;return WAIT;
    }
    p->owns=1;s->first=p->next;
    for(uint32_t i=0;i<64;i++){s->left[i]=l[i];s->right[i]=r[i];}
    return OK;
}
/* After stock cursor advancement. Publication has a checked version; no torn
 * 64-bit timestamp is accepted by readers. Version wrap is refused. */
KEEP uint32_t exchange_commit(Exchange *p,const Observation *o) {
    if(p->fault)return p->fault;
    uint32_t next_cursor=p->expected+64;
    if(next_cursor==p->capacity)next_cursor=0;
    uint32_t version=LD(&p->version);
    if(!p->pending || !mode(o) || o->capacity!=p->capacity || o->cursor!=next_cursor ||
       version>=0xfffffffcu)return fault(p);
    ST(&p->version,version+1);
    if(p->owns)ST(&exchange_slot(p,(uint32_t)(p->next>>6))->state,READY);
    p->next+=64;p->expected=next_cursor;p->pending=p->owns=0;
    ST(&p->pub_lo,(uint32_t)p->next);ST(&p->pub_hi,(uint32_t)(p->next>>32));
    ST(&p->pub_cursor,next_cursor);ST(&p->version,version+2);
    return OK;
}
static uint32_t snapshot(const Exchange *p,uint64_t *next,uint32_t *cursor) {
    uint32_t a=LD(&p->version);
    if(a&1)return WAIT;
    uint32_t lo=LD(&p->pub_lo),hi=LD(&p->pub_hi);*cursor=LD(&p->pub_cursor);
    uint32_t b=LD(&p->version);
    if(a!=b || (b&1))return WAIT;
    if(LD(&p->pub_fault))return TIMELINE;
    *next=((uint64_t)hi<<32)|lo;return OK;
}
/* Event must be sampled synchronously at the stock selection/stop hook, not
 * reconstructed later from a saved modulo cursor. A whole missed lap cannot
 * be detected using modulo positions alone. Coverage is a caller obligation. */
KEEP uint32_t exchange_resolve(const Exchange *p,const Event *e,uint64_t *out) {
    uint64_t next;uint32_t current,status=snapshot(p,&next,&current);
    if(status)return status;
    if(!mode(&e->now) || e->now.capacity!=p->capacity || e->selected>=p->capacity)return INVALID;
    if(e->now.cursor!=current)return WAIT;
    uint32_t distance=(current+p->capacity-e->selected)%p->capacity;
    if(distance>next || distance>(p->mask+1)*64)return MISSING;
    *out=next-distance;return OK;
}
KEEP uint32_t exchange_claim(Exchange *p,const uint64_t *first,Slot **out) {
    *out=0;
    uint64_t next;uint32_t cursor,status=snapshot(p,&next,&cursor);
    if(status)return status;
    if(*first%64 || *first>UINT64_MAX-64)return INVALID;
    if(*first+64>next)return WAIT;
    Slot *s=exchange_slot(p,(uint32_t)(*first>>6));
    uint32_t old=READY;
    if(!__atomic_compare_exchange_n(&s->state,&old,READING,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))
        return old==FREE?MISSING:WAIT;
    if(s->first!=*first){ST(&s->state,READY);return MISSING;}
    *out=s;return OK;
}
/* Only the worker owning this exact claim may release it, after all reads. */
KEEP uint32_t exchange_release(Exchange *p,const uint64_t *first) {
    if(*first%64)return INVALID;
    Slot *s=exchange_slot(p,(uint32_t)(*first>>6));
    if(LD(&s->state)!=READING || s->first!=*first)return INVALID;
    ST(&s->state,READY);return OK;
}
