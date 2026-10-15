/* Stereo AUX send for stock L6 v1.10: AUX 1 carries left and AUX 2 right,
 * switchable to the stock two mono sends by holding AUX 1 + AUX 2 for 1.5 s.
 * In stereo:
 * Each input lane j feeds the pair with the gain stock code computes for its
 * AUX 1 send (send amount, pre/post, and level and mute when post), times the
 * channel's own pan/balance factors, so the send image follows channel pan.
 * The AUX 2 knob and pre/post choice are kept but unused. Pads and internal
 * effects are not part of the stock AUX sends and are not added.
 * See docs/research/stereo_aux_findings.txt. */
#include <stdint.h>
#include "../retention.h"
#include "master_ref.h"
#include "stereo_aux.h"

#define B 0x20010a48u
#define C 0x20016f68u
#define AUX1_ROW (B+0x5e84u)                     /* ten float gains, lane j */
#define AUX2_ROW (B+0x5eacu)
#define AUX1 ((volatile float *)AUX1_ROW)
#define AUX2 ((volatile float *)AUX2_ROW)
#define STATE1(j) ((void *)(B+0x5fc4u+12u*(j)))   /* stock ramp state per row and lane */
#define STATE2(j) ((void *)(B+0x603cu+12u*(j)))
#define PAN(j) ((volatile const float *)(C+0xc0u+8u*(j)))   /* left, right factors */

typedef uint32_t Ramp(volatile float *dst,uint32_t ms,void *state,float target);
extern Ramp sa_ramp_original;   /* the stock request 0x80010398 (displaced prologue) */
#define UPDATE ((void (*)(uint32_t,uint32_t,uint32_t))0x80048c79u)   /* coefficient updater */
#define MONO_PAN ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t))0x8000d631u)
#define BALANCE ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t))0x8000cb71u)
#define RESET_FLAG (*(volatile uint32_t *)(C+0x1fcu))
#define RESET1 ((void (*)(uint32_t))0x8000da29u)          /* Editor mixer reset, mode 1 */
#define RESET2 ((void (*)(uint32_t))0x8000dca9u)          /* mode 2 */
#define RECOMPUTE ((void (*)(uint32_t))0x8000c649u)       /* stock bulk recompute (scenes, startup) */
/* The mode lives in two global settings bytes stock code never uses, checks
 * or puts in scenes (CONFIG+0x30d/0x30e, saved to internal flash with the
 * other globals): stereo only for this exact pair, so anything else, such as
 * a never-written zero, is the stock mono. */
#define MODE ((volatile uint8_t *)(0x80440dc8u+0x30du))
#define STEREO_A 0xa5u
#define STEREO_B 0x5au
#define SAVE ((void (*)(void))0x80006ab9u)               /* request a settings save (as record start does) */
/* Stock recorder state: 1 from record start (ordinary or to a pad) until
 * RecStop has finalized; the RecPlayCtl busy word covers both callbacks. */
#define RECORDING (*(volatile uint8_t *)0x80578ebcu)
#define RECORDER_BUSY (*(volatile uint32_t *)0x80578ec0u)
#define KEY ((uint32_t (*)(uint32_t))0x80008479u)         /* live key state: 1 pressed */
#define KEY_AUX1 16u
#define KEY_AUX2 17u
#define TICKS (*(volatile uint32_t *)0x801f9050u)        /* 1 ms */
#define HOLD_TICKS 1500u
#define ARM_TICKS 10000u      /* no switching in the first 10 s: Main may not be in its normal loop */
#define GAP_TICKS 100u        /* a longer gap between polls restarts the hold */
#define SHOW_TICKS 2000u      /* how long the AUX LEDs show the new mode */
#define RETRY_TICKS 250u      /* the worker repeats its redraw request until Main has done it */
#define POST ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t))0x80020ca1u)
#define SELECT_LED ((void (*)(uint32_t,uint32_t))0x800075d9u)   /* stock select LED: on/off, steady */
#define VIEW (*(volatile uint8_t *)0x804430d8u)                 /* stock selected view (4 AUX 1, 5 AUX 2) */
#define LED_LOCK (*(volatile uint32_t *)0x80446840u)
#define LOCK ((uint32_t (*)(uint32_t,uint32_t))0x80076951u)
#define UNLOCK ((uint32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t))0x800763d9u)
#define LED(sel) ((volatile uint8_t *)(0x8062939cu+2u*((sel)+0xcu)))   /* select LED: level, mode (1 blinks) */
#define SEL_AUX1 4u
#define SEL_AUX2 5u

KEEP uint32_t sa_toggles,sa_refused;
extern MasterRef *mr_state;
static uint32_t held_since,last_poll,holding,fired,restore_posted;
static volatile uint32_t showing,shown_at;   /* set by Main (toggle), cleared by Main (redraw) */
/* Stereo only while the switch can run: the worker that polls the hold is
 * published before any task starts, so without it the mixer is stock mono
 * from power-on and a stored stereo mode cannot leave it stuck in stereo. */
static int stereo(void) {
    return MODE[0]==STEREO_A && MODE[1]==STEREO_B && __atomic_load_n(&mr_state,__ATOMIC_RELAXED);
}
/* The LED show has lasted SHOW_TICKS. Signed: a toggle Main handled after the
 * caller read the time is not yet due. */
static int due(uint32_t now) {return showing && (int32_t)(now-shown_at)>=(int32_t)SHOW_TICKS;}

/* Replaces the entry of the stock gain-ramp request 0x80010398, which every
 * runtime coefficient change uses (task context only). An AUX 1 request
 * carries G[j]: it becomes a request for each side of the pair. AUX 2
 * requests are dropped; everything else passes through unchanged. */
KEEP uint32_t sa_ramp(volatile float *dst,uint32_t ms,void *state,float target) {
    uint32_t offset=(uint32_t)dst-AUX1_ROW;
    if(offset>=0x50u || !stereo())return sa_ramp_original(dst,ms,state,target);
    if(offset>=0x28u)return 0;
    uint32_t j=offset>>2;
    /* Both factors first: the first request can block, and pan may change meanwhile. */
    float left=PAN(j)[0],right=PAN(j)[1];
    sa_ramp_original(&AUX1[j],ms,STATE1(j),target*left);
    return sa_ramp_original(&AUX2[j],ms,STATE2(j),target*right);
}
/* Replace the apply veneers of mono pan (0x80002ac0) and stereo balance
 * (0x800028d8), which update only the master rows: also refresh the pair.
 * The pair is always ramped: the updater's unramped path stores AUX 1 alone. */
KEEP void sa_mono_pan(uint32_t lane,uint32_t pan,uint32_t ramp) {
    MONO_PAN(lane,pan,ramp,1);
    if(lane<=1u && stereo())UPDATE(lane,1,1);
}
KEEP void sa_balance(uint32_t channel,uint32_t pan,uint32_t ramp) {
    if(channel>3u)return;
    uint32_t lane=2u+2u*channel;
    BALANCE(lane,pan,ramp,1);
    if(!stereo())return;
    UPDATE(lane,1,1);
    UPDATE(lane+1u,1,1);
}
/* Replace the veneers of the Editor's mixer reset modes 1 and 2 (0x80002b78,
 * 0x80002b90), whose resets store the gain rows directly, past the filter:
 * do as the veneer did, then let the stock bulk recompute re-issue every gain
 * through it. */
KEEP void sa_reset1(void) {RESET_FLAG=1;RESET1(0);if(stereo())RECOMPUTE(1);}
KEEP void sa_reset2(void) {RESET_FLAG=1;RESET2(0);if(stereo())RECOMPUTE(1);}

/* ---- The switch: hold AUX 1 + AUX 2 for 1.5 s ----
 * Polled by the worker (any task may read the live key state); a hold that
 * lasts HOLD_TICKS asks Main to toggle, once per hold. Stock only shows the
 * AUX 2 view for this, as for a tap of AUX 2. */
KEEP void sa_poll(void) {
    uint32_t now=TICKS,gap=now-last_poll;
    last_poll=now;
    if(due(now) && now-restore_posted>=RETRY_TICKS){restore_posted=now;POST(3,SA_RESTORE_MAGIC,0,0,0);}
    if(now<ARM_TICKS || KEY(KEY_AUX1)!=1 || KEY(KEY_AUX2)!=1){holding=fired=0;return;}
    if(!holding || gap>GAP_TICKS){holding=1;held_since=now;return;}   /* a stalled poll may hide a release */
    if(!fired && now-held_since>=HOLD_TICKS){fired=1;POST(3,SA_TOGGLE_MAGIC,0,0,0);}
}
/* Both bytes of a select LED in one critical section, as the stock setters do. */
static void led(uint32_t sel,uint8_t level,uint8_t mode) {
    LOCK(LED_LOCK,0xffffffffu);
    LED(sel)[0]=level;LED(sel)[1]=mode;
    UNLOCK(LED_LOCK,0,0,0);
}
/* On Main, from the receive hook. Refused while any recording runs or
 * finalizes. For SHOW_TICKS both AUX LEDs blink (stereo) or light steadily
 * (mono), a pattern the stock view indication (one steady select LED) never
 * shows; then sa_restore redraws the view as stock does. */
KEEP void sa_toggle(void) {
    if(RECORDING==1u || RECORDER_BUSY){sa_refused++;return;}
    int to_stereo=!stereo();
    MODE[0]=to_stereo?STEREO_A:0;MODE[1]=to_stereo?STEREO_B:0;
    RECOMPUTE(1);   /* every gain again, through the filter, as 16 ms ramps */
    SAVE();
    led(SEL_AUX1,0x10,(uint8_t)to_stereo);led(SEL_AUX2,0x10,(uint8_t)to_stereo);
    shown_at=TICKS;showing=1;
    sa_toggles++;
}
/* On Main for every received event (the worker's request wakes it): once the
 * show is due, clear it and redraw, so the show ends even if the worker is
 * starved or a request is lost. */
KEEP void sa_restore(void) {
    if(!due(TICKS))return;
    showing=0;
    uint32_t view=VIEW;
    SELECT_LED(SEL_AUX1,view==SEL_AUX1);SELECT_LED(SEL_AUX2,view==SEL_AUX2);
}
