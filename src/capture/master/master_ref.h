#ifndef L6_MASTER_REF_H
#define L6_MASTER_REF_H
/* The four pads play the last takes' stock masters in place, newest on pad 1.
 * While the chain is on (EFX + PAN hold; off until first switched on),
 * after each ordinary stock take, pad 1 is assigned
 * A:\RECORDER\<take>\MASTER.WAV and each older take moves one pad along; no
 * audio is copied. Each take folder also gets a HISTORY.TXT listing the
 * recordings and sounds it includes. See
 * docs/research/master_reference_findings.txt.
 *
 * Stock reload keeps an assigned path only if the pad's folder lists a file
 * with the same basename, so each pad the chain uses needs a permanent anchor
 * A:\SOUND_PAD\PADn\MASTER.WAV (48 kHz): the chain stops at the first pad
 * without one, and without PAD1's nothing is assigned.
 *
 * Four participants, each owning distinct fields:
 *   recorder  mr_admit/mr_stop in the stock recorder task (take start/stop)
 *   worker    mr_worker_step: waits for the recorder, checks the master,
 *             writes HISTORY.TXT, polls the panel holds (panel.c)
 *   Main      mr_main_receive: assigns the chain, counts storage changes,
 *             toggles the chain and AUX modes and ends their LED show;
 *             mr_play notes pad files played in a take
 *   query     read-only status (trial builds only) */
#include <stdint.h>

#define MR_PATH 80u            /* UTF-16 units, NUL included */
#define MR_DIR 64u             /* take folders must be shorter (63 units at most) */
#define MR_WAIT_TICKS 500u     /* Main's bound on waiting for the worker's file calls */
#define MR_PADS 4u             /* the chain: pad 1 newest ... pad 4 oldest */
#define MR_PLAYED 8u           /* distinct pad files recorded per take */
#define MR_LONG 0x105u         /* a stock saved pad path, NUL included */
#define MR_HISTORY 4096u       /* HISTORY.TXT, written and read back */
#define MR_ENTRIES 100u        /* history lines kept; older ones are left out (OMITTED) */
#define MR_UNWRITTEN 8u        /* recent takes whose history could not be written */

/* Worker results (last_status) and handoff results. */
enum {MR_OK=0,MR_REVOKED=1,MR_MISSING=2,MR_SPLIT=3,MR_IO=4,MR_FORMAT=5,MR_SHORT=6};
/* History results (history_status). */
enum {MR_H_OK=0,MR_H_REVOKED=1,MR_H_CREATE=2,MR_H_WRITE=3,MR_H_CLOSE=4,MR_H_RENAME=5,MR_H_NAME=6,
      MR_H_PENDING=7};   /* PENDING: waiting for the recorder to be idle */
enum {MR_HANDOFF_NONE,MR_HANDOFF_POSTED,MR_HANDOFF_ASSIGNED,MR_HANDOFF_SKIPPED,
      MR_HANDOFF_FAILED,MR_HANDOFF_LOST,MR_HANDOFF_SUPERSEDED};
#define MR_HANDOFF_EVENT 3u            /* Main category no stock dispatcher handles */
#define MR_HANDOFF_MAGIC 0x4c364d52u   /* 'L6MR' */
#define MR_CHAIN_MAGIC 0x4c364348u     /* 'L6CH': toggle the take chain (EFX + PAN hold) */
#define PANEL_RESTORE_MAGIC 0x4c364152u /* 'L6AR': wake Main to end a switch's LED show */

/* A pad file that played during a take: the saved path when it started;
 * valid holds the take's generation once the path is complete. */
typedef struct {uint32_t valid;uint16_t path[MR_LONG];} MrPlayed;

typedef struct {
    /* Recorder task. stop_path and stop_revoked are written before stopped
     * is released. */
    uint32_t admitted,stopped,stock_recording,stop_faults,stop_revoked,admit_revoked;
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
    /* Take history. The recorder opens and closes the take; Main's play hook
     * and the recorder's seed append to played[] while it is open (an index
     * claimed atomically, then valid = generation released). RecStop snapshots
     * it into stop_played before releasing stopped; the worker copies that. */
    uint32_t played_open,played_count,played_overflow,played_gen;
    uint32_t history_pending,history_defer,unwritten_next;
    uint32_t stop_played_count,stop_played_overflow,work_count,work_overflow;
    uint32_t history_written,history_failed,history_status,history_entries,history_truncated,history_omitted;
    MrPlayed played[MR_PLAYED],stop_played[MR_PLAYED],work_played[MR_PLAYED];
    uint16_t unwritten[MR_UNWRITTEN][MR_DIR];   /* worker: take folders, NUL-terminated */
    _Alignas(32) char history[MR_HISTORY];   /* worker: the new file */
    _Alignas(32) char backing[MR_HISTORY];   /* worker: a played take's file */
} MasterRef;

void mr_admit(void);
void mr_play(uint32_t kind,uint32_t pad);
void mr_stop(uint32_t selected,uint32_t caller);
int32_t mr_main_receive(uint32_t *packet);
/* 0 idle, 10 waiting for the recorder to finish. */
uint32_t mr_worker_step(void);
void mr_worker_entry(void *);
/* Panel switches (panel.c), armed after Main first received an event. */
extern uint32_t mr_main_ready;
void panel_poll(void);
int panel_recording(void);
void panel_show(uint32_t sel_a,uint32_t sel_b,uint32_t blink);
void panel_restore(void);
#endif
