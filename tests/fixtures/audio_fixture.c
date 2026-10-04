/* Emulator-only callback body. DSP/cursor effects are explicitly synthetic;
 * this is never a replacement proposed for the device's DSP implementation. */
#include <stdint.h>
#define KEEP __attribute__((used,retain))
KEEP uint32_t audio_fixture_mode;
extern void bridge_hook(uint32_t,uint32_t);
KEEP __attribute__((noinline)) void audio_fixture_checkpoint(uint32_t phase) {
    __asm__ volatile(""::"r"(phase):"memory");
}
KEEP void audio_fixture_callback(void) {
    uint32_t mode=audio_fixture_mode;
    audio_fixture_checkpoint(0);
    if(mode&4)bridge_hook(10,0x2022a791u);
    if(!(mode&1))bridge_hook(1,0);
    if(mode&8)bridge_hook(1,0);
    audio_fixture_checkpoint(1);
    volatile uint32_t *cursor=(uint32_t*)0x20015e2cu;
    uint32_t next=*cursor+64,capacity=*(volatile uint32_t*)0x20015e30u;
    *cursor=next==capacity?0:next;
    if(!(mode&2))bridge_hook(2,0);
    if(mode&4)bridge_hook(11,0);
    audio_fixture_checkpoint(2);
}
