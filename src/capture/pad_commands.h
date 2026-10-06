#ifndef L6_PAD_COMMANDS_H
#define L6_PAD_COMMANDS_H
#include <stdint.h>
#define PC_CAPACITY 8
enum {PC_OK=0,PC_BUSY=1,PC_INVALID=2};
enum {PC_IDLE=0,PC_RUNNING=1,PC_RETURNED=2};
/* Scalar arguments of original 3f4d8 (source 0) or 408b0 (source 1).
 * Preserve the whole command: do not reclassify a toggle as a start or discard
 * a release. Some source-1 commands also enter recorder control. These are raw
 * arguments, NOT a snapshot of pad mode, assignment or Record state: stock code
 * reads that state at replay. The dispatcher must order conflicting state
 * changes too, or explicitly define replay-time semantics before binding. */
typedef struct {uint32_t source,pad,argument,event;} PadCommand;
typedef struct {
    uint32_t main_task,handoff_task;
    void (*execute)(const PadCommand *);
} PadCommandPort;
typedef struct {
    PadCommandPort port;
    uint32_t latch,closed,phase,head,count;
    PadCommand queue[PC_CAPACITY];
} PadCommands;
/* Research/test-fixture component only, excluded from the normal handoff build;
 * no stock void-returning handler is replaced.
 * Main calls submit/poll. One serialized handoff worker calls try_hold/release;
 * no stale asynchronous release or overlapping handoff is permitted.
 * OK submit owns a value copy; BUSY/INVALID consumes NOTHING. Integration must
 * retain/backpressure the upstream event on rejection, never drop it or tell a
 * stock caller that BUSY means success. The dispatcher wake/retry is unbound.
 * poll executes one command on Main outside the metadata latch. execute is
 * synchronous and must not retain its pointer to the temporary command copy.
 * New commands must always submit, including while open, to preserve FIFO.
 * PC_BUSY from poll may mean execution finished but bookkeeping needs retry;
 * retry poll, never resubmit an already accepted command. A returning
 * stock handler is not proof that its asynchronous descendants have finished.
 * try_hold succeeds only with an empty queue and no executing/returned command.
 * Accepted pad commands, including stops, therefore execute before hold; their
 * descendants need a separate drain. This is only command admission, NOT a
 * renderer/file/recorder/card fence. Unrelated Main events must
 * keep running. While held, new complete pad commands queue in FIFO order.
 * release is I/O-free and never executes callbacks on the handoff worker.
 * Storage/port lifetime is permanent; init is cold before all callers. */
int32_t pc_init(PadCommands *,const PadCommandPort *);
int32_t pc_submit(PadCommands *,const PadCommand *);
int32_t pc_poll(PadCommands *);
int32_t pc_try_hold(PadCommands *);
int32_t pc_release(PadCommands *);
/* Unpatched stock entries; NOT a validated dispatcher binding. Stock handlers
 * also remove pending UI events from the original queue; diverted commands are
 * invisible to that removal. See verify_pad_dispatch.py's duplicate-press
 * counterexample. Caller-level admission alone does not preserve this behavior. */
void pc_stock_execute(const PadCommand *);
#endif
