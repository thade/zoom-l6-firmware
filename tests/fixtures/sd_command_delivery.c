/* ONLY an emulator IRQ-delivery endpoint. Never linked into a device image. */
#include <stdint.h>
int32_t command_delivery(uint32_t event,uint32_t mask,uint32_t mode,uint32_t *flags,uint32_t timeout) {
    if(((uint32_t (*)(uint32_t,uint32_t))0x2102be01u)(event,mask)) {
        uint32_t unit=event==*(volatile uint32_t*)0x808e28e0u?0:1;
        ((void (*)(uint32_t))0x8006ea99u)(unit);
    }
    return ((int32_t (*)(uint32_t,uint32_t,uint32_t,uint32_t*,uint32_t))0x800326c1u)(event,mask,mode,flags,timeout);
}
