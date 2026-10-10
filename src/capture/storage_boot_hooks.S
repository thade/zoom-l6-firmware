.syntax unified
.thumb
/* Observers are integer-only (verified from linked code). Preserve GPRs,
 * flags and either incoming stack alignment, including inside USB critical
 * sections. They never wait, allocate or touch a semaphore. */
.macro OBS name,event
.section .text.\name,"axR",%progbits
.global \name
.type \name,%function
.thumb_func
\name:
 push.w {r0-r12,lr}
 mrs r2,apsr
 movs r3,#0
 push {r2,r3}
 mov r4,sp
 bic r5,r4,#7
 mov sp,r5
 movs r0,#\event
 mov r1,r4
 bl storage_boot_observe
 mov sp,r4
 pop {r2,r3}
 msr APSR_nzcvqg,r2
 pop.w {r0-r12,lr}
.endm
.macro JUMP target
 ldr.w pc,.Lresume\@
 .balign 4
.Lresume\@: .word \target
.endm
OBS storage_boot_mount_hook,0
 ldr.w lr,.Lmount_return
 JUMP 0x80006141
.balign 4
.Lmount_return: .word 0x80009ab9
OBS storage_boot_request_hook,1
 strd r5,r4,[r6,#4]
 JUMP 0x8003b87f
OBS storage_boot_consume_hook,2
 ldrd r4,r11,[r8,#4]
 strd r10,r10,[r8,#4]
 JUMP 0x80045d67
OBS storage_boot_ack_hook,3
 ldr.w r0,[r8,#0xc]
 JUMP 0x80046cc9
