#include "reload_manager.h"
#define KEEP __attribute__((used,retain))
#define FN(type, address) ((type)((address)|1u))
extern int32_t od_stock_snapshot(uint32_t,Pad *);
static int lock(RmManager *m) {
    uint32_t z=0;return __atomic_compare_exchange_n(&m->lock,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t done(RmManager *m,int32_t r){__atomic_store_n(&m->lock,0,__ATOMIC_RELEASE);return r;}
static int equal(const uint16_t *a,const uint16_t *b) {
    for(uint32_t i=0;i<OD_PATH;i++){if(a[i]!=b[i])return 0;if(!a[i])return 1;}return 0;
}
static int valid(const RmPlan *p) {
    const uint16_t empty[]={'N','O',' ','A','S','S','I','G','N',0};
    for(uint32_t i=0;i<0x60;i++)if(p->settings[i]!=((const uint8_t *)0x800a202e)[i])return 0;
    for(uint32_t i=0;i<4;i++) {
        const Pad *a=&p->pads[i];const uint8_t *b=p->settings+0x60;
        if(!equal(a->path[0]?a->path:empty,(const uint16_t *)(b+i*0x20a)) ||
           b[0x828+i]!=!!a->path[0] || b[0x82c+i]!=a->mode || b[0x830+i]!=a->level ||
           a->opaque[0]>255 || a->opaque[1] || a->opaque[2] || a->opaque[3])return 0;
    }
    return 1;
}
KEEP int32_t rm_init(RmManager *m,RtRuntime *r,RtProducer *p,const RmPort *port) {
    if(!m || m->runtime || !r || !r->coordinator || !p || !port || !port->fenced)return OWN_CONFLICT;
    m->runtime=r;m->producer=p;m->port=port;return OWN_OK;
}
KEEP int32_t rm_start(RmManager *m,const RmPlan *p,uint32_t parent) {
    if(!m || !m->runtime || !p)return OWN_CONFLICT;
    if(!lock(m))return OWN_BUSY;
    if(m->phase!=RM_IDLE && m->phase!=RM_DONE)return done(m,OWN_BUSY);
    if(m->producer->owner || m->port->fenced()!=1 || !valid(p))return done(m,OWN_CONFLICT);
    /* Own the intended result before the producer can mutate anything. */
    uint8_t *dst=(uint8_t *)&m->plan;const uint8_t *src=(const uint8_t *)p;
    for(uint32_t i=0;i<sizeof(*p);i++)dst[i]=src[i];
    m->parent=parent;m->owner=0;m->error=0;m->phase=RM_ACQUIRE;
    return done(m,OWN_OK);
}
/* Public wrappers execute here, with their complete return codes checked.
 * This is synchronous read-only work under the sealed manager owner, not a
 * masquerading worker/UI continuation. Close attempted exactly once on all
 * paths after a successful open. No repair write and no convenience saver. */
KEEP int32_t od_stock_check_settings(const uint8_t *expected) {
    const uint16_t path[]={'A',':','\\','S','O','U','N','D','_','P','A','D','\\',
        'L','6','P','A','D','S','E','T','T','I','N','G','.','Z','S','T',0};
    uint32_t h=0,info[4]={0},actual=0;int32_t bad=1;
    if(FN(int32_t (*)(uint32_t *,const uint16_t *,uint32_t,uint32_t),0x8005ffe8)(&h,path,0,0x100))return 1;
    if(FN(int32_t (*)(uint32_t,uint32_t *),0x8005ef40)(h,info) || info[0]!=RM_SETTINGS)goto close;
    uint8_t buf[128];uint32_t end[4];
    for(uint32_t p=0;p<4;p++) {
        end[p]=0x60+p*0x20a;
        while(end[p]<0x60+(p+1)*0x20a) {
            uint32_t at=end[p];end[p]+=2;if(!expected[at] && !expected[at+1])break;
        }
    }
    for(uint32_t pos=0;pos<RM_SETTINGS;) {
        uint32_t n=RM_SETTINGS-pos;if(n>sizeof(buf))n=sizeof(buf);actual=0;
        if(FN(int32_t (*)(uint32_t,void *,uint32_t,uint32_t *),0x80060620)(h,buf,n,&actual) || actual!=n)goto close;
        for(uint32_t i=0;i<n;i++) {
            uint32_t at=pos+i,ignore=0;
            for(uint32_t p=0;p<4;p++)if(at>=end[p] && at<0x60+(p+1)*0x20a)ignore=1;
            if(!ignore && buf[i]!=expected[at])goto close;
        }
        pos+=n;
    }
    bad=0;
close:
    if(FN(int32_t (*)(uint32_t),0x8005c1f8)(h))bad=1;
    return bad;
}
KEEP int32_t rm_step(RmManager *m) {
    if(!m || !m->runtime)return OWN_CONFLICT;
    if(!lock(m))return OWN_BUSY;
    if(m->phase==RM_IDLE || m->phase==RM_DONE)return done(m,OWN_OK);
    if(m->phase==RM_FAILED)return done(m,OWN_FAULT);
    int32_t r=OWN_BUSY;RlCoordinator *c=m->runtime->coordinator;
    if(m->port->fenced()!=1 || __atomic_load_n(&c->ledger->gate.word,__ATOMIC_ACQUIRE)&OD_GATE_FAILED){r=OWN_FAULT;goto failure;}
    if(m->phase==RM_ACQUIRE) {
        r=rl_manage_begin(c,(uint32_t)m);if(r)goto failure;m->phase=RM_START;
    }
    if(m->phase==RM_START) {
        r=rt_produce_managed(m->runtime,m->producer,m->parent,(uint32_t)m);
        m->owner=m->producer->owner;if(r)goto failure;m->phase=RM_WAIT;
    }
    if(m->phase==RM_WAIT) {
        r=rl_seal(c,(uint32_t)m,m->owner);if(r)goto failure;m->phase=RM_CHECK;
    }
    if(m->phase==RM_CHECK) {
        Pad observed;
        for(uint32_t i=0;i<4;i++) {
            const Pad *p=&m->plan.pads[i];
            if(od_stock_snapshot(i,&observed) || !equal(observed.path,p->path) ||
               observed.mode!=p->mode || observed.level!=p->level || observed.opaque[0]!=p->opaque[0]) {
                m->error=0xffff1001;r=OWN_FAULT;goto failure;
            }
        }
        if(od_stock_check_settings(m->plan.settings)){m->error=0xffff1002;r=OWN_FAULT;goto failure;}
        /* The retained exclusion and sealed root make evidence stable while
         * metadata retirement retries; do not rerun successful file work. */
        if(m->port->fenced()!=1){r=OWN_FAULT;goto failure;}
        m->phase=RM_VERIFY;
    }
    if(m->phase==RM_VERIFY) {
        r=rl_verify(c,m->owner,RL_VERIFIED);if(r)goto failure;m->phase=RM_RETIRE;
    }
    if(m->phase==RM_RETIRE) {
        r=rt_retire(m->runtime,m->producer);if(r)goto failure;m->phase=RM_RELEASE;
    }
    if(m->phase==RM_RELEASE) {
        r=rl_manage_end(c,(uint32_t)m);if(r)goto failure;m->phase=RM_DONE;
    }
    return done(m,OWN_OK);
failure:
    if(r!=OWN_BUSY) {
        if(!m->error)m->error=(uint32_t)r;
        od_gate_fail(&c->ledger->gate);m->phase=RM_FAILED;return done(m,OWN_FAULT);
    }
    return done(m,OWN_BUSY);
}
KEEP int32_t rm_completed(RmManager *m) {
    if(!m || !m->runtime)return OWN_CONFLICT;
    if(!lock(m))return OWN_BUSY;
    int32_t r=m->phase==RM_DONE?OWN_OK:m->phase==RM_FAILED?OWN_FAULT:OWN_BUSY;
    return done(m,r);
}
KEEP const uint32_t rm_layout[]={sizeof(RmManager),sizeof(RmPlan),sizeof(RmPort)};
