#ifndef L6_STORAGE_BOOT_H
#define L6_STORAGE_BOOT_H
#include <stdint.h>
/* Logical, one-boot witness only. This does not grant physical SD permission,
 * admit the storage lease or release the capture worker. */
enum {SB_COLD,SB_CARD,SB_MOUNTED,SB_CARD_DONE,SB_USB,SB_REQUESTED,
      SB_CONSUMED,SB_ACKED,SB_USB_DONE,SB_READY,SB_REVOKED};
uint32_t storage_boot_ready(void);
void storage_boot_revoke(void);
void storage_boot_receive(uint32_t return_address);
int32_t storage_boot_card(uint32_t argument);
void storage_boot_usb(uint32_t mode,uint32_t profile);
void storage_boot_observe(uint32_t event,const uint32_t *saved);
#endif
