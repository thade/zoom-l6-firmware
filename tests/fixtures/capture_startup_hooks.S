/* Offline startup jump experiment. Preserve state around added observations,
 * then execute the original call / MOV with its exact continuation. */
#include "../../src/capture/hook_macros.inc"
#ifdef L6_CAPTURE_COMPOSED_FIXTURE
.global capture_globals_limit
#ifdef L6_SD_RETAIN_ONLY
/* Offline footprint envelope only; this extra global range is NOT owned. */
.set capture_globals_limit,0x80960200
#elif defined(L6_CAPTURE_STORAGE_LEASE)
.set capture_globals_limit,0x809600e8
#else
.set capture_globals_limit,0x809600e4
#endif
#endif
HOOK startup_init_hook,0,startup_observe
 ldr.w lr,.Linit_resume
 JUMP 0x800745b9
.balign 4
.Linit_resume: .word 0x80067a89
HOOK startup_idle_hook,0,startup_register
 mov.w r0,#0x20
 JUMP 0x800745ed
