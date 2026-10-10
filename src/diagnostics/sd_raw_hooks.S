.syntax unified
.thumb
.cpu cortex-m7
.section .text.raw_irq_hook,"ax",%progbits
.global raw_irq_hook
.thumb_func
raw_irq_hook:
    push.w {r0-r12,lr}
    mrs r2,apsr
    movs r3,#0
    push {r2,r3}
    mov r4,sp
    bic r5,r4,#7
    mov sp,r5
    bl raw_irq_sample
    mov sp,r4
    pop {r2,r3}
    msr APSR_nzcvqg,r2
    pop.w {r0-r12,lr}
    /* Exactly the two instructions displaced before native W1C. C and this
     * adapter are integer-only; the verifier rejects any VFP instructions. */
    lsls r4,r1,#0x17
    and.w r3,r3,r2
    b.w raw_irq_resume
