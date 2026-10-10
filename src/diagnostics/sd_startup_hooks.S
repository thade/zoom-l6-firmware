.syntax unified
.thumb
.cpu cortex-m7
.section .text.startup_reset_hook,"ax",%progbits
.global startup_reset_hook
.thumb_func
startup_reset_hook:
    push.w {r0-r12,lr}
    mrs r2,apsr
    movs r3,#0
    push {r2,r3}
    mov r4,sp
    bic r5,r4,#7
    mov sp,r5
    bl startup_reset_sample
    mov sp,r4
    pop {r2,r3}
    msr APSR_nzcvqg,r2
    pop.w {r0-r12,lr}
    /* Displaced instructions at 80069c14, before the native initial clocks. */
    ldr r0,[r4,#8]
    orr r0,r0,#0x08000000
    b.w startup_reset_resume
