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
/* The stock gain-ramp request 0x80010398 as it was: its displaced prologue,
 * then the rest of it. Called by the stereo AUX filter that replaces it. */
.section .text.sa_ramp_original,"ax",%progbits
.global sa_ramp_original
.type sa_ramp_original,%function
.thumb_func
sa_ramp_original:
 push {r4,lr}
 sub sp,#16
 JUMP 0x8001039d
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
#ifdef AUX_LINK
/* Linked AUX limiter detectors (stereo builds with AUX_LINK). The copied
 * audio code's two AUX output limiters each read their own side; the master
 * pair's reads the louder of left and right. Each AUX detector loop's
 *   vldr s0,[r5]; bl fabsf; vcmp.f32 s0,s16
 * (r5: this side's sample, r7: its index 0-63, s16: the envelope) becomes a
 * call here. In stereo (mode bytes A5 5A and the worker published, as the
 * stereo filter requires) both loops use the louder of the two sides, so
 * they compute the same gain series and the image holds; otherwise this side
 * alone, as stock. AUX 1's limiter runs first and writes its output over its
 * own block before AUX 2's runs, so AUX 1's routine keeps the louder values
 * in sa_louder for AUX 2's. Returns with the FPSCR flags of vcmp s0,s16,
 * which the loop reads with vmrs. Clobbers r0, r1 and s2, which the loops
 * do not keep across the call. */
.macro STEREO_OR skip
 movw r0,#:lower16:mr_state
 movt r0,#:upper16:mr_state
 ldr r0,[r0]
 cbz r0,\skip
 movw r0,#0x10d5             /* CONFIG+0x30d (stock.h AUX_MODE) */
 movt r0,#0x8044
 ldrb r1,[r0]
 cmp r1,#0xa5
 bne \skip
 ldrb r1,[r0,#1]
 cmp r1,#0x5a
 bne \skip
.endm
.section .text.sa_limit_a,"axR",%progbits
.global sa_limit_a
.type sa_limit_a,%function
.thumb_func
sa_limit_a:                  /* AUX 1's loop: AUX 2's block follows at +0x100 */
 vldr s0,[r5]
 vabs.f32 s0,s0
 STEREO_OR 1f
 vldr s2,[r5,#0x100]
 vabs.f32 s2,s2
 vmaxnm.f32 s0,s0,s2
 movw r0,#:lower16:sa_louder
 movt r0,#:upper16:sa_louder
 add.w r0,r0,r7,lsl #2
 vstr s0,[r0]
1:
 vcmp.f32 s0,s16
 bx lr
.section .text.sa_limit_b,"axR",%progbits
.global sa_limit_b
.type sa_limit_b,%function
.thumb_func
sa_limit_b:                  /* AUX 2's loop: the louder values AUX 1's kept */
 vldr s0,[r5]
 vabs.f32 s0,s0
 STEREO_OR 1f
 movw r0,#:lower16:sa_louder
 movt r0,#:upper16:sa_louder
 add.w r0,r0,r7,lsl #2
 vldr s0,[r0]
1:
 vcmp.f32 s0,s16
 bx lr
.section .bss.sa_louder,"aw",%nobits
.global sa_louder
.balign 4
sa_louder: .space 256        /* 64 floats: the louder side per sample of the block */
#endif
