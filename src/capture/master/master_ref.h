#ifndef L6_MASTER_REF_H
#define L6_MASTER_REF_H
/* The four pads play the last takes' stock masters in place, newest on pad 1.
 * After each ordinary stock take, pad 1 is assigned
 * A:\RECORDER\<take>\MASTER.WAV and each older take moves one pad along; no
 * audio is copied or written. See docs/research/master_reference_findings.txt.
 *
 * Stock reload keeps an assigned path only if the pad's folder lists a file
 * with the same basename, so a permanent anchor A:\SOUND_PAD\PADn\MASTER.WAV
 * (48 kHz) must exist in all four folders; without them nothing is assigned.
 *
 * Four participants, each owning distinct fields:
 *   recorder  mr_admit/mr_stop in the stock recorder task (take start/stop)
 *   worker    mr_worker_step: waits for RecStop to finish, checks the file
 *   Main      mr_main_receive: assigns pad 1, counts storage changes
 *   query     read-only status (trial builds only) */
#include <stdint.h>

#define MR_PATH 80u            /* UTF-16 units, NUL included */
#define MR_DIR 64u             /* take folders must be shorter (63 units at most) */
#define MR_WAIT_TICKS 500u     /* Main's bound on waiting for the worker's probe */
#define MR_PADS 4u             /* the chain: pad 1 newest ... pad 4 oldest */

/* Worker results (last_status) and handoff results. */
enum {MR_OK=0,MR_REVOKED=1,MR_MISSING=2,MR_SPLIT=3,MR_IO=4,MR_FORMAT=5};
enum {MR_HANDOFF_NONE,MR_HANDOFF_POSTED,MR_HANDOFF_ASSIGNED,MR_HANDOFF_SKIPPED,
      MR_HANDOFF_FAILED,MR_HANDOFF_LOST,MR_HANDOFF_SUPERSEDED};
#define MR_HANDOFF_EVENT 3u            /* Main category no stock dispatcher handles */
#define MR_HANDOFF_MAGIC 0x4c364d52u   /* 'L6MR' */

typedef struct {
    /* Recorder task. stop_path and stop_revoked are written before stopped
     * is released. */
    uint32_t admitted,stopped,stock_recording,open_take,stop_faults,stop_revoked,admit_revoked;
    /* Main: storage changes, the last one, and the handled serial. */
    uint32_t revoked,revoke_packet,main_timed_out,handled;
    /* Worker. */
    uint32_t task,polls,seen,pending,file_open,take_revoked;
    uint32_t checked,refused,last_status,master_bytes;
    /* Handoff: the worker posts (state, serial); Main assigns and records result. */
    uint32_t handoff_state,handoff_result,handoff_serial,handoff_posts,handoff_posted_at,handoff_revoked;
    uint32_t chain_mask;             /* Main: pads the last handoff assigned */
    uint16_t stop_path[MR_PATH];     /* recorder: the stopped take's master */
    uint16_t path[MR_PATH];          /* worker: copy being checked */
    uint16_t posted_path[MR_PATH];   /* worker-written before POSTED, Main-read */
    uint16_t next[MR_PADS][MR_PATH];     /* Main: the shifted chain being checked */
    uint16_t assigned[MR_PADS][MR_PATH]; /* Main: kept until the next assignment */
} MasterRef;

void mr_admit(void);
void mr_stop(uint32_t selected,uint32_t caller);
int32_t mr_main_receive(uint32_t *packet);
/* 0 idle, 10 waiting for the recorder to finish. */
uint32_t mr_worker_step(void);
void mr_worker_entry(void *);
#endif
