#ifndef L6_BACKING_NATIVE_H
#define L6_BACKING_NATIVE_H
#include "backing_handoff.h"
/* Offline v1.10 adapter. Permanent, zero-initialized state. Gate methods have
 * BackingPort semantics and the stricter contract below.
 * Native close interception must be installed before init. No installer here.
 * Failed closes retain their identities; recovery requires external teardown.
 * No automatic retry, rollback, or release after uncertain ownership. */
/* Gate contract (not a recovered implementation):
 * - Called only by the serialized handoff worker, in normal task context with
 *   interrupts and scheduling enabled; no enclosing filesystem operation.
 * - enter OK closes admissions and joins ALL sampler/file/recorder/card users,
 *   including queued descendants. It retains logical admission ownership, NOT
 *   scratch, filesystem or SD locks, critical sections or a suspended task that
 *   the handoff needs. Join waits must allow existing users/driver work to finish.
 *   The binding must also guarantee joined lifetimes for NEW native I/O made
 *   during handoff. A public-read return or released SD token after timeout is
 *   not physical completion evidence; the current adapter may otherwise attempt
 *   rollback while a transfer is unresolved. Such a binding is prohibited.
 *   Stock operation-5 clock stability and command-error reset return also do
 *   not prove cancellation. Join must occur before the lowest driver unwinds
 *   caller/bounce/descriptor lifetimes; public-return quarantine is too late.
 * - enter BUSY/SAFE leaves no reservations or admission changes behind.
 *   Other outcomes retain the gate's diagnostic ownership; no release is tried.
 * - leave is an I/O-free admission commit. OK means release completed. Any
 *   non-OK result MUST leave admissions closed, all prior users joined, and
 *   ownership retained. Check everything fallible BEFORE admitting another task;
 *   after admission becomes visible the only permitted result is OK.
 *   A gate that cannot guarantee this contract must not be bound.
 * - seal joins and checks its own file operations. SAFE means unchanged;
 *   uncertain state/handles must be retained in the gate context.
 * See docs/research/handoff_locks_findings.txt and handoff_dependencies_findings.txt
 * and sd_completion_findings.txt / sd_transfer_probe_findings.txt for evidence
 * and remaining gaps. sd_controller_setup_findings.txt also distinguishes
 * transfer mode from clock configuration and requires stale TC/event draining
 * before DS_ADDR programming. Stock reset callbacks can clear event handles;
 * their zero return does not establish successful recovery. Preserve/recreate
 * completion state and check controller/card recovery before any retry.
 * sd_card_recovery_findings.txt shows stock CMD12 may return success while
 * busy remains; card reinit does not validate prior card/filesystem identity.
 * Neither can authorize buffer release or rollback on its own.
 * sd_checked_recovery_findings.txt checks an emulator-only abort/data-reset/
 * drain sequence, still dependent on MODEL IRQ, kernel, reset-permission and
 * physical/cache/card validity contracts. These are not native gate methods.
 * The compiled SD join probe is an emulator-only fixture,
 * not a device guarantee satisfying this contract. */
typedef struct {
    void *context;
    int32_t (*enter)(void *);
    int32_t (*leave)(void *);
    int32_t (*seal)(void *,const uint16_t *,const uint16_t *);
} BackingGate;
typedef struct {
    BackingGate gate;
    uint32_t held,fault,pad,reads,read_bad;
    uint32_t uncertain_count,uncertain_handles[24];
} BackingNative;
int32_t bn_init(BackingNative *,const BackingGate *,BackingPort *);
int32_t bn_close_hook(uint32_t);
#endif
