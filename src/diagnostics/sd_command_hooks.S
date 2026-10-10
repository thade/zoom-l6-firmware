.syntax unified
.thumb
.cpu cortex-m7
.section .text.command_stock,"ax",%progbits
.global command_stock
.thumb_func
command_stock:
    push.w {r4-r11,lr}
    sub sp,#0x2c
    ldrb r4,[r0]
    b.w command_resume
/* Every inline adapter preserves all GPRs and APSR; no FP instructions. */
.macro SAVE
    push.w {r0-r12,lr}
    mrs r2,apsr
    movs r3,#0
    push {r2,r3}
    mov r4,sp
    bic r5,r4,#7
    mov sp,r5
.endm
.macro RESTORE
    mov sp,r4
    pop {r2,r3}
    msr APSR_nzcvqg,r2
    pop.w {r0-r12,lr}
.endm
.section .text.command_direct_read,"ax",%progbits
.global command_direct_read
.thumb_func
command_direct_read:
    SAVE
    mov r0,r11
    ldr r1,=0x80069fec
    bl command_program_sample
    RESTORE
    str r11,[r10,#-0x20]
    b.w direct_read_resume
.section .text.command_bounce_read,"ax",%progbits
.global command_bounce_read
.thumb_func
command_bounce_read:
    SAVE
    mov r0,r7
    ldr r1,=0x8006a180
    bl command_program_sample
    RESTORE
    str r7,[r6]
    lsrs r1,r0,#9
    b.w bounce_read_resume
.section .text.command_direct_write,"ax",%progbits
.global command_direct_write
.thumb_func
command_direct_write:
    SAVE
    /* r4/r5 now carry adapter stack state. Original R4 is saved at +16. */
    ldr r0,[r4,#24]
    ldr r1,=0x8006abf0
    bl command_program_sample
    RESTORE
    str r4,[r8,#-0x20]
    b.w direct_write_resume
.section .text.command_bounce_write,"ax",%progbits
.global command_bounce_write
.thumb_func
command_bounce_write:
    SAVE
    mov r0,r7
    ldr r1,=0x8006adac
    bl command_program_sample
    RESTORE
    str r7,[r6]
    cmp.w r11,#1
    b.w bounce_write_resume
