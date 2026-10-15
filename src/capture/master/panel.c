/* Panel switches for stock L6 v1.10: two-button holds polled by the worker,
 * confirmed on two select LEDs for 2 s. AUX 1 + AUX 2 toggles the stereo AUX
 * mode (stereo builds), PAN + LEVEL turns the take chain on or off. Both are
 * view buttons: stock only changes the view for them, and has no long press
 * or combination of its own. See docs/research/panel_keys_findings.txt. */
#include <stdint.h>
#include "../retention.h"
#include "master_ref.h"
#include "stereo_aux.h"

#define KEY ((uint32_t (*)(uint32_t))0x80008479u)         /* live key state: 1 pressed */
#define TICKS (*(volatile uint32_t *)0x801f9050u)        /* 1 ms */
#define HOLD_TICKS 1500u
#define ARM_TICKS 10000u      /* no switching in the first 10 s: Main may not be in its normal loop */
#define GAP_TICKS 500u        /* both keys unseen for longer restarts a hold (a stall may hide a release) */
#define RELEASE_POLLS 3u      /* a release ends a hold once seen this many polls running (50-75 ms at
                                 25 ms polls, 20-30 ms at 10 ms): a one-off misread does not */
#define SHOW_TICKS 2000u      /* how long the LEDs show the new state */
#define RETRY_TICKS 250u      /* the worker repeats its redraw request until Main has done it */
#define POST ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t))0x80020ca1u)
#define SELECT_LED ((void (*)(uint32_t,uint32_t))0x800075d9u)   /* stock select LED: on/off, steady */
#define SELECT_LEDS 9u                                          /* HIGH FREQ MID LOW AUX1 AUX2 EFX PAN LEVEL */
#define VIEW (*(volatile uint8_t *)0x804430d8u)                 /* stock selected view (sel of the lit LED) */
#define LED_LOCK (*(volatile uint32_t *)0x80446840u)
#define LOCK ((uint32_t (*)(uint32_t,uint32_t))0x80076951u)
#define UNLOCK ((uint32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t))0x800763d9u)
#define LED(sel) ((volatile uint8_t *)(0x8062939cu+2u*((sel)+0xcu)))   /* select LED: level, mode (1 blinks) */
/* Stock recorder state: 1 from record start (ordinary or to a pad) until
 * RecStop has finalized; the RecPlayCtl busy word covers both callbacks. */
#define RECORDING (*(volatile uint8_t *)0x80578ebcu)
#define RECORDER_BUSY (*(volatile uint32_t *)0x80578ec0u)

/* The holds (constant, with the code) and their state (zeroed globals: the
 * layout carries no initialised data). */
typedef struct {uint8_t a,b;uint32_t magic;} Pair;
static const Pair PAIRS[]={{16,17,SA_TOGGLE_MAGIC},{19,20,MR_CHAIN_MAGIC}};   /* AUX1+AUX2, PAN+LEVEL */
#define HOLDS (sizeof(PAIRS)/sizeof(PAIRS[0]))
typedef struct {uint32_t held_since,seen,holding,fired,up;} Hold;
static Hold holds[HOLDS];
static uint32_t restore_posted;
static volatile uint32_t showing,shown_at;   /* set by Main (show), cleared by Main (redraw) */

/* The LED show has lasted SHOW_TICKS. Signed: a show Main started after the
 * caller read the time is not yet due. */
static int due(uint32_t now) {return showing && (int32_t)(now-shown_at)>=(int32_t)SHOW_TICKS;}

/* Worker: each hold that lasts HOLD_TICKS posts its event to Main, once per
 * hold; a due show is asked to end. */
KEEP void panel_poll(void) {
    uint32_t now=TICKS;
    if(due(now) && now-restore_posted>=RETRY_TICKS){restore_posted=now;POST(MR_HANDOFF_EVENT,PANEL_RESTORE_MAGIC,0,0,0);}
    for(uint32_t i=0;i<HOLDS;i++) {
        Hold *h=&holds[i];const Pair *k=&PAIRS[i];
        if(now<ARM_TICKS || KEY(k->a)!=1 || KEY(k->b)!=1) {
            /* A one-off misread does not end a hold; a real release (and only
             * that) allows the next toggle. */
            if(h->holding && now>=ARM_TICKS && ++h->up<RELEASE_POLLS)continue;
            h->holding=h->fired=h->up=0;continue;
        }
        h->up=0;
        uint32_t unseen=now-h->seen;h->seen=now;
        if(!h->holding || unseen>GAP_TICKS){h->holding=1;h->held_since=now;continue;}   /* unseen for long: may hide a release */
        if(!h->fired && now-h->held_since>=HOLD_TICKS){h->fired=1;POST(MR_HANDOFF_EVENT,k->magic,0,0,0);}
    }
}
/* Main: switches are refused while any recording runs or finalizes. */
KEEP int panel_recording(void) {return RECORDING==1u || RECORDER_BUSY;}
/* Both bytes of a select LED in one critical section, as the stock setters do. */
static void led(uint32_t sel,uint8_t level,uint8_t mode) {
    LOCK(LED_LOCK,0xffffffffu);
    LED(sel)[0]=level;LED(sel)[1]=mode;
    UNLOCK(LED_LOCK,0,0,0);
}
/* Main: for SHOW_TICKS both LEDs of a pair blink (on) or light steadily
 * (off), a pattern the stock view indication (one steady select LED) never
 * shows. A new show replaces one still running. */
KEEP void panel_show(uint32_t sel_a,uint32_t sel_b,uint32_t blink) {
    led(sel_a,0x10,(uint8_t)!!blink);led(sel_b,0x10,(uint8_t)!!blink);
    shown_at=TICKS;showing=1;
}
/* Main, for every received event (the worker's request wakes it): once the
 * show is due, clear it and redraw the select LEDs from the view as stock
 * does, so the show ends even if the worker is starved or a request is lost. */
KEEP void panel_restore(void) {
    if(!due(TICKS))return;
    showing=0;
    uint32_t view=VIEW;
    for(uint32_t sel=0;sel<SELECT_LEDS;sel++)SELECT_LED(sel,view==sel);
}
