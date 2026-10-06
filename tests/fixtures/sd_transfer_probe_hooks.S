.syntax unified
.thumb
.fpu fpv5-d16
/* Emulator trampolines only; no installer or firmware image. */
.macro JUMP target
 ldr.w pc,.Lresume\@
 .balign 4
.Lresume\@: .word \target
.endm
.macro STOCK name,first,second
.section .text.\name,"axR",%progbits
.global \name
.type \name,%function
.thumb_func
\name:
 push.w \first
 sub sp,\second
.endm
STOCK sdp_stock_read,"{r4,r5,r6,r7,r8,lr}",#0x20
 movw r2,#0x8e44
 JUMP 0x80068dbb
STOCK sdp_stock_write,"{r4,r5,r6,r7,r8,r9,r10,r11,lr}",#0x24
 movw r2,#0x8e44
 JUMP 0x80068e4b
STOCK sdp_stock_command,"{r4,r5,r6,r7,r8,r9,r10,r11,lr}",#0x2c
 ldrb r4,[r0]
 JUMP 0x8006a351
STOCK sdp_stock_data_read,"{r4,r5,r6,lr}",#0x20
 movw r6,#0x42b4
 JUMP 0x8006b1e9
STOCK sdp_stock_data_write,"{r4,r5,r6,lr}",#0x20
 movw r6,#0x42b4
 JUMP 0x8006b251

.section .text.sdp_irq_hook,"axR",%progbits
.global sdp_irq_hook
.type sdp_irq_hook,%function
.thumb_func
sdp_irq_hook:
 push.w {r0-r12,lr}
 mrs r2,apsr
 vmrs r3,fpscr
 push {r2,r3}
 vpush {s0-s31}
 mov r4,sp
 bic r5,r4,#7
 mov sp,r5
 bl sdp_irq_sample
 mov sp,r4
 vpop {s0-s31}
 pop {r2,r3}
 vmsr fpscr,r3
 msr APSR_nzcvqg,r2
 pop.w {r0-r12,lr}
 /* Replay all twelve overwritten bytes, including the W1C write/branch. */
 lsls r4,r1,#0x17
 and.w r3,r3,r2
 str.w r3,[lr]
 bpl 1f
 JUMP 0x8006eac3
1: JUMP 0x8006eacb
