/* All live integer/FPU registers and APSR/FPSCR survive the inserted call.
 * C-call stack alignment is restored dynamically; original SP is unchanged.
 * These fixed continuations are for emulator interception only. */
#include "hook_macros.inc"
#ifndef L6_CAPTURE_STARTUP_FIXTURE
/* Historical interceptions are unnecessary in the startup placement fixture,
 * which uses whole callback entry/return and the two absolute RAM adapters. */
HOOK emulator_outer_hook,0
 cbz r0,1f
 JUMP 0x8001078d
1: JUMP 0x8001078f
HOOK emulator_tap_hook,1
 movw r0,#0x6220
 JUMP 0x202269fd
HOOK emulator_commit_hook,2
 str.w r0,[r11,r1]
 JUMP 0x2022a77b
#endif
HOOK emulator_start_hook,3
 movw r2,#0xdc8
 JUMP 0x8000690d
HOOK emulator_stop_hook,4
 movw r2,#0xdc8
 JUMP 0x8000691d
HOOK emulator_admit_hook,5
 movw r0,#0x201
 JUMP 0x8000b15d
HOOK emulator_reject_hook,6
 movs r0,#6
#ifdef L6_CAPTURE_ENCODED_HOOKS
 pop.w {r4,r5,r6,lr}
 JUMP 0x80034fc7
#else
 JUMP 0x80034fc3
#endif
#ifndef L6_CAPTURE_STARTUP_FIXTURE
HOOK emulator_accept_start_hook,7
 JUMP 0x8004b6d9
HOOK emulator_submit_stop_hook,8
 push {r4,lr}
 JUMP 0x8004b71b
HOOK emulator_start_sent_hook,9
 ldr r0,[r4]
 JUMP 0x8004b70b
HOOK emulator_stop_sent_hook,9
 ldr r0,[r4]
 JUMP 0x8004b74d
#endif
/* Original stream drain has completed; observe its file error before any
 * finalizer/postprocessing can obscure it. Replay the displaced MOVS. */
HOOK emulator_recorder_drained_hook,0,ct_record_drained
 movs r0,#0
#ifdef L6_CAPTURE_ENCODED_HOOKS
 ldr.w lr,.Ldrain_return_lr
 JUMP 0x80037e99
 .balign 4
.Ldrain_return_lr: .word 0x8000b793
#else
 JUMP 0x8000b78f
#endif
.section .text.ct_stock_send,"axR",%progbits
.global ct_stock_send
.type ct_stock_send,%function
.thumb_func
ct_stock_send:
 push {r4,lr}
#ifdef L6_CAPTURE_ENCODED_HOOKS
 mov.w r2,#-1
 /* Resume at the untouched MOVS r3,#0 that selects ordinary FIFO sending. */
 JUMP 0x800483ff
#else
 JUMP 0x800483fb
#endif
/* High-level entries take at most one register argument. The C wrapper creates
 * its own frame; replay only the displaced stock prologue before continuing. */
.section .text.ct_stock_record_request,"axR",%progbits
.global ct_stock_record_request
.type ct_stock_record_request,%function
.thumb_func
ct_stock_record_request:
 push {r4,r5,r6,lr}
#ifdef L6_CAPTURE_ENCODED_HOOKS
 mov r4,r0
 JUMP 0x80034f45
#else
 JUMP 0x80034f43
#endif
.section .text.ct_stock_stop_request,"axR",%progbits
.global ct_stock_stop_request
.type ct_stock_stop_request,%function
.thumb_func
ct_stock_stop_request:
 push {r4,r5,r7,lr}
#ifdef L6_CAPTURE_ENCODED_HOOKS
 sub sp,#0x20
 JUMP 0x80034d1d
#else
 JUMP 0x80034d1b
#endif
.section .text.ct_stock_play_request,"axR",%progbits
.global ct_stock_play_request
.type ct_stock_play_request,%function
.thumb_func
ct_stock_play_request:
 push {r4,r5,r6,r7,lr}
#ifdef L6_CAPTURE_ENCODED_HOOKS
 sub sp,#0x24
 JUMP 0x80034e5d
#else
 JUMP 0x80034e5b
#endif
.section .text.ct_stock_stop_argument,"axR",%progbits
.global ct_stock_stop_argument
.type ct_stock_stop_argument,%function
.thumb_func
ct_stock_stop_argument:
 push {r4,r5,r6,lr}
#ifdef L6_CAPTURE_ENCODED_HOOKS
 sub sp,#0x20
 JUMP 0x8003503d
#else
 JUMP 0x8003503b
#endif
.section .text.ct_stock_stop_other,"axR",%progbits
.global ct_stock_stop_other
.type ct_stock_stop_other,%function
.thumb_func
ct_stock_stop_other:
 push {r4,r5,r7,lr}
#ifdef L6_CAPTURE_ENCODED_HOOKS
 sub sp,#0x20
 JUMP 0x800350dd
#else
 JUMP 0x800350db
#endif

/* Optional complete callback boundary; replaces legacy outer observation.
 * Original CBZ/BLX and the post-return BL retain stock argument/stack state.
 * Capture-only tests use these. With na_bind_capture, install only the shared
 * na_entry_hook/na_return_hook here; retain the tap/commit hooks above. */
HOOK emulator_audio_outer_hook,10
 cbz r0,1f
#ifdef L6_CAPTURE_ENCODED_HOOKS
 ldr.w lr,.Laudio_callback_lr
 bx r0
 .balign 4
.Laudio_callback_lr: .word 0x8001078f
#else
 JUMP 0x8001078d
#endif
1: JUMP 0x8001078f
HOOK emulator_audio_return_hook,11
 ldr.w lr,.Laudio_return_lr
 JUMP 0x80010151
 .balign 4
.Laudio_return_lr: .word 0x80010793
