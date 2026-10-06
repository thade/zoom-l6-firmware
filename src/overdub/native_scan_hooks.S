/* v1.10 original scan publication boundary; emulator hook, no patch writer. */
.syntax unified
.thumb
.global ns_publish_entry
.type ns_publish_entry,%function
.thumb_func
ns_publish_entry:
 push.w {r0-r3,r12,lr}
 mov r1,r2
 mov r0,r5
 mov r2,r9
 ldr r3,[sp,#28]
 bl ns_publish
 pop.w {r0-r3,r12,lr}
 ldr pc,=0x800365d9
