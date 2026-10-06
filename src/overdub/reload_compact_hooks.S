/* Emulator-only forwarders for verified v1.10 prologues. No patch writer. */
.syntax unified
.thumb
.macro FN name
.global \name
.type \name,%function
.thumb_func
\name:
.endm
FN rc_stock_send
 push {r4,lr}
 ldr r12,=0x800483fb
 bx r12
FN rc_stock_receive
 push {r4,lr}
 ldr r12,=0x800483ab
 bx r12
FN rc_stock_event
 push.w {r4,r5,r6,r7,r8,r9,r10,lr}
 ldr r12,=0x8006e4bd
 bx r12
FN rc_stock_ui
 push {r4,lr}
 ldr r12,=0x8002d56b
 bx r12
FN rc_stock_filter
 cmp r0,#0
 beq 1f
 push.w {r4,r5,r6,r7,r8,r9,r10,r11,lr}
 ldr r12,=0x8001fd13
 bx r12
1: bx lr
FN rc_stock_clear
 push {r4,r5,r6,r7,lr}
 ldr r12,=0x8002043b
 bx r12
FN rc_stock_delete
 push.w {r4,r5,r6,r7,r8,r9,r10,r11,lr}
 ldr r12,=0x8002054d
 bx r12
/* These two stock subranges need emulator return-boundary redirection at
 * 0x8002c4a2 and 0x8002c4b2. They are not standalone stock subroutines. */
FN rc_mode5_prefix
 push {r4,lr}
 ldr r12,=0x8002c481
 bx r12
FN rc_mode5_suffix
 push {r4,lr}
 ldr r12,=0x8002c4a7
 bx r12
FN rc_mode5_range_return
 pop {r4,pc}
/* Mode-5 entry replacement, not an installed branch. Preserve Main's registers
 * and original stack; yield between bounded drain polls. The calling scheduler
 * must progress worker/verification tasks. Faults stay parked, never resume. */
FN rc_mode5_entry
 push.w {r4,r5,r6,r7,r8,r9,r10,r11,lr}
 sub sp,#4
2:
 bl rc_mode5_poll
 cmp r0,#0
 beq 3f
 bl rc_pause
 b 2b
3:
 add sp,#4
 pop.w {r4,r5,r6,r7,r8,r9,r10,r11,lr}
 ldr r12,=0x8002c363
 bx r12
/* Resume c288 only AFTER a checked, attributed USB stop and descendant join.
 * Recreate its original saved-register frame and r4=1 (card-remount branch). */
FN us_stock_remount
 push {r4,lr}
 movs r4,#1
 ldr r12,=0x8000c291
 bx r12
