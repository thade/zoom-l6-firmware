/* No track files for muted channels with no sends, for stock L6 v1.10
 * (experiment 43). Opt-in: holding AUX 2 + EFX for 1.5 s switches it on or
 * off (the hold is in panel.c). While it is on, an ordinary take leaves out
 * every channel 1-6 whose channel mute is on and whose sends carry nothing:
 * for each send that matters, the level is zero, or the send is muted, or
 * the send point is post-fader (a post-fader send follows the channel
 * mute). In mono AUX mode the sends that matter are EFX, AUX 1 and AUX 2;
 * in stereo AUX mode EFX and AUX 1, because the AUX 2 knob does nothing
 * there. The EFX send has no send point in stock (the send point setter
 * 0x8000cb28 takes AUX 1 and 2 only), so it matters whenever its level is
 * nonzero and it is not muted. Both lanes of a channel go together, MONO x2
 * included; MASTER.WAV (streams 10 and 11) is never left out; pad-record
 * takes and the project loader keep stock's answer.
 *
 * The one patch site: the record prepare 0x80002df8 calls the stock stream
 * mask selector 0x80008990(target) at 0x80002e96 and hands the mask to
 * 0x8000b540; that call becomes a call of tm_select, which calls the
 * selector and filters its answer. The stock selector itself is not
 * patched: the project loader 0x80002d30 calls it too and must keep
 * stock's answer. See docs/research/unused_track_files_findings.txt. */
#include <stdint.h>
#include "../retention.h"
#include "master_ref.h"
#include "stock.h"
#include "track_mask.h"

#define SELECT ((uint32_t (*)(int32_t))0x80008991u)   /* stock: 0xfff, or 0xc00 for Master Only or a pad target */
/* Per-lane mixer state, 0x15 bytes per lane from CONFIG, through the stock getters. */
#define CHANNEL_MUTE ((int32_t (*)(uint32_t))0x80005f51u)                 /* byte 0 */
#define EFX_LEVEL ((int32_t (*)(uint32_t,uint32_t))0x80005f61u)           /* +0x9 (index 0) */
#define EFX_MUTE ((int32_t (*)(uint32_t,uint32_t))0x80005f79u)            /* +0xa */
#define AUX_LEVEL ((int32_t (*)(uint32_t,uint32_t))0x80005f11u)           /* +0xc+aux, signed */
#define AUX_MUTE ((int32_t (*)(uint32_t,uint32_t))0x80005f29u)            /* +0xe+aux */
#define AUX_POST ((uint32_t (*)(uint32_t,uint32_t))0x80005ef9u)           /* +0x13+aux: 1 post-fader (the Editor's AUX Send Point) */
#define SKIP_A 0x96u
#define SKIP_B 0x69u
#define SEL_AUX2 5u
#define SEL_EFX 6u
#define CHANNELS 6u
#define STEREO_A 0xa5u
#define STEREO_B 0x5au
static const uint8_t HEAD[CHANNELS]={0,1,2,4,6,8};   /* channel 1-6 to its head lane; channels 3-6 also own the next lane */

KEEP uint32_t tm_takes;      /* ordinary takes prepared with the setting on */
KEEP uint32_t tm_dropped;    /* lanes left out, in all */
KEEP uint32_t tm_last;       /* channels (bit per channel) left out of the last take */
KEEP uint32_t tm_toggles,tm_refused;
extern MasterRef *mr_state;

/* On only for the exact pair and while the switch can run (the worker is
 * published), as the stereo mode: a stored setting cannot outlive the hold
 * that switches it off. */
static int on(void) {
    return SKIP_MODE[0]==SKIP_A && SKIP_MODE[1]==SKIP_B && __atomic_load_n(&mr_state,__ATOMIC_RELAXED);
}
static int stereo(void) {return AUX_MODE[0]==STEREO_A && AUX_MODE[1]==STEREO_B;}
/* Nothing reaches this lane's sends. */
static int silent(uint32_t lane,uint32_t auxes) {
    if(EFX_LEVEL(lane,0) && !EFX_MUTE(lane,0))return 0;
    for(uint32_t aux=0;aux<auxes;aux++)
        if(AUX_LEVEL(lane,aux) && !AUX_MUTE(lane,aux) && !AUX_POST(lane,aux))return 0;
    return 1;
}
/* Every lane of the channel is muted and feeds no send. */
static int unused(uint32_t ch,uint32_t auxes) {
    uint32_t lanes=ch<2u?1u:2u;
    for(uint32_t k=0;k<lanes;k++) {
        uint32_t lane=HEAD[ch]+k;
        if(!CHANNEL_MUTE(lane) || !silent(lane,auxes))return 0;
    }
    return 1;
}
/* Main, in the record prepare in place of its selector call. Returns the
 * stream mask for 0x8000b540. */
KEEP uint32_t tm_select(int32_t target) {
    uint32_t mask=SELECT(target);
    if(target>=0 || !on())return mask;   /* a pad target, or the setting off: stock */
    uint32_t auxes=stereo()?1u:2u,kept=mask,drop=0;
    for(uint32_t ch=0;ch<CHANNELS;ch++) {
        uint32_t bits=(ch<2u?1u:3u)<<HEAD[ch];
        if((mask&bits) && unused(ch,auxes)){mask&=~bits;drop|=1u<<ch;}
    }
    tm_takes++;tm_last=drop;
    for(uint32_t gone=kept&~mask;gone;gone&=gone-1u)tm_dropped++;
    if(drop)panel_show_mutes(drop);
    return mask;
}
/* Main, from the receive hook (the AUX 2 + EFX hold, panel.c). Refused while
 * any recording runs or finalizes. AUX 2 and EFX blink (on) or light
 * steadily (off) for 2 s. */
KEEP void tm_toggle(void) {
    if(panel_recording()){tm_refused++;return;}
    int to_on=!(SKIP_MODE[0]==SKIP_A && SKIP_MODE[1]==SKIP_B);
    SKIP_MODE[0]=to_on?SKIP_A:0;SKIP_MODE[1]=to_on?SKIP_B:0;
    SAVE();
    panel_show(SEL_AUX2,SEL_EFX,(uint32_t)to_on);
    tm_toggles++;
}
