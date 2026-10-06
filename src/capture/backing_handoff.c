#include "backing_handoff.h"
#include <stddef.h>
#define KEEP __attribute__((used,retain))
KEEP const uint32_t backing_layout[]={sizeof(BackingHandoff),offsetof(BackingHandoff,error),
    offsetof(BackingHandoff,fault),offsetof(BackingHandoff,last_session)};
static int same(const void *a,const void *b,uint32_t n) {
    const uint8_t *x=a,*y=b;while(n--)if(*x++!=*y++)return 0;return 1;
}
static int path_equal(const uint16_t *a,const uint16_t *b) {
    for(uint32_t i=0;i<OD_PATH;i++){if(a[i]!=b[i])return 0;if(!a[i])return 1;}return 0;
}
static int observed(BackingHandoff *s,const uint16_t *path) {
    int32_t r=s->port.snapshot(s->port.context,s->pad,&s->observed);
    if(r!=BP_OK)return r==BP_SAFE?BP_SAFE:BP_UNCERTAIN;
    return path_equal(s->observed.path,path) && same(&s->before.mode,&s->observed.mode,24)?BP_OK:BP_SAFE;
}
KEEP int32_t backing_init(BackingHandoff *s,SessionManager *m,const BackingPort *p,uint32_t pad) {
    if(!s || !m || !p || !p->context || !p->seal || pad>3 || m->pad!=pad)return OD_INVALID;
    if(!manager_storage_disjoint(m,m->descriptor,(uint32_t)s,sizeof(*s)))return OD_INVALID;
    const uint8_t *raw=(const uint8_t*)s;
    for(uint32_t i=0;i<sizeof(*s);i++)if(raw[i])return OD_INVALID;
    if(!p->enter || !p->leave || !p->insert || !p->snapshot ||
       !p->assign || !p->restore || !p->save)return OD_INVALID;
    uint32_t r=manager_bind_publication(m,(uint32_t)s);
    if(r)return r==11?OD_BUSY:OD_INVALID;
    s->manager=m;s->port=*p;s->pad=pad;return OD_OK;
}
static int32_t worker_step(void *context){return backing_step(context);}
KEEP int32_t backing_attach_worker(BackingHandoff *s,NativeWorker *w) {
    uint32_t ipsr;__asm__ volatile("mrs %0, ipsr":"=r"(ipsr));
    if(!s || !w || ipsr || *(volatile uint32_t*)0x801f9048u ||
       __atomic_load_n(&w->state,__ATOMIC_ACQUIRE)!=W_WAITING || w->handoff ||
       !s->manager || w->manager!=s->manager || s->manager->publication_owner!=(uint32_t)s ||
       !manager_storage_disjoint(s->manager,s->manager->descriptor,(uint32_t)s,sizeof(*s)))return OD_INVALID;
    uint64_t a=(uint32_t)s,b=(uint32_t)w;
    if(a<b+sizeof(*w) && b<a+sizeof(*s))return OD_INVALID;
    w->handoff=worker_step;w->handoff_context=s;return OD_OK;
}
static int final_path(BackingHandoff *s,const ManagerResult *r) {
    const char *prefix="A:\\SOUND_PAD\\PAD";
    uint32_t n=0;while(n<OD_PATH && r->path[n])n++;
    /* Exact generated name; never accept a foreign folder or traversal. */
    if(n!=33)return 0;
    for(uint32_t i=0;prefix[i];i++)if(r->path[i]!=(uint8_t)prefix[i])return 0;
    if(r->path[16]!='1'+s->pad || r->path[17]!='\\' || r->path[18]!='O' ||
       r->path[19]!='D' || r->path[20]!='_')return 0;
    for(uint32_t i=21;i<29;i++)if(!((r->path[i]>='0' && r->path[i]<='9') ||
                                                 (r->path[i]>='A' && r->path[i]<='F')))return 0;
    if(r->path[29]!='.' || r->path[30]!='T' || r->path[31]!='M' || r->path[32]!='P')return 0;
    for(uint32_t i=0;i<=n;i++)s->completed[i]=r->path[i];
    s->completed[30]='W';s->completed[31]='A';s->completed[32]='V';return 1;
}
typedef struct {BackingHandoff *state;int32_t result;} Visit;
static void publish(const ManagerResult *results,uint32_t head,uint32_t count,void *opaque) {
    Visit *v=opaque;BackingHandoff *s=v->state;const BackingPort *p=&s->port;void *ctx=p->context;
    if(!count || count>4 || head>3){v->result=OD_INVALID;return;}
    const ManagerResult *r=&results[(head+3)&3];
    if(!r->session || r->session!=s->manager->session || !final_path(s,r)) {
        v->result=OD_INVALID;return;
    }
    if(r->session==s->last_session){v->result=OD_SKIPPED;return;}
    int32_t result=p->enter(ctx);
    if(result!=BP_OK) {
        v->result=result==BP_BUSY?OD_BUSY:result==BP_SAFE?OD_IO:OD_FAULT;return;
    }
    int32_t status=OD_ASSIGN;
    result=p->snapshot(ctx,s->pad,&s->before);
    if(result!=BP_OK){if(result!=BP_SAFE)status=OD_FAULT;goto done;}
    result=p->seal(ctx,r->path,s->completed);
    if(result!=BP_OK){status=result==BP_SAFE?OD_IO:OD_FAULT;goto done;}
    result=p->insert(ctx,s->pad,s->completed);
    if(result!=BP_OK){status=result==BP_SAFE?OD_CATALOGUE:OD_FAULT;goto done;}
    status=OD_ASSIGN;
    result=p->assign(ctx,s->pad,s->completed,&s->before);
    if(result==BP_OK)result=observed(s,s->completed);
    if(result!=BP_OK){if(result!=BP_SAFE){status=OD_FAULT;goto done;}goto rollback;}
    status=OD_PERSIST;
    result=p->save(ctx);
    if(result!=BP_OK){if(result!=BP_SAFE){status=OD_FAULT;goto done;}goto rollback;}
    s->last_session=r->session;status=OD_OK;goto done;
rollback:
    if(p->restore(ctx,s->pad,&s->before)!=BP_OK || observed(s,s->before.path)!=BP_OK ||
       p->save(ctx)!=BP_OK)status=OD_FAULT;
done:
    /* No deletion: a sealed but unselected take stays recoverable on disk.
     * Never retry this take automatically after a safe publication failure. */
    if(status!=OD_FAULT && p->leave(ctx)!=BP_OK)status=OD_FAULT;
    if(status==OD_FAULT)s->fault=1;
    v->result=status;
}
KEEP int32_t backing_step(BackingHandoff *s) {
    if(!s || !s->manager)return OD_INVALID;
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&s->busy,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return OD_BUSY;
    int32_t status=OD_BUSY;
    if(s->fault){status=OD_FAULT;goto out;}
    if(__atomic_load_n(&s->manager->cancel,__ATOMIC_ACQUIRE) && s->held!=2) {
        s->error=OD_CANCELLED;
        if(!s->held) {
            uint32_t r=manager_skip_publication(s->manager,(uint32_t)s);
            status=r==11?OD_BUSY:r?OD_INVALID:OD_CANCELLED;goto out;
        }
        /* BUSY enter left no fence/reservations; nothing was published. */
        s->held=2;
    }
    if(!s->held) {
        uint32_t r=manager_hold_publication(s->manager,(uint32_t)s);
        if(r){status=r==11?OD_BUSY:OD_INVALID;goto out;}
        s->held=1;s->error=0;
    }
    if(s->held==1) {
        Visit visit={s,OD_INVALID};
        uint32_t r=manager_visit_held_results(s->manager,(uint32_t)s,publish,&visit);
        status=r==11?OD_BUSY:r?OD_FAULT:visit.result;
        if(status==OD_BUSY)goto out;
        s->error=(uint32_t)status;
        if(status==OD_FAULT){s->fault=1;goto out;}
        s->held=2;
    }
    /* Release contention retries only the release, never seal/assign/save. */
    uint32_t r=manager_release_publication(s->manager,(uint32_t)s);
    if(r){status=r==11?OD_BUSY:OD_FAULT;if(status==OD_FAULT)s->fault=1;goto out;}
    s->held=0;status=(int32_t)s->error;
out:
    __atomic_store_n(&s->busy,0,__ATOMIC_RELEASE);return status;
}
