#ifndef OD_H
#define OD_H
#include <stdint.h>

/* Offline prototype ABI. Addresses and storage in the ELF are emulator-only.
 * Port functions below are NOT all recovered bindings to the stock firmware. */
#define OD_PATH 261
#define OD_BLOCK 4096
typedef uint16_t Path[OD_PATH];
typedef struct { Path path; uint32_t mode, level, opaque[4]; } Pad;
typedef struct {
    int32_t (*open)(uint32_t *, const uint16_t *, uint32_t, uint32_t);
    int32_t (*read)(uint32_t, void *, uint32_t, uint32_t *);
    int32_t (*write)(uint32_t, const void *, uint32_t, uint32_t *);
    int32_t (*close)(uint32_t);
    int32_t (*info)(uint32_t, uint32_t *);
    int32_t (*count)(uint32_t);
    int32_t (*insert)(uint32_t, const uint16_t *, uint32_t);
    int32_t (*enter)(void); /* Exclude recording, playback, rescans, other jobs. */
    void (*leave)(void);
    int32_t (*qualify)(const uint16_t *); /* Must positively confirm unsplit take. */
    int32_t (*snapshot)(uint32_t, Pad *);
    int32_t (*assign)(uint32_t, const uint16_t *, const Pad *);
    int32_t (*restore)(uint32_t, const Pad *);
    int32_t (*save)(void); /* Proposed grouped save; NOT stock transactional save. */
    int32_t (*checkpoint)(void); /* Cooperative cancellation/yield contract. */
} Port;
typedef struct {
    int32_t target;
    uint32_t master_closed_ok, postprocess_done, parts;
    Path master;
} Job;
enum { OD_OK, OD_SKIPPED, OD_BUSY, OD_INVALID, OD_IO, OD_WAV,
       OD_CATALOGUE, OD_ASSIGN, OD_PERSIST, OD_CANCELLED, OD_FAULT };
typedef struct {
    uint32_t count, serial, busy, fault;
    Path history[4]; /* RAM-only session history of completed source files. */
    Path sources[4], destinations[4];
    Pad before[4], observed;
    uint32_t sizes[4], prepared, inserted, attempted, cleanup_error;
    uint8_t a[OD_BLOCK], b[OD_BLOCK];
} State;
int32_t od_promote(State *, const Port *, const Job *);
int32_t od_publish_completed_paths(State *,const Port *,const uint16_t *const *,uint32_t);
#endif
