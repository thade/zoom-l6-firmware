/* Master-reference adapters. Each saves the full integer/FPU context, calls
 * C, then replays the displaced stock instructions and resumes. */
#include "../hook_macros.inc"
/* Stock recorder: streams admitted. */
HOOK mr_admit_hook,0,mr_admit
 movw r0,#0x201
 JUMP 0x8000b15d
/* Stop cursor setter: as HOOK, but passes (r0 = cursor, r1 = caller LR) so
 * only RecStop counts. */
.section .text.mr_stop_hook,"axR",%progbits
.global mr_stop_hook
.type mr_stop_hook,%function
.thumb_func
mr_stop_hook:
 push.w {r0-r12,lr}
 mrs r2,apsr
 vmrs r3,fpscr
 push {r2,r3}
 vpush {s0-s31}
 mov r4,sp
 bic r5,r4,#7
 mov sp,r5
 mov r1,lr
 bl mr_stop
 mov sp,r4
 vpop {s0-s31}
 pop {r2,r3}
 vmsr fpscr,r3
 msr APSR_nzcvqg,r2
 pop.w {r0-r12,lr}
 movw r2,#0xdc8
 JUMP 0x8000691d
/* Stock pad start 0x80018310, after its pad bounds check: C gets (0, pad). */
HOOK mr_play_hook,0,mr_play
 push {r4,lr}
 mov r4,r0
 JUMP 0x8001831b
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
