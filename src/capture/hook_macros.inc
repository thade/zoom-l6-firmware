/* Shared save/restore convention for offline hook experiments. */
.syntax unified
.thumb
.fpu fpv5-d16
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
