/* Experiment 06: explicit, once-per-boot memory reservation after normal boot.
 * No capture/task/file operation. Successful blocks are never freed or used.
 * The stack/task blocks reserve capacity only; they do not create a worker. */
#include <stdint.h>
#ifndef RESERVATION_ARENA_BYTES
#error "Build must derive the arena request from the current capture ABI"
#endif
#define W(a) (*(volatile uint32_t *)(a))
#define B(a) (*(volatile uint8_t *)(a))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define TICKS W(0x801f9050u)
#define STACK_BYTES 16384u
#define TASK_BYTES 148u
#define FLOOR_BYTES 65536u
#define CHARGE(n) (((n)&~7u)+16u)
#define EXPECTED_CHARGE (CHARGE(RESERVATION_ARENA_BYTES)+CHARGE(STACK_BYTES)+CHARGE(TASK_BYTES))
enum { UNTRIED, BUSY, HELD, HEADROOM_REFUSED, ALLOCATION_FAILED, CONTEXT_REFUSED };
typedef struct {
    uint32_t status,pointer[3],free_before,free_after,charge,elapsed;
} Reservation;
_Static_assert(sizeof(Reservation)==32,"reservation state ABI");
_Static_assert(RESERVATION_ARENA_BYTES==77279,"Review changed capture ABI before a new reservation trial");
__attribute__((section(".probe_state"),aligned(32),used))
Reservation reservation_stats={0};
extern uint32_t health_query(const uint8_t *);

static void reserve(void) {
    Reservation *s=&reservation_stats;
    uint32_t expected=UNTRIED;
    /* One weak claim, no admission loop. A missed claim leaves UNTRIED and may
     * be retried explicitly; an accepted attempt, including failure, is final. */
    if(!__atomic_compare_exchange_n(&s->status,&expected,BUSY,1,
                                   __ATOMIC_ACQ_REL,__ATOMIC_RELAXED))return;
    uint32_t basepri,primask;
    __asm__ volatile("mrs %0, basepri\n\tmrs %1, primask":"=r"(basepri),"=r"(primask));
    if(W(0x801f9048u)!=1 || W(0x801f901cu)!=0x8095ffd0u ||
       W(0x801f904cu)!=0 || !W(0x808e291cu) || basepri || primask) {
        ST(&s->status,CONTEXT_REFUSED);return;
    }
    uint32_t start=TICKS,result=HEADROOM_REFUSED;
    /* Original allocator/free suspend scheduling internally. This outer
     * nesting keeps the preflight, three allocations and rollback together;
     * native resume remains responsible for pending events/context switching. */
    ((void (*)(void))0x80074781u)();
    uint32_t before=W(0x801f9020u);
    ST(&s->free_before,before);
    /* A native split can consume up to 16 additional bytes of remainder per
     * block. Preserve the experimental 64-KiB floor even in that case. */
    if(before>=EXPECTED_CHARGE+48u+FLOOR_BYTES) {
        const uint32_t sizes[3]={RESERVATION_ARENA_BYTES,STACK_BYTES,TASK_BYTES};
        uint32_t i;
        for(i=0;i<3;i++) {
            uint32_t p=((uint32_t (*)(uint32_t))0x8006de79u)(sizes[i]);
            if(!p)break;
            ST(&s->pointer[i],p);
        }
        result=i==3?HELD:ALLOCATION_FAILED;
        if(result==HELD && W(0x801f9020u)<FLOOR_BYTES)result=HEADROOM_REFUSED;
        if(result!=HELD) {
            while(i) {
                --i;
                ((void (*)(uint32_t))0x80073f49u)(LD(&s->pointer[i]));
                ST(&s->pointer[i],0);
            }
        }
    }
    uint32_t after=W(0x801f9020u);
    ST(&s->free_after,after);ST(&s->charge,before-after);
    ST(&s->elapsed,TICKS-start);
    /* Publish only after pointers and exact charge are recorded. Other tasks
     * cannot run until native resume, and interrupts never consume the blocks. */
    ST(&s->status,result);
    ((uint32_t (*)(void))0x80077541u)();
}
static void encode(uint8_t *out,uint32_t value) {
    for(uint32_t i=0;i<5;i++){out[i]=(uint8_t)(value&127);value>>=7;}
}
/* Fixed request 79/reply 78, kind 1=read status, kind 2=reserve once.
 * The existing 7B/7A timing queries and all editor messages are unchanged.
 * Kind 2 is an explicit mutation, never described as a read-only query. */
uint32_t reservation_dispatch(const uint8_t *packet) {
    const uint8_t *p=packet+4;
    if(*(const uint32_t*)packet!=8 || p[0]!=0xf0 || p[1]!=0x52 || p[2] || p[3] ||
       p[4]!=0x79 || p[5]<1 || p[5]>2 || p[6]>127 || p[7]!=0xf7 ||
       B(0x80629b60u)!=2)return health_query(packet);
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(ipsr)return health_query(packet);
    if(p[5]==2)reserve();
    Reservation *s=&reservation_stats;
    uint8_t reply[88]={0xf0,0x52,0,0,0x78,p[5],p[6]};
    encode(reply+7,LD(&s->status));
    encode(reply+12,RESERVATION_ARENA_BYTES);encode(reply+17,STACK_BYTES);
    encode(reply+22,TASK_BYTES);encode(reply+27,EXPECTED_CHARGE);
    encode(reply+32,FLOOR_BYTES);encode(reply+37,LD(&s->free_before));
    encode(reply+42,LD(&s->free_after));encode(reply+47,LD(&s->charge));
    for(uint32_t i=0;i<3;i++)encode(reply+52+i*5,LD(&s->pointer[i]));
    encode(reply+67,LD(&s->elapsed));encode(reply+72,LD(&s->status));
    encode(reply+77,TICKS);encode(reply+82,W(0x801f904cu));reply[87]=0xf7;
    ((void (*)(const uint8_t*,uint32_t,uint32_t))0x80031649u)(reply,sizeof(reply),2);
    return 1;
}
