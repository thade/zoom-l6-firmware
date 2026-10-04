#ifndef L6_REQUEST_ROUTER_H
#define L6_REQUEST_ROUTER_H
#include <stdint.h>
typedef struct {void *bridge;uint32_t session,next,owner,pending;} Router;
typedef struct {
    Router *router;uint32_t session,id,owner,kind,state,sent,delivered,marked,held,snapshot;
    uint64_t stamp;
    uint32_t selected;
} Request;
uint32_t rr_submit(Router*,Request*,uint32_t);
uint32_t rr_sent(Router*,Request*,uint32_t);
uint32_t rr_dispatch(Router*,Request*);
uint32_t rr_complete(Router*,Request*);
uint32_t rr_begin(Router*,Request*);
uint32_t rr_finish_request(Router*,Request*);
uint32_t rr_ignore(Router*,Request*);
#endif
