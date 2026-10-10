/* Offline only. The completion provider must join the actual chunk and pin
 * its original span/cache lines; a software ticket or raw TC is insufficient.
 * Prior physical/source exclusion before DS_ADDR is a separate precondition. */
#ifndef L6_SD_CHUNK_PROBE_H
#define L6_SD_CHUNK_PROBE_H
#include <stdint.h>
typedef struct {
    uint32_t active,code,address,bytes,raw,task,completed,checks;
} SdChunkProbe;
extern volatile SdChunkProbe sdp_chunk_state;
/* Zero preserves existing experiments. An exact MODEL result1 means joined;
 * every other result retains the native data-wait frame and unit token. */
extern volatile uint32_t sdp_chunk_finish_port;
#endif
