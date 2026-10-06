#ifndef EXTRA_EXCHANGE_H
#define EXTRA_EXCHANGE_H
#include <stdint.h>
#define EXCHANGE_MAX_SLOTS 4096u
typedef struct {uint32_t cursor,capacity,callback,copy_state;} Observation;
typedef struct {Observation now;uint32_t selected;} Event;
typedef struct {uint32_t state,pad;uint64_t first;float left[64],right[64];} Slot;
typedef struct {
    Slot *slots;
    uint32_t mask,capacity,expected,pending,owns,dropped,fault;
    uint64_t next;
    uint32_t version,pub_lo,pub_hi,pub_cursor,pub_fault;
    uint32_t prepared;
} Exchange;
/* prepare runs only on a worker with exclusive, quiescent storage ownership.
 * begin consumes that preparation at the audio boundary in constant work.
 * Neither API allocates memory or establishes physical buffer ownership. */
uint32_t exchange_prepare(Exchange*,Slot*,uint32_t);
uint32_t exchange_begin(Exchange*,const Observation*);
uint32_t exchange_stage(Exchange*,const float*,const float*,const Observation*);
uint32_t exchange_commit(Exchange*,const Observation*);
uint32_t exchange_resolve(const Exchange*,const Event*,uint64_t*);
uint32_t exchange_claim(Exchange*,const uint64_t*,Slot**);
uint32_t exchange_release(Exchange*,const uint64_t*);
#endif
