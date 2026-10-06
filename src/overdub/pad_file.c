#include "pad_file.h"
#define KEEP __attribute__((used,retain))
#define W(a) (*(volatile uint32_t *)(a))
typedef struct {uint32_t pad,handle,token;} Pin;
typedef struct {uint32_t owner,retained,queued;} Writer;
typedef struct {uint32_t handle,owner,token,pads;} Close;
#define CLOSE_SLOTS 8
static struct {
    RlCoordinator *coordinator;void (*yield)(void);
    uint32_t lock,sequence;Writer writers[4];Pin pins[PF_PIN_SLOTS];
    uint32_t revoked;Close closes[CLOSE_SLOTS];
} pad_files;
static int lock(void) {
    uint32_t z=0;return __atomic_compare_exchange_n(&pad_files.lock,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(int32_t s){__atomic_store_n(&pad_files.lock,0,__ATOMIC_RELEASE);return s;}
KEEP int32_t pf_bind(RlCoordinator *c,void (*yield)(void)) {
    if(pad_files.coordinator || !c || !c->ledger || !yield)return OWN_CONFLICT;
    if(c->lock || c->ledger->lock || c->ledger->gate.word)return OWN_BUSY;
    for(uint32_t i=0;i<RL_SLOTS;i++)if(c->jobs[i].owner)return OWN_BUSY;
    pad_files.coordinator=c;pad_files.yield=yield;return OWN_OK;
}
KEEP int32_t pf_ready(RlCoordinator *c){return c && pad_files.coordinator==c?OWN_OK:OWN_CONFLICT;}
KEEP int32_t pf_pin(RlCoordinator *c,uint32_t slot,uint32_t pad,uint32_t *out) {
    if(slot>=PF_PIN_SLOTS || pad>3 || !out)return OWN_CONFLICT;
    if(!pad_files.coordinator) {
        out[0]=W(0x80735b24u+20*pad);out[1]=0;
        return out[0]?OWN_OK:OWN_CONFLICT;
    }
    if(c!=pad_files.coordinator)return OWN_CONFLICT;
    if(!lock())return OWN_BUSY;
    if(pad_files.writers[pad].owner || pad_files.pins[slot].token)return leave(OWN_BUSY);
    if(pad_files.revoked&(1u<<pad))return leave(OWN_CONFLICT);
    uint32_t handle=W(0x80735b24u+20*pad),base=0x807348d0u+0x22cu*pad;
    if(!handle || W(base)!=1 || W(base+4)!=handle)return leave(OWN_CONFLICT);
    for(uint32_t i=0;i<4;i++)if(pad_files.writers[i].owner &&
        (pad_files.writers[i].retained==handle || pad_files.writers[i].queued==handle))return leave(OWN_BUSY);
    for(uint32_t i=0;i<CLOSE_SLOTS;i++)if(pad_files.closes[i].token &&
        pad_files.closes[i].handle==handle)return leave(OWN_BUSY);
    if(pad_files.sequence==UINT32_MAX)return leave(OWN_FULL);
    uint32_t token=++pad_files.sequence;
    pad_files.pins[slot]=(Pin){pad,handle,token};out[0]=handle;out[1]=token;
    return leave(OWN_OK);
}
KEEP int32_t pf_drop(uint32_t slot,uint32_t token) {
    if(!token)return OWN_OK; /* Legacy unbound snapshot. */
    if(!pad_files.coordinator || slot>=PF_PIN_SLOTS)return OWN_CONFLICT;
    if(!lock())return OWN_BUSY;
    if(pad_files.pins[slot].token!=token)return leave(OWN_STALE);
    pad_files.pins[slot].token=0;return leave(OWN_OK);
}
KEEP int32_t pf_change_begin(uint32_t pad,uint32_t owner) {
    if(!pad_files.coordinator || pad>3 || !owner)return OWN_CONFLICT;
    if(!lock())return OWN_BUSY;
    if(pad_files.writers[pad].owner)return leave(OWN_BUSY);
    uint32_t retained=W(0x807348d4u+0x22cu*pad),queued=W(0x80735b24u+20*pad);
    for(uint32_t i=0;i<CLOSE_SLOTS;i++)if(pad_files.closes[i].token &&
        ((pad_files.closes[i].pads&(1u<<pad)) || pad_files.closes[i].handle==retained ||
         pad_files.closes[i].handle==queued))return leave(OWN_BUSY);
    for(uint32_t i=0;i<PF_PIN_SLOTS;i++)if(pad_files.pins[i].token &&
        (pad_files.pins[i].pad==pad || pad_files.pins[i].handle==retained || pad_files.pins[i].handle==queued))return leave(OWN_BUSY);
    pad_files.writers[pad]=(Writer){owner,retained,queued};return leave(OWN_OK);
}
static int32_t change_end(uint32_t pad,uint32_t owner,uint32_t publish) {
    if(!pad_files.coordinator || pad>3 || !owner)return OWN_CONFLICT;
    if(!lock())return OWN_BUSY;
    if(pad_files.writers[pad].owner!=owner)return leave(OWN_CONFLICT);
    if(publish) {
        uint32_t base=0x807348d0u+0x22cu*pad,handle=W(base+4);
        if(W(base)==1 && handle && handle==W(0x80735b24u+20*pad) &&
           *(volatile uint8_t *)handle==0x40)pad_files.revoked&=~(1u<<pad);
    }
    pad_files.writers[pad].owner=0;return leave(OWN_OK);
}
KEEP int32_t pf_change_end(uint32_t pad,uint32_t owner){return change_end(pad,owner,0);}
KEEP int32_t pf_close_begin(uint32_t handle,uint32_t owner,uint32_t *token) {
    if(!pad_files.coordinator || !owner || !token)return OWN_CONFLICT;
    if(!handle){*token=0;return OWN_OK;}
    if(!lock())return OWN_BUSY;
    uint32_t pads=0;Close *slot=0;
    for(uint32_t i=0;i<CLOSE_SLOTS;i++) {
        Close *c=&pad_files.closes[i];
        if(c->token && c->handle==handle)return leave(OWN_BUSY);
        if(!c->token && !slot)slot=c;
    }
    if(!slot)return leave(OWN_BUSY);
    for(uint32_t i=0;i<PF_PIN_SLOTS;i++)if(pad_files.pins[i].token && pad_files.pins[i].handle==handle)return leave(OWN_BUSY);
    for(uint32_t i=0;i<4;i++) {
        Writer *w=&pad_files.writers[i];
        uint32_t linked=W(0x807348d4u+0x22cu*i)==handle || W(0x80735b24u+20*i)==handle ||
            (w->owner && (w->retained==handle || w->queued==handle));
        if(linked) {
            if(w->owner && w->owner!=owner)return leave(OWN_BUSY);
            pads|=1u<<i;
        }
    }
    if(pad_files.sequence==UINT32_MAX)return leave(OWN_FULL);
    *token=++pad_files.sequence;*slot=(Close){handle,owner,*token,pads};
    return leave(OWN_OK);
}
KEEP int32_t pf_close_end(uint32_t handle,uint32_t owner,uint32_t token) {
    if(!pad_files.coordinator || !owner)return OWN_CONFLICT;
    if(!handle && !token)return OWN_OK;
    if(!lock())return OWN_BUSY;
    for(uint32_t i=0;i<CLOSE_SLOTS;i++) {
        Close *c=&pad_files.closes[i];
        if(c->token && c->token==token) {
            if(c->handle!=handle || c->owner!=owner)return leave(OWN_CONFLICT);
            uint32_t pads=c->pads;
            /* A guarded loader can publish a previously unlinked handle while
             * this close is in flight. Pins remain excluded by the close slot;
             * revoke new associations as well before releasing that slot. */
            for(uint32_t p=0;p<4;p++) {
                Writer *w=&pad_files.writers[p];
                if(W(0x807348d4u+0x22cu*p)==handle || W(0x80735b24u+20*p)==handle ||
                   (w->owner && (w->retained==handle || w->queued==handle)))pads|=1u<<p;
            }
            pad_files.revoked|=pads;c->token=0;return leave(OWN_OK);
        }
    }
    return leave(OWN_STALE);
}
static __attribute__((noreturn)) void park(void) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(pad_files.coordinator)od_gate_fail(&pad_files.coordinator->ledger->gate);
    for(;;) {if(pad_files.yield && !ipsr)pad_files.yield();else __asm__ volatile("wfe");}
}
extern int32_t pf_stock_load(uint32_t,uint32_t),pf_stock_unload(uint32_t),pf_stock_close(uint32_t);
static int32_t change(uint32_t pad,uint32_t path,uint32_t load) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(!pad_files.coordinator || ipsr)park();
    uint32_t owner=((uint32_t (*)(void))0x800770e9u)();int32_t s;
    while((s=pf_change_begin(pad,owner))==OWN_BUSY)pad_files.yield();
    if(s)park();
    int32_t result=load?pf_stock_load(pad,path):pf_stock_unload(pad);
    while((s=change_end(pad,owner,load))==OWN_BUSY)pad_files.yield();
    if(s)park();
    return result;
}
KEEP int32_t pf_load(uint32_t pad,uint32_t path){return change(pad,path,1);}
KEEP int32_t pf_unload(uint32_t pad){return change(pad,0,0);}
KEEP int32_t pf_close(uint32_t handle) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(!pad_files.coordinator || ipsr)park();
    uint32_t owner=((uint32_t (*)(void))0x800770e9u)(),token;int32_t s;
    while((s=pf_close_begin(handle,owner,&token))==OWN_BUSY)pad_files.yield();
    if(s)park();
    int32_t result=pf_stock_close(handle);
    while((s=pf_close_end(handle,owner,token))==OWN_BUSY)pad_files.yield();
    if(s)park();
    return result;
}
