#include "pad_commands.h"
#include <stddef.h>
#define KEEP __attribute__((used,retain))
#define LOAD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define STORE(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
KEEP const uint32_t pc_layout[]={sizeof(PadCommands),offsetof(PadCommands,latch),
    offsetof(PadCommands,closed),offsetof(PadCommands,phase),offsetof(PadCommands,count)};
static int task_context(void) {uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));return !ipsr;}
static int main_context(PadCommands *s) {
    return s && task_context() && s->port.main_task &&
        ((uint32_t (*)(void))0x800770e9u)()==s->port.main_task;
}
static int handoff_context(PadCommands *s) {
    return s && task_context() && s->port.handoff_task &&
        ((uint32_t (*)(void))0x800770e9u)()==s->port.handoff_task;
}
static int take(PadCommands *s) {
    uint32_t zero=0;return __atomic_compare_exchange_n(&s->latch,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static void give(PadCommands *s){STORE(&s->latch,0);}
KEEP int32_t pc_init(PadCommands *s,const PadCommandPort *p) {
    if(!s || !p || !p->main_task || !p->handoff_task || p->main_task==p->handoff_task ||
       !p->execute || !task_context())return PC_INVALID;
    const uint8_t *raw=(const uint8_t *)s;
    for(uint32_t i=0;i<sizeof(*s);i++)if(raw[i])return PC_INVALID;
    s->port=*p;return PC_OK;
}
KEEP int32_t pc_submit(PadCommands *s,const PadCommand *c) {
    if(!main_context(s) || !c || c->source>1 || c->pad>3)return PC_INVALID;
    if(!take(s))return PC_BUSY;
    if(s->count==PC_CAPACITY){give(s);return PC_BUSY;}
    s->queue[(s->head+s->count)%PC_CAPACITY]=*c;s->count++;
    give(s);return PC_OK;
}
KEEP int32_t pc_poll(PadCommands *s) {
    if(!main_context(s))return PC_INVALID;
    if(!take(s))return PC_BUSY;
    uint32_t phase=LOAD(&s->phase);
    if(phase==PC_RETURNED) {
        /* Completion bookkeeping may be retried, never the executed command. */
        s->head=(s->head+1)%PC_CAPACITY;s->count--;STORE(&s->phase,PC_IDLE);
        give(s);return PC_OK;
    }
    if(s->closed || phase!=PC_IDLE || !s->count){give(s);return PC_BUSY;}
    PadCommand command=s->queue[s->head];STORE(&s->phase,PC_RUNNING);give(s);
    s->port.execute(&command);
    STORE(&s->phase,PC_RETURNED);
    if(!take(s))return PC_BUSY;
    s->head=(s->head+1)%PC_CAPACITY;s->count--;STORE(&s->phase,PC_IDLE);
    give(s);return PC_OK;
}
KEEP int32_t pc_try_hold(PadCommands *s) {
    if(!handoff_context(s))return PC_INVALID;
    if(!take(s))return PC_BUSY;
    if(s->closed || s->count || LOAD(&s->phase)!=PC_IDLE){give(s);return PC_BUSY;}
    s->closed=1;give(s);return PC_OK;
}
KEEP int32_t pc_release(PadCommands *s) {
    if(!handoff_context(s))return PC_INVALID;
    if(!take(s))return PC_BUSY;
    if(!s->closed){give(s);return PC_INVALID;}
    s->closed=0;give(s);return PC_OK;
}
KEEP void pc_stock_execute(const PadCommand *c) {
    if(c->source==0)((void (*)(uint32_t,uint32_t,uint32_t))0x8003f4d9u)(c->pad,c->argument,c->event);
    else ((void (*)(uint32_t,uint32_t,uint32_t))0x800408b1u)(c->pad,c->argument,c->event);
}
