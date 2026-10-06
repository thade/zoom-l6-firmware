.syntax unified
.thumb
/* Emulator forwarders for v1.10; no patch installation. */
.global pf_stock_load
.type pf_stock_load,%function
.thumb_func
pf_stock_load:
 push {r4,r5,r6,r7,lr}
 ldr r12,=0x800092a3
 bx r12
.global pf_stock_unload
.type pf_stock_unload,%function
.thumb_func
pf_stock_unload:
 push {r4,lr}
 ldr r12,=0x800096fb
 bx r12
.global pf_stock_close
.type pf_stock_close,%function
.thumb_func
pf_stock_close:
 push.w {r4,r5,r6,r7,r8,r9,r10,lr}
 ldr r12,=0x8005c1fd
 bx r12
