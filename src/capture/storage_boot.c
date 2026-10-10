/* Bind the first normal Main startup to actual directory and USB-worker
 * execution. Missing/out-of-order observations permanently disable this
 * optional witness; original calls still run. No retry, queue or wait loop. */
#include "storage_boot.h"
#include "retention.h"
#define W(a) (*(volatile uint32_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
KEEP uint32_t storage_boot_phase;
static uint32_t command,argument;

KEEP void storage_boot_revoke(void) { ST(&storage_boot_phase,SB_REVOKED); }
static void advance(uint32_t from,uint32_t to) {
    if(!__atomic_compare_exchange_n(&storage_boot_phase,&from,to,0,
                                    __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))
        storage_boot_revoke();
}
static uint32_t main_thread(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0,ipsr":"=r"(ipsr));
    return !ipsr && W(0x801f9048u) && W(0x80446da4u) &&
        ((uint32_t (*)(void))0x800770e9u)()==W(0x80446da4u);
}
KEEP int32_t storage_boot_card(uint32_t a) {
    if(a || !main_thread() || ((uint32_t (*)(void))0x80006249u)())
        storage_boot_revoke();
    advance(SB_COLD,SB_CARD);
    int32_t result=((int32_t (*)(uint32_t))0x80009a41u)(a);
    if(result)storage_boot_revoke();
    advance(SB_MOUNTED,SB_CARD_DONE);
    return result;
}
KEEP void storage_boot_usb(uint32_t mode,uint32_t profile) {
    if(mode || profile>2 || !main_thread())storage_boot_revoke();
    /* The only accepted request is made by this first Main call. Publication
     * precedes the request and worker consumption; command/argument are never
     * reused for another generation. */
    command=profile<=2 ? (0x20u<<(profile*2)) : 0;
    advance(SB_CARD_DONE,SB_USB);
    ((void (*)(uint32_t,uint32_t))0x8000c221u)(mode,profile);
    /* A stale ACK may return before worker execution. Disable capture instead
     * of altering the native handshake or guessing that the worker is ready. */
    advance(SB_ACKED,SB_USB_DONE);
}
KEEP void storage_boot_observe(uint32_t event,const uint32_t *s) {
    /* Assembly saves APSR/padding, then r0-r12/LR. The observation runs at the
     * original instruction, before its mailbox store/load or ACK give. */
    if(event==0) { advance(SB_CARD,SB_MOUNTED);return; }
    if(event==1) {
        if(!main_thread() || s[7]!=command || W(0x801f910cu) || W(0x801f9110u))
            storage_boot_revoke();
        argument=s[6];advance(SB_USB,SB_REQUESTED);return;
    }
    if(s[10]!=0x801f9108u || s[9]) { storage_boot_revoke();return; }
    if(event==2) {
        uint32_t c=W(0x801f910cu);
        if(!c)return; /* Empty worker poll; never an acknowledgement. */
        if(c!=command || W(0x801f9110u)!=argument)storage_boot_revoke();
        advance(SB_REQUESTED,SB_CONSUMED);return;
    }
    if(event!=3 || W(0x801f910cu) || W(0x801f9110u))storage_boot_revoke();
    advance(SB_CONSUMED,SB_ACKED);
}
KEEP void storage_boot_receive(uint32_t return_address) {
    if(!main_thread() || return_address!=0x8002c445u)storage_boot_revoke();
    if(LD(&storage_boot_phase)!=SB_READY)advance(SB_USB_DONE,SB_READY);
}
KEEP uint32_t storage_boot_ready(void) { return LD(&storage_boot_phase)==SB_READY; }
