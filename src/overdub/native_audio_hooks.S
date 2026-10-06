.syntax unified
.thumb
.fpu fpv5-d16
/* One state-preserving pair brackets both bound observers. Capture's legacy
 * outer/return replacements must not also be installed at these sites. */
.macro JUMP target
 ldr.w pc,.Lresume\@
 .balign 4
.Lresume\@: .word \target
.endm
.macro OBSERVE name,callee
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
 bl \callee
 mov sp,r4
 vpop {s0-s31}
 pop {r2,r3}
 vmsr fpscr,r3
 msr APSR_nzcvqg,r2
 pop.w {r0-r12,lr}
.endm
OBSERVE na_entry_hook,na_observe_begin
 cbz r0,1f
 JUMP 0x8001078d
1: JUMP 0x8001078f
OBSERVE na_return_hook,na_observe_end
 ldr.w lr,.Lreturn_lr
 JUMP 0x80010151
 .balign 4
.Lreturn_lr: .word 0x80010793
