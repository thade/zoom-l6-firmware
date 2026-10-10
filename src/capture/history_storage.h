#ifndef L6_HISTORY_STORAGE_H
#define L6_HISTORY_STORAGE_H
#include <stdint.h>
#define EXCHANGE_MAX_SLOTS 4096u
#define HISTORY_MAX_SEGMENTS 8u
#define HISTORY_EXTERNAL 0x80000000u
typedef struct {uint32_t state,pad;uint64_t first;float left[64],right[64];} Slot;
typedef struct {Slot *slots;uint32_t bytes;} HistorySegment;
typedef struct {
    uint32_t segment_count,slots_per_segment;
    HistorySegment segments[HISTORY_MAX_SEGMENTS];
} HistoryStorage;
/* Descriptor words 6/7 retain the contiguous pointer/count ABI.
 * With HISTORY_EXTERNAL set in word 7, word 6 instead points to an
 * immutable, readable HistoryStorage and the low bits give the total count.
 * Validation checks declared ranges, not physical ownership/cache properties.
 * Each region's full declared bytes remain reserved, including unused padding. */
uint32_t hstorage_decode(const void *storage,uint32_t count,HistoryStorage *out);
uint32_t hstorage_disjoint(const HistoryStorage*,uint32_t address,uint32_t bytes);
#endif
