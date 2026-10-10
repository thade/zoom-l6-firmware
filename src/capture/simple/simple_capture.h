#ifndef L6_SIMPLE_CAPTURE_H
#define L6_SIMPLE_CAPTURE_H
/* Pre-compressor stereo capture, simplified design. See
 * docs/research/simple_capture_findings.txt for the contract and evidence.
 *
 * Four participants, each owning distinct fields:
 *   audio     sc_stage/sc_commit at the original DSP tap and commit sites
 *   recorder  sc_admit/sc_stop in the stock recorder task (take start/stop)
 *   Main      sc_main_receive on storage-changing packets
 *   worker    sc_worker_step, the only caller of the filesystem
 * All state is allocated once at startup and kept until reboot. */
#include <stdint.h>
#include <stddef.h>

#define SC_FRAMES 64u
#define SC_MAX_SEGMENTS 8u
#define SC_FIFO 4096u          /* every payload write except the last */
#define SC_WAIT_TICKS 500u     /* Main's bound on waiting for the worker */

typedef struct {float left[SC_FRAMES],right[SC_FRAMES];} ScBlock;
typedef struct {
    ScBlock *segment[SC_MAX_SEGMENTS];
    uint32_t segments,per_segment;   /* both powers of two */
} ScHistory;

enum {SC_IDLE,SC_CAPTURING};
enum {SC_OK=0,SC_REVOKED=1,SC_TIMELINE=2,SC_OVERRUN=3,SC_ORDER=4,SC_IO=5,
      SC_NAME=6,SC_EVENT=7,SC_VERIFY=8,SC_INVALID=12};

typedef struct {
    /* Audio only. */
    uint32_t expected,capacity,staged;
    /* Published by audio: frames committed, the stock ring cursor at that
     * frame, and frames since the epoch began (saturating). A new epoch starts
     * whenever continuity breaks. */
    uint32_t frames,epoch,published_cursor,age,published_capacity;
    /* Recorder task: one take at a time, identified by its take number. */
    uint32_t take,open_take,stop_take,abort_take;
    uint32_t start,stop,take_epoch,take_revoked;
    uint32_t skipped,event_faults;
    /* Main increments revoked; the worker clears file_open once it is done. */
    uint32_t revoked,file_open;
    /* Worker only. */
    uint32_t state,done,cursor,fifo_used,bytes,handle,serial,limit,named;
    uint32_t completed,failed,last_status,polls,task;
    uint32_t mask,shift;
    ScHistory history;
    uint16_t path[40];
    /* Main only, in the padding before header: a wait already timed out for
     * the open file, and the last packet that revoked (category<<16|sub<<8|code). */
    uint32_t main_timed_out,revoke_packet;
    _Alignas(32) uint8_t header[512];
    _Alignas(32) uint8_t fifo[SC_FIFO+SC_FRAMES*8];
} SimpleCapture;

/* Validate history, initialize a zeroed state and publish it to every hook.
 * Call once, before the scheduler runs any hook or the worker. */
uint32_t sc_init(SimpleCapture *,const ScHistory *,uint32_t serial);
void sc_stage(void);
void sc_commit(void);
void sc_admit(void);
void sc_stop(uint32_t selected,uint32_t caller);
int32_t sc_main_receive(uint32_t *packet);
/* 0 idle, 10 more work or waiting for audio, 1 take finished with an error. */
uint32_t sc_worker_step(void);
void sc_worker_entry(void *);
#endif
