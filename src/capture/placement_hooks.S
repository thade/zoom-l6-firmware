/* Candidate inline absolute jumps consume complete instruction spans.
 * These adapters replay the entire span. Offline placement tests only. */
#include "hook_macros.inc"
HOOK placement_tap_hook,1
 movw r0,#0x6220
 ldr r0,[r4,r0]
 cmp r0,#0
 JUMP 0x20226a01
HOOK placement_commit_hook,2
 str.w r0,[r11,r1]
 add sp,#0x120
 vpop {d8-d15}
 JUMP 0x2022a781
