#ifndef L6_CAPTURE_RETENTION_H
#define L6_CAPTURE_RETENTION_H
/* Research builds expose every entry to the emulator. A separate minimal
 * build lets the linker remove unreachable entries; its external roots are
 * explicit in build_extra_capture.py. This changes retention, not behavior. */
#ifdef L6_CAPTURE_MINIMAL_LINK
#define KEEP __attribute__((used))
#else
#define KEEP __attribute__((used,retain))
#endif
#endif
