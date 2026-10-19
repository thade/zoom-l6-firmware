#ifndef L6_TRACK_MASK_H
#define L6_TRACK_MASK_H
/* Optional: no track files for muted channels with no sends (track_mask.c,
 * linked only into builds with TRACK_MASK; experiment 43). Main's receive
 * hook routes the AUX 2 + EFX hold to the toggle; the record prepare's
 * stream mask selector call is replaced by tm_select. */
#include <stdint.h>
#define TM_TOGGLE_MAGIC 0x4c36544du   /* 'L6TM': Main category-3 event, toggle the setting */
uint32_t tm_select(int32_t target);
void tm_toggle(void);
/* panel.c: the dropped channels' MUTE LEDs blink for the show time. */
void panel_show_mutes(uint32_t channels);
#endif
