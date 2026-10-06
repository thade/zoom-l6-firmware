#include "backing_native.h"
#include <stddef.h>
#define FN(type,address) ((type)((address)|1u))
#define KEEP __attribute__((used,retain))
#define WORD(address) (*(volatile uint32_t *)(address))
extern int32_t bn_raw_snapshot(uint32_t,Pad *);
extern int32_t bn_raw_assign(uint32_t,const uint16_t *,const Pad *);
extern int32_t bn_raw_restore(uint32_t,const Pad *);
extern int32_t bn_raw_save(void);
extern int32_t bn_stock_close(uint32_t);
/* Only one fenced handoff may use native sampler state at a time. */
static BackingNative *owner;
KEEP const uint32_t bn_layout[]={sizeof(BackingNative),offsetof(BackingNative,fault),
    offsetof(BackingNative,uncertain_count),offsetof(BackingNative,uncertain_handles)};
static int installed(void) {
    return WORD(0x8005c1f8u)==0xf000f8dfu &&
           WORD(0x8005c1fcu)==((uint32_t)bn_close_hook|1u);
}
static void retain(BackingNative *s,uint32_t h) {
    s->fault=1;
    for(uint32_t i=0;i<s->uncertain_count;i++)if(s->uncertain_handles[i]==h)return;
    /* Stock has 24 file descriptors. Never overwrite an unresolved identity. */
    if(s->uncertain_count<24)s->uncertain_handles[s->uncertain_count++]=h;
}
KEEP int32_t bn_close_hook(uint32_t h) {
    BackingNative *s=owner;
    if(s && s->fault){retain(s,h);return -1;}
    int32_t r=bn_stock_close(h);
    if(s && r)retain(s,h);
    return r;
}
static int ready(BackingNative *s) {
    return s && owner==s && s->held && !s->fault && installed();
}
static int32_t enter(void *ctx) {
    BackingNative *s=ctx;
    if(s->fault || !installed())return BP_UNCERTAIN;
    if(owner)return BP_BUSY;
    int32_t r=s->gate.enter(s->gate.context);
    if(r==BP_OK){s->held=1;owner=s;}
    return r;
}
static int32_t leave(void *ctx) {
    BackingNative *s=ctx;
    if(!ready(s))return BP_UNCERTAIN;
    /* leave may admit another task before returning. Close interception must
     * already be ordinary pass-through when that task starts. */
    owner=0;
    int32_t r=s->gate.leave(s->gate.context);
    if(r==BP_OK)s->held=0;
    else {s->fault=1;owner=s;}
    return r;
}
static int32_t seal(void *ctx,const uint16_t *from,const uint16_t *to) {
    BackingNative *s=ctx;
    if(!ready(s))return BP_UNCERTAIN;
    int32_t r=s->gate.seal(s->gate.context,from,to);
    return s->fault?BP_UNCERTAIN:r;
}
static int32_t snapshot(void *ctx,uint32_t pad,Pad *out) {
    if(!ready(ctx))return BP_UNCERTAIN;
    return bn_raw_snapshot(pad,out)?BP_SAFE:BP_OK;
}
static int32_t insert(void *ctx,uint32_t pad,const uint16_t *path) {
    if(!ready(ctx))return BP_UNCERTAIN;
    return FN(int32_t (*)(uint32_t,const uint16_t *,uint32_t),0x80008dd8)(pad,path,0)?BP_SAFE:BP_OK;
}
/* Temporarily replace ONLY this stopped pad's prefetch callback. The native
 * prefetch requests the exact remaining bytes (including the final partial
 * block). Public read is synchronous, so no file-task request can outlive it.
 * Stock conversion ignores callback results: clear failed input, record the
 * failure, and reject the entire load before playback can be admitted. */
static void read_initial(uint32_t pad,void *buffer,uint32_t bytes) {
    BackingNative *s=owner;uint32_t actual=0;
    if(!s)return; /* Impossible with the callback installed under the gate. */
    if(!ready(s) || pad!=s->pad || !bytes || bytes>0x46a00u ||
       (uint32_t)buffer<0x80735b80u ||
       (uint64_t)(uint32_t)buffer+bytes>0x80735b80ull+0x46a00u) {
        s->fault=1;return;
    }
    uint32_t h=FN(uint32_t (*)(uint32_t),0x80036318)(pad);
    int32_t r=h?FN(int32_t (*)(uint32_t,void *,uint32_t,uint32_t *),0x80060620)
        (h,buffer,bytes,&actual):-1;
    s->reads++;
    if(r || actual!=bytes) {
        s->read_bad=1;
        uint8_t *p=buffer;for(uint32_t i=0;i<bytes;i++)p[i]=0;
    }
}
static int32_t load(BackingNative *s,uint32_t pad,const uint16_t *path,const Pad *prior) {
    if(!ready(s))return BP_UNCERTAIN;
    if(pad>=4 || !prior)return BP_SAFE;
    volatile uint32_t *callback=(volatile uint32_t *)(0x80735180u+pad*0x224u+0x32cu);
    uint32_t original=*callback;
    if(original!=0x80036209u){s->fault=1;return BP_UNCERTAIN;}
    s->pad=pad;s->reads=0;s->read_bad=0;
    *callback=(uint32_t)read_initial;
    int32_t r=path?bn_raw_assign(pad,path,prior):bn_raw_restore(pad,prior);
    if(*callback!=(uint32_t)read_initial)s->fault=1;
    *callback=original;
    if(s->fault)return BP_UNCERTAIN;
    if(r || s->read_bad || ((path || prior->path[0]) && !s->reads))return BP_SAFE;
    return BP_OK;
}
static int32_t assign(void *ctx,uint32_t pad,const uint16_t *path,const Pad *prior) {
    if(!path || !path[0])return BP_SAFE;
    return load(ctx,pad,path,prior);
}
static int32_t restore(void *ctx,uint32_t pad,const Pad *prior) {
    return load(ctx,pad,0,prior);
}
static int32_t save(void *ctx) {
    BackingNative *s=ctx;if(!ready(s))return BP_UNCERTAIN;
    int32_t r=bn_raw_save();
    return s->fault?BP_UNCERTAIN:r?BP_SAFE:BP_OK;
}
KEEP int32_t bn_init(BackingNative *s,const BackingGate *gate,BackingPort *out) {
    if(!s || !gate || !out || !gate->context || !gate->enter || !gate->leave || !gate->seal ||
       owner || !installed())return BP_SAFE;
    const uint8_t *raw=(const uint8_t *)s;
    for(uint32_t i=0;i<sizeof(*s);i++)if(raw[i])return BP_SAFE;
    s->gate=*gate;
    *out=(BackingPort){s,enter,leave,seal,snapshot,insert,assign,restore,save};
    return BP_OK;
}
