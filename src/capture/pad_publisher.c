/* Offline connection between verified extra captures and stock pad adapters.
 * One worker invokes this at M_RESET before stepping the manager again. BUSY
 * means retain that boundary and retry later; never stop a playing pad here.
 * Error/FAULT requires an explicit caller decision, never a retry loop. */
#include "session_manager.h"
#include "../overdub/overdub.h"
#define KEEP __attribute__((used,retain))
typedef struct {State *state;const Port *port;int32_t result;} PublishContext;
static void publish(const ManagerResult *results,uint32_t head,uint32_t count,void *opaque) {
    PublishContext *c=opaque;
    const uint16_t *paths[4];
    if(!count || count>4 || head>3){c->result=OD_INVALID;return;}
    uint32_t previous=UINT32_MAX;
    for(uint32_t i=0;i<count;i++) {
        const ManagerResult *r=&results[(head+3-i)&3];
        if(!r->session || (i && r->session>=previous)){c->result=OD_INVALID;return;}
        previous=r->session;paths[i]=r->path;
    }
    c->result=od_publish_completed_paths(c->state,c->port,paths,count);
}
KEEP int32_t manager_publish_pads(SessionManager *m,State *state,const Port *port) {
    if(!state || !port)return OD_INVALID;
    PublishContext context={state,port,OD_INVALID};
    uint32_t result=manager_visit_results(m,publish,&context);
    return result==11?OD_BUSY:result?OD_INVALID:context.result;
}

KEEP int32_t manager_publish_held_pads(SessionManager *m,State *state,const Port *port,uint32_t token) {
    if(!state || !port || !token)return OD_INVALID;
    PublishContext context={state,port,OD_INVALID};
    uint32_t result=manager_visit_held_results(m,token,publish,&context);
    return result==11?OD_BUSY:result?OD_INVALID:context.result;
}
