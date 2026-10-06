.syntax unified
.thumb
/* Replay the eight overwritten v1.10 public-close entry bytes. The emulator
 * installs an eight-byte literal branch; this file does not patch firmware. */
.global bn_stock_close
.type bn_stock_close,%function
.thumb_func
bn_stock_close:
 push.w {r4,r5,r6,r7,r8,r9,r10,lr}
 sub sp,#0x18
 mov r4,r0
 ldr r12,=0x8005c201
 bx r12
