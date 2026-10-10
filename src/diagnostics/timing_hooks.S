.syntax unified
.thumb
.cpu cortex-m7
/* Integer-only observers; displaced public-file prologues include r11. */
.section .text.timing_read_original,"ax",%progbits
.global timing_read_original
.thumb_func
timing_read_original:
    push.w {r4,r5,r6,r7,r8,r9,r10,r11,lr}
    b.w timing_read_resume
.section .text.timing_write_original,"ax",%progbits
.global timing_write_original
.thumb_func
timing_write_original:
    push.w {r4,r5,r6,r7,r8,r9,r10,r11,lr}
    b.w timing_write_resume
