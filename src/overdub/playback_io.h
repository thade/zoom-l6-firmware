#ifndef OD_PLAYBACK_IO_H
#define OD_PLAYBACK_IO_H
#include "playback_session.h"
typedef struct {
    OdSession *session;uint32_t main_task,stream_task,queue;
    int32_t (*receive)(uint32_t,uint32_t *);
    int32_t (*start)(uint32_t);
    void (*refill)(uint32_t,uint32_t,uint32_t,uint32_t);
    void (*yield)(void);
} PiBinding;
/* Single cold binding; stable session/port and native handles. Set the session
 * start port to pi_start and the ordinary parent port to pi_parent. Both stream
 * queue endpoints must use ticket transport before hooks are activated. */
int32_t pi_bind(const PiBinding *);
/* Ordinary producer's cold preflight when selecting this parent port. */
int32_t pi_parent_ready(OwnLedger *,const uint32_t ids[8],const uint32_t id_words[8]);
/* Scan producer's single-caller cold preflight against the consuming endpoint. */
int32_t pi_scan_ready(OdSession *,uint32_t queue);
/* Synchronous session start port: wraps the entire stock start/restart, including
 * its seek. Only the bound Main task inside od_session_start may invoke it. */
int32_t pi_start(uint32_t pad);
/* Ordinary producer parent port. No implicit root or global session fallback:
 * Main requires the start wrapper; stream worker requires a claimed refill. */
int32_t pi_parent(uint32_t current_task,uint32_t *parent);
/* Only stream worker receive at 0x80036c70 and refill BL at 0x80036c7c.
 * Retains dequeued packet/claim/completion retries without repeating stock IO. */
int32_t pi_next(uint32_t queue,uint32_t out[4]);
void pi_refill(uint32_t,uint32_t,uint32_t,uint32_t);
#endif
