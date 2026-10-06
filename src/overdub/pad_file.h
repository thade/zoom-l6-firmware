#ifndef OD_PAD_FILE_H
#define OD_PAD_FILE_H
#include "reload_ownership.h"
#define PF_PIN_SLOTS 10 /* two reload producers, eight ordinary operations */
/* Optional cold binding; no participants or existing admissions. Protects only
 * tracked IO against wrapped native load/unload and public close paths.
 * Lower-level close bypasses, card teardown and unbound ordinary readers remain
 * outside. ordinary_io supplies a lifetime core, not native traffic routing. */
int32_t pf_bind(RlCoordinator *,void (*yield)(void));
int32_t pf_ready(RlCoordinator *);
/* Atomic handle snapshot + per-producer reservation. Without binding, preserves
 * legacy snapshot behavior with token zero. Slots 0/1 match reload roles;
 * slots 2..9 are permanently assigned to ordinary operation contexts. */
int32_t pf_pin(RlCoordinator *,uint32_t slot,uint32_t pad,uint32_t out[2]);
int32_t pf_drop(uint32_t slot,uint32_t token);
/* Mutation reservation; native wrappers use current task ID as owner. BUSY has
 * no side effects. End only after the complete original operation returns. */
int32_t pf_change_begin(uint32_t pad,uint32_t owner);
int32_t pf_change_end(uint32_t pad,uint32_t owner);
int32_t pf_load(uint32_t pad,uint32_t path);
int32_t pf_unload(uint32_t pad);
/* Guard public close BEFORE stock filesystem locks. Close attempts revoke the
 * associated pads' read admission until a guarded successful load republishes.
 * Nested closes by a mutation owner do not release its outer reservation. */
int32_t pf_close_begin(uint32_t handle,uint32_t owner,uint32_t *token);
int32_t pf_close_end(uint32_t handle,uint32_t owner,uint32_t token);
int32_t pf_close(uint32_t handle);
#endif
