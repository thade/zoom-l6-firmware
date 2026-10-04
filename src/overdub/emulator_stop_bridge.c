#include "overdub.h"

/* Harness-only bridge: Unicorn redirects one observed BL here. These addresses
 * are emulator fixtures, NOT discovered spare RAM or an installation patch.
 * A real integration must independently capture the Job and close outcomes. */
__attribute__((used, retain)) uint32_t od_emulator_after_postprocess(int32_t target) {
    uint32_t original=((uint32_t (*)(int32_t))0x800032b1)(target);
    Job *job=(Job *)0x21002000;
    job->target=target;
    *(volatile int32_t *)0x21003000=od_promote((State *)0x21010000,(Port *)0x21001000,job);
    return original;
}
