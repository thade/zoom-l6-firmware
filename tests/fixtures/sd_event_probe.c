/* OFFLINE ONLY. Native flag/token operations, not physical cancellation.
 * MODEL QUIET must pin all event users and exclude old controller/IRQ/task
 * posts through admission. NVIC masking alone supplies neither guarantee.
 * Supports only the traced binary semaphore and privileged Thread context.
 * Any rearm fault disables IRQ110 again; a failed disable acknowledgement
 * cannot prove masking. The caller retains its transfer on all faults.
 * Do not install or use as a general-purpose event reset. */
#include "sd_event_probe.h"
#define KEEP __attribute__((used,retain))
#define REG(a) (*(volatile uint32_t *)(a))
#define IRQ_BIT (1u<<14)
#define ISER 0xe000e10cu
#define ICPR 0xe000e28cu
#define ISPR 0xe000e20cu
#define IABR 0xe000e30cu
KEEP volatile SdEventProbe sdp_event_state;
KEEP volatile uint32_t sdp_kernel_port;

static uint32_t context(void) {
    uint32_t ipsr,basepri,primask,control;
    __asm__ volatile("mrs %0,ipsr":"=r"(ipsr));
    __asm__ volatile("mrs %0,basepri":"=r"(basepri));
    __asm__ volatile("mrs %0,primask":"=r"(primask));
    __asm__ volatile("mrs %0,control":"=r"(control));
    return ipsr || basepri || primask || (control&1) || REG(0x801f6090u);
}
KEEP int32_t sdp_event_context_ready(void) { return !context(); }
static void critical_enter(void) { ((void (*)(void))0x80073ec9u)(); }
static void critical_leave(void) { ((void (*)(void))0x80073f19u)(); }
static void disable(void) { ((int32_t (*)(int32_t))0x80032249u)(110); }
static void enable(void) { ((int32_t (*)(int32_t))0x80032259u)(110); }
static void barrier(void) { __asm__ volatile("dsb\nisb":::"memory"); }
static int32_t fail(uint32_t why) { sdp_event_state.fault=why;return 0; }
static int32_t identity(uint32_t event,uint32_t sem) {
    return REG(0x808e28e0u)==event && REG(event)==sem && REG(event+4)==1;
}
static int32_t schema(uint32_t sem) {
    return REG(sem)==sem && REG(sem+0x3c)==1 && !REG(sem+0x40) &&
           REG(sem+0x38)<=1 && !REG(sem+0x10) && !REG(sem+0x24) &&
           *(volatile uint8_t *)(sem+0x44)==0xff &&
           *(volatile uint8_t *)(sem+0x45)==0xff;
}
static int32_t hardware(void) {
    return !REG(0x402c0038u) && !REG(0x402c0030u);
}
static uint32_t count(uint32_t sem) {
    return ((uint32_t (*)(uint32_t))0x80073dd1u)(sem);
}
static int32_t take(uint32_t sem) {
    int32_t result=((int32_t (*)(uint32_t,uint32_t))0x80076951u)(sem,0);
    if(result==1)sdp_event_state.takes++;
    return result;
}
KEEP int32_t sdp_event_drain(uint32_t unit,uint32_t event) {
    sdp_event_state=(SdEventProbe){.calls=sdp_event_state.calls+1};
    /* Stock critical helpers replace BASEPRI, rather than save its old value. */
    if(!sdp_event_context_ready())return fail(SDP_EV_CONTEXT);
    if(unit || !event || (event&3) || REG(0x808e28e0u)!=event)
        return fail(SDP_EV_IDENTITY);
    uint32_t sem=REG(event);
    if(!sem || (sem&3) || !identity(event,sem))return fail(SDP_EV_IDENTITY);
    uint32_t priority=*(volatile uint8_t *)0xe000e46eu;
    if(priority<0x20 || (priority&15) || !(REG(ISER)&IRQ_BIT) || (REG(IABR)&IRQ_BIT))
        return fail(SDP_EV_IRQ);
    critical_enter();
    disable();sdp_event_state.disabled=!(REG(ISER)&IRQ_BIT);
    uint32_t fault=0,flags=0;
    if((REG(ISER)&IRQ_BIT) || (REG(IABR)&IRQ_BIT)){fault=SDP_EV_IRQ;goto done;}
    if(!identity(event,sem)){fault=SDP_EV_IDENTITY;goto done;}
    if(!schema(sem)){fault=SDP_EV_SCHEMA;goto done;}
    if(!hardware()){fault=SDP_EV_HARDWARE;goto done;}
    REG(ICPR)=IRQ_BIT;barrier();
    if(REG(ISPR)&IRQ_BIT){fault=SDP_EV_PENDING;goto done;}
    sdp_event_state.flags_before=REG(event+8);
    if(((int32_t (*)(uint32_t,uint32_t))0x80032209u)(event,0))
        {fault=SDP_EV_FLAGS;goto done;}
    /* The actual constructor creates a binary semaphore: consume at most one.
     * A second successful take would indicate a violated exclusion contract. */
    int32_t first=take(sem);
    if((first!=0 && first!=1) || take(sem)!=0){fault=SDP_EV_TOKEN;goto done;}
    if(!identity(event,sem)){fault=SDP_EV_IDENTITY;goto done;}
    if(!schema(sem)){fault=SDP_EV_SCHEMA;goto done;}
    if(((int32_t (*)(uint32_t,uint32_t *))0x80032879u)(event,&flags) || flags)
        {fault=SDP_EV_FLAGS;goto done;}
    if(count(sem)){fault=SDP_EV_TOKEN;goto done;}
    if(!identity(event,sem)){fault=SDP_EV_IDENTITY;goto done;}
    if(!schema(sem)){fault=SDP_EV_SCHEMA;goto done;}
    if(!hardware()){fault=SDP_EV_HARDWARE;goto done;}
    if(REG(ISPR)&IRQ_BIT){fault=SDP_EV_PENDING;goto done;}
    enable();barrier();
    if(!(REG(ISER)&IRQ_BIT) || (REG(IABR)&IRQ_BIT) || (REG(ISPR)&IRQ_BIT) ||
       !hardware() || !identity(event,sem) || REG(event+8) || count(sem))
        {fault=SDP_EV_REARM;disable();sdp_event_state.disabled=!(REG(ISER)&IRQ_BIT);}
    else sdp_event_state.rearmed=1;
done:
    critical_leave();
    return fault?fail(fault):1;
}
