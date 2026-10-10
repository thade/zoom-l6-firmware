/* Offline Main receive binding. This is not permission to enable capture:
 * physical I/O completion and the full native lock dependency audit are separate.
 * Five byte-checked Main BL sites call this instead of the original receiver. */
#include "native_arena.h"
#include "retention.h"
#ifdef L6_CAPTURE_BOOT_WITNESS
#include "storage_boot.h"
#endif
extern NativeCaptureArena *startup_arena;

KEEP int32_t storage_main_receive(uint32_t *packet) {
#ifdef L6_CAPTURE_BOOT_WITNESS
    storage_boot_receive((uint32_t)__builtin_return_address(0));
#endif
    int32_t result=((int32_t (*)(uint32_t*))0x80020691u)(packet);
    /* Conservative cancellation before card/USB/power/mode handler effects.
     * Preserve the original receiver, including its native event coalescing.
     * No private queue, packet copy, timer event or lower-callee BUSY result. */
    uint32_t changes_storage=(packet[0]==0 && packet[2]>=0x32 && packet[2]<=0x35) ||
        (packet[0]==1 && packet[1]==0 && packet[2]<=5) ||
        /* Native category-2 dispatch selects by code alone; subtype is ignored. */
        (packet[0]==2 && (packet[2]==0xa2 || packet[2]==0xa3));
    NativeCaptureArena *a=startup_arena;
#ifdef L6_CAPTURE_BOOT_WITNESS
    if(changes_storage)storage_boot_revoke();
#endif
    if(changes_storage && a && a->lease.manager) {
        /* Retain the packet on Main's existing stack and leave later packets
         * in the original FIFO. The independent file worker completes cleanup.
         * Never time out into a transition with uncertain file ownership.
         * Closed control objects remain owned until reboot, so old ordinary
         * callbacks do not have to retire before storage-only shutdown joins. */
        uint32_t closed=storage_lease_close(&a->lease);
        while(closed || storage_lease_join(&a->lease))
            ((void (*)(uint32_t))0x80074159u)(1);
    }
    return result;
}
