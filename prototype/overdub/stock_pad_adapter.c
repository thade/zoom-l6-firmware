#include "overdub.h"

/* Version-specific, offline-tested bindings. Caller must supply exclusion.
 * Sample loading still depends on the device's audio/SD subsystems. */
#define FN(type, address) ((type)((address)|1u))
#define KEEP __attribute__((used, retain))
static int equal(const uint16_t *a,const uint16_t *b) {
    for (uint32_t i=0;i<OD_PATH;i++) {if (a[i]!=b[i]) return 0;if (!a[i]) return 1;}return 0;
}
static int copy_path(uint16_t *out,const uint16_t *in) {
    for(uint32_t i=0;i<OD_PATH;i++){out[i]=in[i];if(!in[i])return 0;}return 1;
}
static uint32_t get(uint32_t address,uint32_t pad) {
    return FN(uint32_t (*)(uint32_t),address)(pad);
}
KEEP int32_t od_stock_snapshot(uint32_t pad,Pad *out) {
    if(pad>=4 || !out)return 1;
    const uint16_t *path=(const uint16_t *)get(0x80006200,pad);
    uint32_t assigned=get(0x800061f0,pad),loaded=get(0x800362b8,pad);
    int empty=!path[0] || equal(path,(const uint16_t *)0x800a3306);
    if(empty) {if(assigned || loaded)return 1;out->path[0]=0;}
    else {
        if(assigned!=1 || loaded!=1 || !get(0x80036318,pad) ||
           !equal(path,(const uint16_t *)(0x807348d0+pad*0x22c+0x20)) || copy_path(out->path,path))return 1;
    }
    out->mode=get(0x80006238,pad);
    out->level=get(0x80006218,pad); /* Native byte encoding, no level conversion. */
    out->opaque[0]=get(0x80006228,pad); /* Preserve adjacent per-pad byte. */
    out->opaque[1]=out->opaque[2]=out->opaque[3]=0;
    return 0;
}
static int options_equal(const Pad *a,const Pad *b) {
    return a->mode==b->mode && a->level==b->level && a->opaque[0]==b->opaque[0];
}
KEEP int32_t od_stock_assign(uint32_t pad,const uint16_t *path,const Pad *prior) {
    if(pad>=4 || !path || !prior || !path[0])return 1;
    const uint16_t *name=FN(const uint16_t *(*)(const uint16_t *),0x8000be20)(path);
    int32_t index=FN(int32_t (*)(uint32_t,const uint16_t *),0x80008ec0)(pad,name);
    if(index<0)return 1;
    const uint16_t *resolved=FN(const uint16_t *(*)(uint32_t,uint32_t),0x80008e88)(pad,(uint32_t)index);
    if(!equal(path,resolved))return 1; /* Never silently select a same-basename file elsewhere. */
    uint32_t count=get(0x80008ee8,pad);
    if(FN(int32_t (*)(const uint16_t *,uint32_t,uint32_t,uint32_t,uint32_t),0x8004b760)
        (path,pad,(uint32_t)index,count,0))return 1;
    Pad observed;
    if(od_stock_snapshot(pad,&observed) || !equal(observed.path,path) || !options_equal(&observed,prior))return 1;
    return 0;
}
KEEP int32_t od_stock_restore(uint32_t pad,const Pad *prior) {
    if(pad>=4 || !prior)return 1;
    /* Assignment should not change these bytes. Do not guess how to repair
     * unrelated runtime parameter state if another actor changed them. */
    if(get(0x80006238,pad)!=prior->mode || get(0x80006218,pad)!=prior->level ||
       get(0x80006228,pad)!=prior->opaque[0])return 1;
    if(prior->path[0])return od_stock_assign(pad,prior->path,prior);
    FN(void (*)(uint32_t),0x800096f8)(pad);
    FN(void (*)(uint32_t,const uint16_t *),0x800069a8)(pad,(const uint16_t *)0x800a3306);
    Pad observed;
    return od_stock_snapshot(pad,&observed) || observed.path[0] || !options_equal(&observed,prior);
}
KEEP int32_t od_stock_save(void) {
    /* The convenience saver updates its comparison cache BEFORE the disk write.
     * Write every attempt through checked wrappers, then verify readback. A
     * failed save cannot become a no-op on retry. Not atomic crash-safe storage. */
    FN(void (*)(const void *),0x80034318)((const void *)0x80441560);
    const uint16_t path[]={'A',':','\\','S','O','U','N','D','_','P','A','D','\\',
        'L','6','P','A','D','S','E','T','T','I','N','G','.','Z','S','T',0};
    uint32_t h=0,info[4]={0},actual=0;
    int32_t bad=1;
    int32_t status=FN(int32_t (*)(uint32_t *,const uint16_t *,uint32_t,uint32_t),0x8005ffe8)(&h,path,1,0x80);
    if((uint32_t)status==0xffffd75a)
        status=FN(int32_t (*)(uint32_t *,const uint16_t *,uint32_t,uint32_t),0x8005ffe8)(&h,path,0x101,0x80);
    if(status)return 1;
    status=FN(int32_t (*)(uint32_t,const void *,uint32_t,uint32_t *),0x800622b0)
        (h,(const void *)0x800a202e,0x60,&actual);
    if(!status && actual==0x60) {
        status=FN(int32_t (*)(uint32_t,const void *,uint32_t,uint32_t *),0x800622b0)
            (h,(const void *)0x80445524,0x1034,&actual);
        bad=status || actual!=0x1034;
    }
    if(FN(int32_t (*)(uint32_t),0x8005c1f8)(h))bad=1;
    h=0;
    if(bad)return 1;
    bad=1;
    if(FN(int32_t (*)(uint32_t *,const uint16_t *,uint32_t,uint32_t),0x8005ffe8)(&h,path,0,0x100))return 1;
    if(FN(int32_t (*)(uint32_t,uint32_t *),0x8005ef40)(h,info) || info[0]!=0x1094)goto done;
    uint8_t buf[128];
    for(uint32_t pos=0;pos<0x1094;) {
        uint32_t n=0x1094-pos;if(n>sizeof(buf))n=sizeof(buf);
        if(FN(int32_t (*)(uint32_t,void *,uint32_t,uint32_t *),0x80060620)(h,buf,n,&actual) || actual!=n)goto done;
        for(uint32_t i=0;i<n;i++) {
            uint32_t at=pos+i;
            const uint8_t *expected=(const uint8_t *)(at<0x60?0x800a202e + at:0x80445524+at-0x60);
            if(buf[i]!=*expected)goto done;
        }
        pos+=n;
    }
    bad=0;
done:
    if(FN(int32_t (*)(uint32_t),0x8005c1f8)(h))bad=1;
    return bad;
}
