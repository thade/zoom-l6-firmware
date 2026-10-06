#ifndef OD_NATIVE_AUDIO_H
#define OD_NATIVE_AUDIO_H
#include "control_coordinator.h"
/* Single cold binding to permanent control storage and native AudioProcess.
 * Audio stays running on faults; publication sees audio_fault and cannot pass.
 * This proves callback completion, not persistent pad-reader exclusion. */
uint32_t na_bind(OcCoordinator *,uint32_t task);
void na_begin(uint32_t loaded_callback);
void na_end(void);
/* Optional cold composition, after na_bind and before any observer entry.
 * Permanent bridge functions use integer-only ABI across the separate ELF
 * builds. enable must select strict whole-invocation capture without IO.
 * A failed enable is not installed. No replacement or live detach is allowed. */
uint32_t na_bind_capture(void (*hook)(uint32_t,uint32_t),uint32_t (*enable)(void));
/* Startup path: bind dormant while capture is closed. Main requests arming;
 * the next AudioProcess entry activates, and a successful full return publishes
 * readiness. These do not prove storage readiness or authorize worker release. */
uint32_t na_prepare(OcCoordinator *,uint32_t,void (*)(uint32_t,uint32_t),uint32_t (*)(void));
uint32_t na_arm(void);
uint32_t na_ready(void);
void na_observe_begin(uint32_t loaded_callback);
void na_observe_end(void);
/* Proposed replacements at 0x8001078a and 0x8001078e. Preserve machine state,
 * replay CBZ and post-callback BL; original BLX still executes. No patch writer.
 * With na_bind_capture these are the ONE shared pair for both observers.
 * Do not also install capture's legacy outer/return hooks at these sites. */
void na_entry_hook(void);
void na_return_hook(void);
#endif
