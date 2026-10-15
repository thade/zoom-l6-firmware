#ifndef L6_STEREO_AUX_H
#define L6_STEREO_AUX_H
/* Optional stereo AUX module (linked only into stereo builds): the worker and
 * Main's receive hook call it through weak references. */
#include <stdint.h>
#define SA_TOGGLE_MAGIC 0x4c364158u   /* 'L6AX': Main category-3 event, toggle mono/stereo */
#define SA_RESTORE_MAGIC 0x4c364152u  /* 'L6AR': redraw the AUX select LEDs */
void sa_poll(void) __attribute__((weak));
void sa_toggle(uint32_t busy) __attribute__((weak));
void sa_restore(void) __attribute__((weak));
#endif
