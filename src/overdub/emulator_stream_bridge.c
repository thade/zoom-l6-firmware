#include "admission_gate.h"

/* Emulator-only interception of BL 0x80036c7c in SamplerUpdatePlyStream.
 * The harness owns one ordinary gate admission PER delivered queue message.
 * Never redirect all calls to 0x800369a8 here: direct prefetch calls and
 * promotion-owned child work require different, attributable ownership.
 * Actual producer admission, queue-failure handling and device placement are
 * not implemented. No installed firmware calls this function. */
__attribute__((used, retain)) void od_emulator_stream_callback(
        uint32_t pad, uint32_t frames, uint32_t span, uint32_t position) {
    ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t))0x800369a9)(
        pad,frames,span,position);
    /* Covers normal completion and the stock early-cancel return. */
    *(volatile int32_t *)0x2100380c=od_gate_work_end((OdGate *)0x21003800);
}
