/* Offline worker manager. One serialized worker owns this instance and all
 * bridge/file steps; callers may atomically request cancellation. No UI/RTOS
 * task registration, pad assignment or wall-clock timeout is supplied here. */
#include "session_manager.h"
#include "capture.h"
#include "exchange.h"
#include <stddef.h>
#include "retention.h"
#ifdef L6_CAPTURE_STORAGE_LEASE
#include "storage_lease.h"
extern uint32_t bridge_close_storage(void*,uint32_t);
#endif
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
static SessionManager *manager_owner;
KEEP const uint32_t manager_layout[]={sizeof(SessionManager),offsetof(SessionManager,state),
 offsetof(SessionManager,error),offsetof(SessionManager,session),offsetof(SessionManager,count),
 offsetof(SessionManager,results),sizeof(ManagerResult)};
extern const uint32_t ct_layout[],rr_layout[],bridge_layout[],exchange_layout[],life_layout[];
extern uint32_t ct_manager_matches(const uint32_t*),bridge_manager_matches(void*,uint32_t);
extern uint32_t ct_boot_close(void);
extern uint32_t ct_close_admission(void*,uint32_t),ct_shutdown(void*,uint32_t);
extern uint32_t ct_stage_next(const uint32_t*),ct_activate_next(void*,uint32_t);
extern uint32_t ct_abort_stage(void*,uint32_t),ct_stage_is_published(void*);
extern uint32_t bridge_step(void*,uint32_t),bridge_manager_flags(void*),bridge_manager_error(void*);
extern void bridge_route_fault(void*,uint32_t,uint32_t);
extern uint32_t life_prepare(void*,Capture*,uint32_t,uint32_t),life_cancel_quiesced(void*,Capture*);
extern uint32_t life_is_prepared(const void*),life_resources_released(const void*),life_current_serial(const void*);
extern uint32_t life_copy_verified(const void*,uint16_t*,uint32_t);
static void *object(SessionManager *m,uint32_t i){return (void*)m->descriptor[i];}
static uint32_t bytes(uint32_t i) {
    const uint32_t sizes[]={ct_layout[0],rr_layout[0],bridge_layout[0],exchange_layout[0],
                           life_layout[0],sizeof(Capture)};
    return sizes[i];
}
static int overlap(uint32_t a,uint32_t n,uint32_t b,uint32_t k){return a<b+k && b<a+n;}
static int spans(SessionManager *m,const uint32_t *d,HistoryStorage *h) {
    uint32_t addr=(uint32_t)m;
    if(!addr || (addr&3) || addr>UINT32_MAX-sizeof(*m) ||
        (d[5]&31u) || !d[8] || !d[9] || hstorage_decode((void*)d[6],d[7],h) ||
        !hstorage_disjoint(h,addr,sizeof(*m)))return 0;
    if((d[7]&HISTORY_EXTERNAL) && overlap(d[6],sizeof(*h),addr,sizeof(*m)))return 0;
    for(uint32_t i=0;i<6;i++) {
        uint32_t n=bytes(i);
        if(!d[i] || (d[i]&3) || d[i]>UINT32_MAX-n || overlap(d[i],n,addr,sizeof(*m)))return 0;
        for(uint32_t j=0;j<i;j++)if(overlap(d[i],n,d[j],bytes(j)))return 0;
        if(!hstorage_disjoint(h,d[i],n) ||
           ((d[7]&HISTORY_EXTERNAL) && overlap(d[i],n,d[6],sizeof(*h))))return 0;
    }
    return 1;
}
KEEP uint32_t manager_storage_disjoint(SessionManager *m,const uint32_t *d,uint32_t a,uint32_t n) {
    HistoryStorage h;
    if(!m || !d || !a || !n || a>UINT32_MAX-n || !spans(m,d,&h) ||
       overlap(a,n,(uint32_t)m,sizeof(*m)))return 0;
    for(uint32_t i=0;i<6;i++)if(overlap(a,n,d[i],bytes(i)))return 0;
    if((d[7]&HISTORY_EXTERNAL) && overlap(a,n,d[6],sizeof(h)))return 0;
    return hstorage_disjoint(&h,a,n);
}
KEEP uint32_t manager_boot(SessionManager *m,const uint32_t *d,uint32_t pad,uint32_t serial) {
    HistoryStorage h;
    if(!m || !d || manager_owner || pad>3 || !serial || !spans(m,d,&h))return 12;
    /* Reject a dirty manager rather than silently discard its state/ownership. */
    const uint8_t *raw=(const uint8_t*)m;
    for(uint32_t i=0;i<sizeof(*m);i++)if(raw[i])return 12;
    uint32_t s=ct_boot_close();if(s)return s;
    for(uint32_t i=0;i<10;i++)m->descriptor[i]=d[i];
    /* Existing RESET advances to the caller's first session and serial before
     * clearing objects, preserving its bounded work and cancellation protocol. */
    m->session=d[8]-1;m->serial=serial-1;m->pad=pad;m->state=M_RESET;
    manager_owner=m;return 0;
}
KEEP uint32_t manager_init(SessionManager *m,const uint32_t *d,uint32_t pad) {
    /* Fresh zeroed Manager, live ARMED first session, strict audio installed.
     * Descriptor pointers refer to valid caller-owned allocations. */
    HistoryStorage h;
    if(!m || !d || manager_owner || m->state || pad>3 || !spans(m,d,&h) || !ct_manager_matches(d) ||
       !bridge_manager_matches((void*)d[2],d[8]) || !life_is_prepared((void*)d[4]))return 12;
    for(uint32_t i=0;i<10;i++)m->descriptor[i]=d[i];
    m->session=d[8];m->serial=life_current_serial((void*)d[4]);m->pad=pad;m->state=M_LIVE;manager_owner=m;return 0;
}
KEEP void manager_cancel(SessionManager *m) {if(m && m==manager_owner)ST(&m->cancel,1);}
static void remember(SessionManager *m,uint32_t code){if(!m->error)m->error=code;}
static uint32_t stopped(SessionManager *m,uint32_t code,int blocked) {
    /* Resource/fence uncertainty supersedes the initiating cancellation. */
    if(blocked && code)m->error=code;else remember(m,code);
    m->state=blocked?M_BLOCKED:M_STOPPED;return m->error;
}
static uint32_t cleanup_unpublished(SessionManager *m) {
    if(!life_resources_released(object(m,4)))
        (void)life_cancel_quiesced(object(m,4),object(m,5));
    return stopped(m,m->error?m->error:16,!life_resources_released(object(m,4)));
}
static uint32_t run(SessionManager *m) {
    uint32_t *d=m->descriptor,s,flags;
    switch(m->state) {
    case M_LIVE:
    case M_FINISH:
        if(LD(&m->cancel))bridge_route_fault(object(m,2),m->session,16);
        s=bridge_step(object(m,2),m->session);flags=bridge_manager_flags(object(m,2));
        if(s!=0 && s!=10 && s!=11)remember(m,s);
        if((flags&1) || m->error || LD(&m->cancel)) {
            uint32_t close=ct_close_admission(object(m,0),m->session);
            if(close)return stopped(m,close,1);
            m->state=M_FINISH;
        }
        if(s==0 || (s!=10 && s!=11)){m->state=M_FENCE;return 10;}
        return s;
    case M_FENCE:
        flags=bridge_manager_flags(object(m,2));
        if(!(flags&8)) {
            if(LD(&m->cancel))bridge_route_fault(object(m,2),m->session,16);
            s=bridge_step(object(m,2),m->session);
            if(s==10 || s==11)return s;
            if(s)remember(m,s);
        }
#ifdef L6_CAPTURE_STORAGE_LEASE
        if(storage_lease_closing(m)) {
            /* Storage changes need closed files and stopped memory accesses,
             * not permission to reuse the retained control objects. Keep old
             * queued callbacks alive and never reset/rearm this arena. */
            s=bridge_close_storage(object(m,2),m->session);
            if(s==11)return s;
            if(s || !life_resources_released(object(m,4)))return stopped(m,s?s:13,1);
            remember(m,16);m->state=M_STORAGE_STOPPED;return m->error;
        }
#endif
        s=ct_shutdown(object(m,0),m->session);
        if(s==10 || s==11)return s;
        if(s)return stopped(m,s,1);
        if(bridge_manager_error(object(m,2)))remember(m,bridge_manager_error(object(m,2)));
        if(!life_resources_released(object(m,4)))return stopped(m,13,1);
        /* Publish a result only AFTER the fence and a final validity check. */
        if(!m->error && !LD(&m->cancel)) {
            ManagerResult *r=&m->results[m->head];
            if(life_copy_verified(object(m,4),r->path,261))return stopped(m,13,0);
            r->session=m->session;r->reserved=0;m->head=(m->head+1)&3;
            if(m->count<4)m->count++;
        }
        if(m->error || LD(&m->cancel))return stopped(m,16,0);
        m->zero_index=m->zero_offset=0;m->state=M_RESET;return 10;
    case M_RESET:
        if(!m->zero_index && !m->zero_offset && m->publication_owner && m->count &&
           m->results[(m->head+3)&3].session==m->session && m->publication_session!=m->session)return 11;
        if(LD(&m->cancel))return stopped(m,16,0);
        if(!m->zero_index && !m->zero_offset) {
            if(m->session==UINT32_MAX || m->serial==UINT32_MAX)return stopped(m,14,0);
            d[8]=++m->session;m->serial++;
        }
        /* Clear control objects only, at most 4 KiB per fenced worker step.
         * exchange_prepare initializes slot ownership before publication;
         * exchange_stage overwrites every timestamp/sample before READY.
         * Old history payloads therefore need no clearing, even at cold boot. */
        if(m->zero_index<6) {
            uint32_t n=bytes(m->zero_index)-m->zero_offset;if(n>4096)n=4096;
            uint8_t *p=(uint8_t*)object(m,m->zero_index)+m->zero_offset;
            for(uint32_t i=0;i<n;i++)p[i]=0;
            m->zero_offset+=n;
            if(m->zero_offset==bytes(m->zero_index)){m->zero_index++;m->zero_offset=0;}
            return 10;
        }
        m->state=M_PREPARE;return 10;
    case M_PREPARE:
        if(LD(&m->cancel)) {
#ifdef L6_CAPTURE_STORAGE_LEASE
            return cleanup_unpublished(m);
#else
            return stopped(m,16,0);
#endif
        }
        s=life_prepare(object(m,4),object(m,5),m->pad,m->serial);
        if(s==10)return 10; /* bounded filename collision probing */
        if(s)return stopped(m,s,!life_resources_released(object(m,4)));
        m->serial=life_current_serial(object(m,4));m->state=M_STAGE;return 10;
    case M_STAGE:
        if(LD(&m->cancel)){m->state=M_ABORT_UNPUBLISHED;remember(m,16);return 10;}
        s=ct_stage_next(d);
        if(s) {
            remember(m,s);
            if(ct_stage_is_published(object(m,0)))return stopped(m,s,1);
            m->state=M_ABORT_UNPUBLISHED;return 10;
        }
        m->state=M_ACTIVATE;return 10;
    case M_ACTIVATE:
        if(LD(&m->cancel)){remember(m,16);m->state=M_ABORT_STAGE;return 10;}
        s=ct_activate_next(object(m,0),m->session);
        if(s==11)return 11;
        if(s){remember(m,s);m->state=M_ABORT_STAGE;return 10;}
        m->state=M_LIVE;return 0;
    case M_ABORT_STAGE:
        s=ct_abort_stage(object(m,0),m->session);
        if(s==10 || s==11)return s;
        return stopped(m,s?s:16,s!=0);
    case M_ABORT_UNPUBLISHED:return cleanup_unpublished(m);
#ifdef L6_CAPTURE_STORAGE_LEASE
    case M_STORAGE_STOPPED:
#endif
    case M_STOPPED:case M_BLOCKED:return m->error;
    default:return 12;
    }
}
KEEP uint32_t manager_step(SessionManager *m) {
    if(!m || m!=manager_owner || !m->state)return 12;
#ifdef L6_CAPTURE_STORAGE_LEASE
    uint32_t lease=storage_lease_enter(m,1);if(lease)return lease;
#endif
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&m->busy,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
#ifdef L6_CAPTURE_STORAGE_LEASE
        storage_lease_leave(m);
#endif
        return 11;
    }
    uint32_t s=LD(&m->publication_hold)?11:run(m);ST(&m->busy,0);
#ifdef L6_CAPTURE_STORAGE_LEASE
    storage_lease_leave(m);
#endif
    return s;
}
KEEP uint32_t manager_resume(SessionManager *m) {
    if(!m || m!=manager_owner)return 12;
#ifdef L6_CAPTURE_STORAGE_LEASE
    uint32_t lease=storage_lease_enter(m,0);if(lease)return lease;
#endif
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&m->busy,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
#ifdef L6_CAPTURE_STORAGE_LEASE
        storage_lease_leave(m);
#endif
        return 11;
    }
    uint32_t s=12;
    if(m->state==M_STOPPED && !LD(&m->publication_hold)) {
        m->error=0;ST(&m->cancel,0);m->zero_index=m->zero_offset=0;m->state=M_RESET;s=0;
    }
    ST(&m->busy,0);
#ifdef L6_CAPTURE_STORAGE_LEASE
    storage_lease_leave(m);
#endif
    return s;
}
KEEP uint32_t manager_copy_result(SessionManager *m,uint32_t newest_index,ManagerResult *out) {
    if(!m || m!=manager_owner || !out)return 12;
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&m->busy,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
    uint32_t s=12;
    if(newest_index<m->count) {*out=m->results[(m->head+3-newest_index)&3];s=0;}
    ST(&m->busy,0);return s;
}

static uint32_t visit_results(SessionManager *m,uint32_t token,ManagerVisitor visit,void *context) {
    if(!m || m!=manager_owner || !visit)return 12;
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&m->busy,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
    uint32_t result=11;
    /* Caller must additionally acquire the pad/ordinary-recorder/card exclusion
     * through the publisher port. This latch alone is NOT a sampler fence. */
    if((token ? m->publication_owner==token && LD(&m->publication_hold)==token : !m->publication_owner) &&
       m->state==M_RESET && !m->error && !LD(&m->cancel) && m->count) {
        visit(m->results,m->head,m->count,context);result=0;
    }
    ST(&m->busy,0);return result;
}

KEEP uint32_t manager_visit_results(SessionManager *m,ManagerVisitor visit,void *ctx) {
    return visit_results(m,0,visit,ctx);
}
KEEP uint32_t manager_visit_held_results(SessionManager *m,uint32_t token,ManagerVisitor visit,void *ctx) {
    if(!token)return 12;
    return visit_results(m,token,visit,ctx);
}
static uint32_t publication(SessionManager *m,uint32_t token,uint32_t action) {
    if(!m || m!=manager_owner || !token)return 12;
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&m->busy,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 11;
    uint32_t r=12;
    if(!action) {
        if(!m->publication_owner && !m->publication_hold &&
           (m->state==M_LIVE || (m->state==M_RESET && !m->zero_index && !m->zero_offset))) {
            m->publication_owner=token;r=0;
        }
    } else if(m->publication_owner==token && m->state==M_RESET &&
              !m->zero_index && !m->zero_offset && m->count &&
              m->results[(m->head+3)&3].session==m->session) {
        if(action==3) {
            if(!LD(&m->publication_hold)){m->publication_session=m->session;r=0;}
            else r=11;
        } else if(action==1) {
            if(!m->error && !LD(&m->cancel) && !m->publication_hold && m->publication_session!=m->session) {
                ST(&m->publication_hold,token);r=0;
            } else r=11;
        } else if(LD(&m->publication_hold)==token) {
            m->publication_session=m->session;ST(&m->publication_hold,0);r=0;
        }
    } else if(action==1 && m->publication_owner==token)r=11;
    ST(&m->busy,0);return r;
}
KEEP uint32_t manager_bind_publication(SessionManager *m,uint32_t token){return publication(m,token,0);}
KEEP uint32_t manager_hold_publication(SessionManager *m,uint32_t token){return publication(m,token,1);}
KEEP uint32_t manager_release_publication(SessionManager *m,uint32_t token){return publication(m,token,2);}
KEEP uint32_t manager_skip_publication(SessionManager *m,uint32_t token){return publication(m,token,3);}
