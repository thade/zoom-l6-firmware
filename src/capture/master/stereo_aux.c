/* Stereo AUX send for stock L6 v1.10: AUX 1 carries left and AUX 2 right,
 * switchable to the stock two mono sends by holding AUX 1 + AUX 2 for 1.5 s
 * (the hold and its LED confirmation are in panel.c).
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
#define SEL_AUX1 4u
#define SEL_AUX2 5u

KEEP uint32_t sa_toggles,sa_refused;
extern MasterRef *mr_state;
/* Stereo only while the switch can run: the worker that polls the hold is
 * published before any task starts, so without it the mixer is stock mono
 * from power-on and a stored stereo mode cannot leave it stuck in stereo. */
static int stereo(void) {
    return MODE[0]==STEREO_A && MODE[1]==STEREO_B && __atomic_load_n(&mr_state,__ATOMIC_RELAXED);
}

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

/* On Main, from the receive hook (the AUX 1 + AUX 2 hold, panel.c). Refused
 * while any recording runs or finalizes. Both AUX LEDs blink (stereo) or
 * light steadily (mono) for 2 s. */
KEEP void sa_toggle(void) {
    if(panel_recording()){sa_refused++;return;}
    int to_stereo=!stereo();
    MODE[0]=to_stereo?STEREO_A:0;MODE[1]=to_stereo?STEREO_B:0;
    RECOMPUTE(1);   /* every gain again, through the filter, as 16 ms ramps */
    SAVE();
    panel_show(SEL_AUX1,SEL_AUX2,(uint32_t)to_stereo);
    sa_toggles++;
}
