/* Offline startup jump experiment. Preserve state around added observations,
 * then execute the original call / MOV with its exact continuation. */
#include "../../src/capture/hook_macros.inc"
HOOK startup_init_hook,0,startup_observe
 ldr.w lr,.Linit_resume
 JUMP 0x800745b9
.balign 4
.Linit_resume: .word 0x80067a89
HOOK startup_idle_hook,0,startup_register
 mov.w r0,#0x20
 JUMP 0x800745ed
