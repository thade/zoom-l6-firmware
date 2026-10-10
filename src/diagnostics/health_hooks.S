.syntax unified
.thumb
.cpu cortex-m7
#ifndef HEALTH_QUERY_CALLBACK
#define HEALTH_QUERY_CALLBACK health_query
#endif
.section .text.health_parser,"ax",%progbits
.global health_parser
.thumb_func
health_parser:
    push {r0,r1,r2,r3,r4,lr}
    bl HEALTH_QUERY_CALLBACK
    cmp r0,#0
    pop.w {r0,r1,r2,r3,r4,lr}
    bne 1f
    /* Displaced four-byte prologue at 800301f0. */
    push.w {r4,r5,r6,r7,r8,r9,r10,lr}
    b.w health_parser_resume
1:  bx lr
.section .text.health_sd_original,"ax",%progbits
.global health_sd_original
.thumb_func
health_sd_original:
    /* Displaced four-byte prologue at 80068378. */
    push.w {r4,r5,r6,r7,r8,r9,r10,lr}
    b.w health_sd_resume
