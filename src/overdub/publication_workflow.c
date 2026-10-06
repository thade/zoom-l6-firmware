#include "publication_workflow.h"
#define KEEP __attribute__((used,retain))
#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
static PwWorkflow *binding;
extern int32_t od_stock_snapshot(uint32_t,Pad *);
static int enter(PwWorkflow *w) {
    uint32_t z=0;return __atomic_compare_exchange_n(&w->lock,&z,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static int32_t leave(PwWorkflow *w,int32_t r){__atomic_store_n(&w->lock,0,__ATOMIC_RELEASE);return r;}
static int32_t capture_status(uint32_t r){return r==0?OWN_OK:r==11?OWN_BUSY:OWN_CONFLICT;}
KEEP int32_t pw_fenced(void) {
    PwWorkflow *w=binding;if(!w)return 0;
    const PwConfig *c=&w->config;OdShutdown *s=c->shutdown;OcCoordinator *o=s->control;
    return w->child && w->promotion && s->promotion==w->promotion &&
        s->phase==SD_HELD && LD(&s->session->held) && LD(&s->session->ledger->gate.word)==OD_GATE_PROMOTING &&
        LD(&c->capture->publication_hold)==(uint32_t)w && !LD(&c->capture->cancel) &&
        !c->capture->error && c->capture->session==w->session &&
        LD(&o->closed) && o->epoch==s->epoch && LD(&o->audio_request)==s->epoch &&
        LD(&o->audio_ack)==s->epoch && !LD(&o->audio_fault) && s->port->quiet() && c->port->external_held()==1;
}
KEEP const RmPort pw_reload_port={pw_fenced};
KEEP int32_t pw_init(PwWorkflow *w,const PwConfig *c) {
    if(binding || !w || !c || w->phase || !c->capture || !c->publication || !c->files ||
       !c->shutdown || !c->reload || !c->port || !c->port->bind || !c->port->hold ||
       !c->port->release || !c->port->publish || !c->port->external_held ||
       c->reload->port!=&pw_reload_port || !c->reload->runtime ||
       c->shutdown->session->ledger!=c->reload->runtime->coordinator->ledger)return OWN_CONFLICT;
    int32_t r=capture_status(c->port->bind(c->capture,(uint32_t)w));if(r)return r;
    w->config=*c;binding=w;return OWN_OK;
}
KEEP int32_t pw_start(PwWorkflow *w) {
    if(!w || binding!=w)return OWN_CONFLICT;
    if(!enter(w))return OWN_BUSY;
    if(w->phase!=PW_IDLE && w->phase!=PW_DONE)return leave(w,OWN_BUSY);
    if(w->last_session && w->last_session==w->config.capture->session)return leave(w,OWN_STALE);
    w->phase=PW_HOLD;w->error=0;w->publish_result=0;return leave(w,OWN_OK);
}
static int baseline(PwWorkflow *w) {
    for(uint32_t p=0;p<4;p++)if(od_stock_snapshot(p,&w->plan.pads[p]))return 0;
    for(uint32_t i=0;i<RM_SETTINGS;i++) {
        const uint8_t *src=(const uint8_t *)(i<0x60?0x800a202e + i:
            i<0xc94?0x80441560+i-0x60:0x80445524+i-0x60);
        w->plan.settings[i]=*src;
    }
    return 1;
}
static int plan(PwWorkflow *w) {
    /* A safely failed publisher has already verified rollback. Reload and
     * verify the ORIGINAL plan before releasing any shared ownership. */
    if(w->publish_result!=OD_OK)return 1;
    State *s=w->config.publication;
    if(!s->count || s->count>4)return 0;
    for(uint32_t p=0;p<s->count;p++) {
        uint32_t i=0;
        do {
            if(i==OD_PATH)return 0;
            uint16_t ch=s->destinations[p][i];w->plan.pads[p].path[i]=ch;
            uint32_t at=0x60+p*0x20a+i*2;
            w->plan.settings[at]=(uint8_t)ch;w->plan.settings[at+1]=(uint8_t)(ch>>8);
            i++;if(!ch)break;
        }while(1);
        /* Preserve options from BEFORE publication; never bless changed values
         * by reading them from the result about to be checked. */
        w->plan.settings[0x60+0x828+p]=1;
    }
    return 1;
}
KEEP int32_t pw_step(PwWorkflow *w) {
    if(!w || binding!=w)return OWN_CONFLICT;
    if(!enter(w))return OWN_BUSY;
    if(w->phase==PW_IDLE || w->phase==PW_DONE)return leave(w,OWN_OK);
    if(w->phase==PW_FAILED)return leave(w,OWN_FAULT);
    PwConfig *c=&w->config;int32_t r=OWN_BUSY;
    if(c->port->external_held()!=1 || c->capture->error || LD(&c->capture->cancel) ||
       LD(&c->shutdown->session->ledger->gate.word)&OD_GATE_FAILED){r=OWN_FAULT;goto failure;}
    if(w->phase==PW_HOLD) {
        r=capture_status(c->port->hold(c->capture,(uint32_t)w));if(r)goto failure;
        w->session=c->capture->session;w->phase=PW_SHUTDOWN;
    }
    if(w->phase==PW_SHUTDOWN) {
        r=od_shutdown_poll(c->shutdown);if(r)goto failure;
        w->promotion=c->shutdown->promotion;w->phase=PW_CHILD;
    }
    if(w->phase==PW_CHILD) {
        r=od_shutdown_publish_begin(c->shutdown,&w->child);if(r)goto failure;
        w->phase=PW_BASELINE;
    }
    if(w->phase>=PW_BASELINE && w->phase<=PW_CHILD_END && !pw_fenced()){r=OWN_FAULT;goto failure;}
    if(w->phase==PW_BASELINE) {
        if(!baseline(w)){r=OWN_FAULT;goto failure;}w->phase=PW_PUBLISH;
    }
    if(w->phase==PW_PUBLISH) {
        w->publish_result=c->port->publish(c->capture,c->publication,c->files,(uint32_t)w);
        if(w->publish_result==OD_BUSY){r=OWN_BUSY;goto failure;}
        if(w->publish_result!=OD_OK && w->publish_result!=OD_SKIPPED) {
            w->error=0xffff2000+w->publish_result;
            if(w->publish_result==OD_FAULT || c->publication->fault ||
               w->publish_result>OD_FAULT){r=OWN_FAULT;goto failure;}
        }
        w->phase=PW_PLAN;
    }
    if(w->phase==PW_PLAN) {
        if(!plan(w)){r=OWN_FAULT;goto failure;}w->phase=PW_START;
    }
    if(w->phase==PW_START) {
        r=rm_start(c->reload,&w->plan,w->child);if(r)goto failure;w->phase=PW_WAIT;
    }
    if(w->phase==PW_WAIT) {
        /* Main owns the reload producer/verification polling, including its
         * retained UI messages. This worker never executes Main's UI body. */
        r=rm_completed(c->reload);if(r)goto failure;
        w->phase=PW_CHILD_END;
    }
    if(w->phase==PW_CHILD_END) {
        r=od_shutdown_publish_end(c->shutdown,w->child,0);if(r)goto failure;
        w->child=0;w->phase=PW_REOPEN;
    }
    if(w->phase==PW_REOPEN) {
        r=od_shutdown_finish(c->shutdown,w->promotion,0);if(r)goto failure;
        w->promotion=0;w->phase=PW_RELEASE;
    }
    if(w->phase==PW_RELEASE) {
        r=capture_status(c->port->release(c->capture,(uint32_t)w));if(r)goto failure;
        w->last_session=w->session;w->phase=PW_DONE;
    }
    return leave(w,OWN_OK);
failure:
    if(r!=OWN_BUSY) {
        if(!w->error)w->error=(uint32_t)r;
        od_gate_fail(&c->shutdown->session->ledger->gate);w->phase=PW_FAILED;
        return leave(w,OWN_FAULT);
    }
    return leave(w,OWN_BUSY);
}
KEEP int32_t pw_main_ready(void) {
    PwWorkflow *w=binding;if(!w)return OWN_OK;
    if(!enter(w))return OWN_BUSY;
    int32_t r=w->phase==PW_IDLE || w->phase==PW_DONE?OWN_OK:w->phase==PW_FAILED?OWN_FAULT:OWN_BUSY;
    return leave(w,r);
}
KEEP const uint32_t pw_layout[]={sizeof(PwWorkflow),sizeof(PwConfig),sizeof(PwPort)};
