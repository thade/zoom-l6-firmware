.syntax unified
.thumb
.fpu fpv5-d16
/* All live integer/FPU registers and APSR/FPSCR survive the inserted call.
 * C-call stack alignment is restored dynamically; original SP is unchanged.
 * These fixed continuations are for emulator interception only. */
.macro JUMP target
 ldr.w pc,.Lresume\@
 .balign 4
.Lresume\@: .word \target
.endm
.macro HOOK name, kind, callee=bridge_hook
.section .text.\name,"axR",%progbits
.global \name
.type \name,%function
.thumb_func
\name:
 push.w {r0-r12,lr}
 mrs r2,apsr
 vmrs r3,fpscr
 push {r2,r3}
 vpush {s0-s31}
 mov r4,sp
 bic r5,r4,#7
 mov sp,r5
 mov r1,r0
 movs r0,#\kind
 bl \callee
 mov sp,r4
 vpop {s0-s31}
 pop {r2,r3}
 vmsr fpscr,r3
 msr APSR_nzcvqg,r2
 pop.w {r0-r12,lr}
.endm
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
 JUMP 0x80034fc3
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
/* Original stream drain has completed; observe its file error before any
 * finalizer/postprocessing can obscure it. Replay the displaced MOVS. */
HOOK emulator_recorder_drained_hook,0,ct_record_drained
 movs r0,#0
 JUMP 0x8000b78f
.section .text.ct_stock_send,"axR",%progbits
.global ct_stock_send
.type ct_stock_send,%function
.thumb_func
ct_stock_send:
 push {r4,lr}
 JUMP 0x800483fb
/* High-level entries take at most one register argument. The C wrapper creates
 * its own frame; replay only the displaced stock prologue before continuing. */
.section .text.ct_stock_record_request,"axR",%progbits
.global ct_stock_record_request
.type ct_stock_record_request,%function
.thumb_func
ct_stock_record_request:
 push {r4,r5,r6,lr}
 JUMP 0x80034f43
.section .text.ct_stock_stop_request,"axR",%progbits
.global ct_stock_stop_request
.type ct_stock_stop_request,%function
.thumb_func
ct_stock_stop_request:
 push {r4,r5,r7,lr}
 JUMP 0x80034d1b
.section .text.ct_stock_play_request,"axR",%progbits
.global ct_stock_play_request
.type ct_stock_play_request,%function
.thumb_func
ct_stock_play_request:
 push {r4,r5,r6,r7,lr}
 JUMP 0x80034e5b
.section .text.ct_stock_stop_argument,"axR",%progbits
.global ct_stock_stop_argument
.type ct_stock_stop_argument,%function
.thumb_func
ct_stock_stop_argument:
 push {r4,r5,r6,lr}
 JUMP 0x8003503b
.section .text.ct_stock_stop_other,"axR",%progbits
.global ct_stock_stop_other
.type ct_stock_stop_other,%function
.thumb_func
ct_stock_stop_other:
 push {r4,r5,r7,lr}
 JUMP 0x800350db

/* Optional complete callback boundary; replaces legacy outer observation.
 * Original CBZ/BLX and the post-return BL retain stock argument/stack state. */
HOOK emulator_audio_outer_hook,10
 cbz r0,1f
 JUMP 0x8001078d
1: JUMP 0x8001078f
HOOK emulator_audio_return_hook,11
 ldr.w lr,.Laudio_return_lr
 JUMP 0x80010151
 .balign 4
.Laudio_return_lr: .word 0x80010793
