/* v1.10 callback entry/stock forwarder; no firmware patch writer. */
.syntax unified
.thumb
.global rp_read_entry
.type rp_read_entry,%function
.thumb_func
rp_read_entry:
 mov r3,lr
 b rp_dispatch

/* Replay the first four bytes at 0x80036208, then bypass intercepted entry.
 * The original invalid-pad and null-buffer returns are retained. */
.global rp_stock_read
.type rp_stock_read,%function
.thumb_func
rp_stock_read:
 cmp r0,#3
 bhi 1f
 ldr r12,=0x8003620d
 bx r12
1: bx lr

.global rp_seek_entry
.type rp_seek_entry,%function
.thumb_func
rp_seek_entry:
 b rp_seek_dispatch

/* Replay CMP/IT/BXHI at 0x80036250..54, then bypass entry interception. */
.global rp_stock_seek
.type rp_stock_seek,%function
.thumb_func
rp_stock_seek:
 cmp r0,#3
 bhi 2f
 ldr r12,=0x80036257
 bx r12
2: bx lr
