/* Test-only effect callback: invokes the REAL stock imported copy producer.
 * This is not an original Zoom effect or proposed replacement processor. */
#include <stdint.h>
__attribute__((used,retain)) void oc_fixture_effect_copy(void *context,const uint32_t *table) {
    (void)context;
    ((void (*)(void *,const void *,uint32_t))table[11])((void*)0x21038000,(const void*)0x21037000,16);
}
