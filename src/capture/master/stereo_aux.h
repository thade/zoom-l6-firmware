#ifndef L6_STEREO_AUX_H
#define L6_STEREO_AUX_H
/* Optional stereo AUX module (linked only into stereo builds): Main's receive
 * hook calls it through a weak reference. */
#include <stdint.h>
#define SA_TOGGLE_MAGIC 0x4c364158u   /* 'L6AX': Main category-3 event, toggle mono/stereo */
void sa_toggle(void) __attribute__((weak));
#endif
