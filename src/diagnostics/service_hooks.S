.syntax unified
.thumb
.cpu cortex-m7
.section .text.service_take_original,"ax",%progbits
.global service_take_original
.thumb_func
service_take_original:
    /* Replay the displaced MOV.W before its original tail branch. */
    mov.w r1,#-1
    b.w service_take_resume
.section .text.service_give_original,"ax",%progbits
.global service_give_original
.thumb_func
service_give_original:
    /* Displaced instruction was an unconditional tail branch. */
    b.w service_give_target
