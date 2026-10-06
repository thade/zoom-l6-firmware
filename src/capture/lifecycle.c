/* Offline lifecycle. APIs require serialized worker access. Start/stop/cancel
 * require the caller to quiesce BOTH producer and consumer. No installed fence
 * or ordinary-recorder start/stop hook exists. No pad mutation occurs here. */
#include "capture.h"
#include <stddef.h>
#include "retention.h"
typedef int32_t (*Open)(uint32_t*,const uint16_t*,uint32_t,uint32_t);
typedef int32_t (*Transfer)(uint32_t,void*,uint32_t,uint32_t*);
typedef int32_t (*Close)(uint32_t);
typedef int32_t (*Seek)(uint32_t,int32_t,uint32_t);
typedef int32_t (*Info)(uint32_t,uint32_t*);
#define OPEN ((Open)0x8005ffe9u)
#define WRITE ((Transfer)0x800622b1u)
#define READ ((Transfer)0x80060621u)
#define CLOSE ((Close)0x8005c1f9u)
#define SEEK ((Seek)0x8005f169u)
#define INFO ((Info)0x8005ef41u)
enum { IDLE,ARMED,CAPTURING,DRAINING,FINALIZING,VERIFYING,VERIFIED,FAILED };
enum { DONE=0,MORE=10,BUSY=11,INVALID=12,ERROR=13,COLLISION=14,CORRUPT=15,CANCELLED=16 };
typedef struct {
    uint32_t phase,handle,error,uncertain_close,pad,serial,left,hash;
    uint16_t path[261];
    uint8_t header[512];
    uint32_t naming;
} Life;
KEEP const uint32_t life_layout[]={sizeof(Life),offsetof(Life,path),offsetof(Life,header)};
static int same(const uint8_t *a,const uint8_t *b,uint32_t n) {
    while(n--)if(*a++!=*b++)return 0;return 1;
}
static void u32(uint8_t *p,uint32_t v) {for(uint32_t i=0;i<4;i++)p[i]=(uint8_t)(v>>(i*8));}
static void tag(uint8_t *p,const char *s) {for(uint32_t i=0;i<4;i++)p[i]=(uint8_t)s[i];}
static void header(Life *s,uint32_t bytes) {
    for(uint32_t i=0;i<512;i++)s->header[i]=0;
    tag(s->header,"RIFF");u32(s->header+4,bytes+504);tag(s->header+8,"WAVE");
    tag(s->header+12,"fmt ");u32(s->header+16,16);
    s->header[20]=3;s->header[22]=2;u32(s->header+24,48000);u32(s->header+28,384000);
    s->header[32]=8;s->header[34]=32;tag(s->header+36,"JUNK");u32(s->header+40,460);
    tag(s->header+504,"data");u32(s->header+508,bytes);
}
static int close_file(Life *s) {
    if(!s->handle)return 0;
    uint32_t h=s->handle;s->handle=0;
    if(CLOSE(h)){s->uncertain_close=1;return 1;}return 0;
}
static uint32_t fail(Life *s,uint32_t reason) {
    s->error=reason;s->phase=FAILED;
    if(close_file(s))s->error=ERROR;
    return s->error;
}
static int transfer(Transfer fn,uint32_t handle,void *p,uint32_t n) {
    uint32_t actual=0;return fn(handle,p,n,&actual)!=0 || actual!=n;
}
/* A zero-initialized, unused Life and quiescent Capture are required. Failed
 * instances cannot be restarted without an external resource/recovery audit. */
KEEP uint32_t life_prepare(Life *s,Capture *c,uint32_t pad,uint32_t serial) {
    if(s->phase!=IDLE)return BUSY;
    if(pad>3)return INVALID;
    extra_init(c,0);extra_stop_quiesced(c);
    if(!s->naming){s->pad=pad;s->serial=serial;s->naming=1;}
    else if(s->pad!=pad)return INVALID;
    const char *prefix="A:\\SOUND_PAD\\PAD1\\OD_";uint32_t n=0;
    while(prefix[n]){s->path[n]=(uint16_t)prefix[n];n++;}
    s->path[16]=(uint16_t)('1'+pad);
    for(uint32_t tries=0;tries<32;tries++) {
        const char *hex="0123456789ABCDEF";
        for(uint32_t i=0;i<8;i++)s->path[n+i]=(uint16_t)hex[(s->serial>>(28-i*4))&15];
        const char *ext=".WAV";
        for(uint32_t i=0;i<5;i++)s->path[n+8+i]=(uint16_t)ext[i];
#ifdef L6_CAPTURE_PRIVATE_FILES
        /* On reboot, skip both completed WAVs and abandoned TMPs. Probe the
         * final name read-only; only the known not-found result permits create.
         * No startup directory scan, deletion or persistent counter required. */
        int32_t existing=OPEN(&s->handle,s->path,0,0x100);
        if(!existing) {
            if(close_file(s))return fail(s,ERROR);
            if(s->serial==UINT32_MAX)return fail(s,COLLISION);
            s->serial++;
            if(tries==31)return MORE;
            continue;
        }
        if(s->handle || (uint32_t)existing!=0xffffd75au)return fail(s,ERROR);
        s->path[n+9]='T';s->path[n+10]='M';s->path[n+11]='P';
#endif
        int32_t status=OPEN(&s->handle,s->path,0x501,0x80);
        if(!status)break;
        /* The verified stock public open contract clears handle on error. */
        if(s->handle)return fail(s,ERROR);
        if((uint32_t)status!=0xffffd75bu)return fail(s,ERROR);
        if(s->serial==0xffffffffu)return fail(s,COLLISION);
        s->serial++;
        if(tries==31) {
#ifdef L6_CAPTURE_PRIVATE_FILES
            return MORE;
#else
            return fail(s,COLLISION);
#endif
        }
    }
    if(!s->handle)return fail(s,ERROR);
    header(s,0);
    if(transfer(WRITE,s->handle,s->header,512))return fail(s,ERROR);
    extra_init(c,s->handle);extra_stop_quiesced(c);
    s->phase=ARMED;return DONE;
}
KEEP uint32_t life_start_quiesced(Life *s,Capture *c) {
    if(s->phase!=ARMED)return INVALID;
    extra_init(c,s->handle);s->phase=CAPTURING;return DONE;
}
KEEP uint32_t life_stop_quiesced(Life *s,Capture *c) {
    if(s->phase!=CAPTURING)return INVALID;
    extra_stop_quiesced(c);s->phase=DRAINING;return DONE;
}
KEEP uint32_t life_cancel_quiesced(Life *s,Capture *c) {
    if(s->phase==VERIFIED || s->phase==FAILED || s->phase==IDLE)return INVALID;
    extra_stop_quiesced(c);
    __atomic_store_n(&c->fault,4,__ATOMIC_RELEASE);
    c->handle=0;return fail(s,CANCELLED);
}
/* A late rejected event can arrive while readback finishes. Revoke eligibility
 * of an already closed file without pretending to undo its disk contents. */
KEEP uint32_t life_revoke_quiesced(Life *s,Capture *c) {
    if(s->phase!=VERIFIED)return INVALID;
    extra_invalidate_quiesced(c);s->phase=FAILED;s->error=CANCELLED;return CANCELLED;
}
/* Each call performs at most one 4-KiB payload write/read. Final header/open/info
 * operations are bounded, but physical SD latency remains outside this proof. */
KEEP uint32_t life_step(Life *s,Capture *c) {
    if(s->phase==VERIFIED)return DONE;
    if(s->phase==FAILED)return s->error;
    if(s->phase==DRAINING) {
        uint32_t r=extra_drain(c);
        if(r==0)return MORE;
        if(r!=1 || !extra_ready(c))return fail(s,ERROR);
        s->phase=FINALIZING;return MORE;
    }
    if(s->phase==FINALIZING) {
        /* Staging is stopped and fully drained before FINALIZING. The same
         * serialized worker owns it through readback; retain counters/hash. */
        uint8_t *buffer=(uint8_t*)c->blocks;
        header(s,c->bytes);
        if(SEEK(s->handle,0,2) || transfer(WRITE,s->handle,s->header,512))return fail(s,ERROR);
        if(close_file(s))return fail(s,ERROR);
        c->handle=0;
        if(OPEN(&s->handle,s->path,0,0x100))return fail(s,ERROR);
        uint32_t info[4]={0};
        if(INFO(s->handle,info) || info[0]!=c->bytes+512)return fail(s,CORRUPT);
        if(transfer(READ,s->handle,buffer,512) || !same(buffer,s->header,512))return fail(s,CORRUPT);
        s->left=c->bytes;s->hash=2166136261u;s->phase=VERIFYING;return MORE;
    }
    if(s->phase==VERIFYING) {
        uint8_t *buffer=(uint8_t*)c->blocks;
        uint32_t n=s->left>sizeof(c->blocks)?sizeof(c->blocks):s->left;
        if(n) {
            if(transfer(READ,s->handle,buffer,n))return fail(s,CORRUPT);
            s->hash=extra_hash(s->hash,buffer,n);s->left-=n;
            if(s->left)return MORE;
        }
        if(s->hash!=c->hash)return fail(s,CORRUPT);
        if(close_file(s))return fail(s,ERROR);
        s->phase=VERIFIED;return DONE;
    }
    return BUSY;
}
/* Eligibility token only. Assignment still requires the separate pad lifetime
 * gate, checked catalogue update, loader readback and settings persistence. */
KEEP const uint16_t *life_verified_path(const Life *s) {
    return s->phase==VERIFIED?s->path:0;
}
/* Manager queries: serialized with this Life's worker; no IO. */
KEEP uint32_t life_is_prepared(const Life *s) {
    return s->phase==ARMED && s->handle && !s->uncertain_close;
}
KEEP uint32_t life_copy_verified(const Life *s,uint16_t *out,uint32_t capacity) {
    if(s->phase!=VERIFIED || s->handle || s->uncertain_close || !out)return INVALID;
    uint32_t n=0;while(n<261 && s->path[n])n++;
    if(n==261 || capacity<=n)return INVALID;
    for(uint32_t i=0;i<=n;i++)out[i]=s->path[i];return DONE;
}
KEEP uint32_t life_resources_released(const Life *s) {
    return (s->phase==FAILED || s->phase==VERIFIED) && !s->handle && !s->uncertain_close;
}
KEEP uint32_t life_current_serial(const Life *s) {return s->serial;}
