/* Simplified capture adapters. Each saves the full integer/FPU context, calls
 * C, then replays the displaced stock instructions and resumes. */
#include "../hook_macros.inc"
/* DSP tap at the pre-master mix and commit after the stock cursor advance. */
HOOK placement_tap_hook,0,sc_stage
 movw r0,#0x6220
 ldr r0,[r4,r0]
 cmp r0,#0
 JUMP 0x20226a01
HOOK placement_commit_hook,0,sc_commit
 str.w r0,[r11,r1]
 add sp,#0x120
 vpop {d8-d15}
 JUMP 0x2022a781
/* Stock recorder: streams admitted, and the stop cursor setter (r0=cursor). */
HOOK sc_admit_hook,0,sc_admit
 movw r0,#0x201
 JUMP 0x8000b15d
/* As HOOK, but passes (r0 = cursor, r1 = caller LR) so only RecStop counts. */
.section .text.sc_stop_hook,"axR",%progbits
.global sc_stop_hook
.type sc_stop_hook,%function
.thumb_func
sc_stop_hook:
 push.w {r0-r12,lr}
 mrs r2,apsr
 vmrs r3,fpscr
 push {r2,r3}
 vpush {s0-s31}
 mov r4,sp
 bic r5,r4,#7
 mov sp,r5
 mov r1,lr
 bl sc_stop
 mov sp,r4
 vpop {s0-s31}
 pop {r2,r3}
 vmsr fpscr,r3
 msr APSR_nzcvqg,r2
 pop.w {r0-r12,lr}
 movw r2,#0xdc8
 JUMP 0x8000691d
/* Startup: remember the first initialization result, then register after
 * the stock idle task exists. */
HOOK startup_init_hook,0,startup_observe
 ldr.w lr,.Linit_resume
 JUMP 0x800745b9
.balign 4
.Linit_resume: .word 0x80067a89
HOOK startup_idle_hook,0,startup_register
 mov.w r0,#0x20
 JUMP 0x800745ed
