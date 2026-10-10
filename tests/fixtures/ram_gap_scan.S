.syntax unified
.cpu cortex-m7
.thumb
.text

.macro function name
.global \name
.type \name,%function
.thumb_func
\name:
.endm

function gap_arithmetic
  movw r0, #0x5ff0
  movt r0, #0x81f2
  add r0, #16
  strd r1, r2, [r0]
  bx lr

function gap_bulk
  push {lr}
  movw r0, #0x5fe0
  movt r0, #0x81f2
  movs r1, #0
  movs r2, #64
  bl stock_memset
  pop {pc}

function gap_clobber
  movw r0, #0x6000
  movt r0, #0x81f2
  ldr r0, [r4]
  str r1, [r0]
  bx lr

function gap_mutable_load
  movw r0, #0x901c
  movt r0, #0x801f
  ldr r0, [r0]
  str r1, [r0]
  bx lr

function gap_branch
  movw r0, #0x6000
  movt r0, #0x81f2
  b 1f
  str r1, [r0]
1:bx lr

function gap_conditional
  movw r0, #0x6000
  movt r0, #0x81f2
  cmp r1, #0
  it eq
  streq r1, [r0]
  bx lr

function gap_index
  movw r0, #0x5ff0
  movt r0, #0x81f2
  movs r1, #4
  str r2, [r0, r1, lsl #2]
  bx lr

function gap_post_index
  movw r0, #0x5ffc
  movt r0, #0x81f2
  str r1, [r0], #4
  str r1, [r0]
  bx lr

function gap_multiple
  movw r0, #0x5ffc
  movt r0, #0x81f2
  stm r0!, {r1, r2}
  bx lr

function gap_literal
  ldr r0, 1f
  strb r1, [r0]
  bx lr
  .balign 4
1:.word 0x81f26000

function gap_call
  movw r0, #0x6000
  movt r0, #0x81f2
  bl unknown_call
  str r1, [r0]
  bx lr
unknown_call:
  bx lr

function gap_outside
  movw r0, #0x5ffc
  movt r0, #0x81f2
  str r1, [r0]
  bx lr
