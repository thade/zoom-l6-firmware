/* Dependency-audit fixture ONLY. This is not a recovered filesystem/sector
 * translator: it submits synthetic one-sector transfers before the Python
 * fixture supplies logical file bytes. Never link into a normal profile. */
#include <stdint.h>
#define KEEP __attribute__((used,retain))
typedef int32_t (*Bytes)(uint32_t,void *,uint32_t,uint32_t *);
static int32_t route(uint32_t operation,uint32_t handle,void *buffer,
                     uint32_t bytes,uint32_t *actual,Bytes model) {
    uint32_t request[5]={operation | 0x100u,0,0,1,7};
    uint32_t sector[128]={0};
    *actual=0;
    request[2]=(uint32_t)sector;
    for(uint32_t left=bytes;left;) {
        int32_t status=((int32_t (*)(void *))0x80068379u)(request);
        if(status)return status;
        left-=left<512?left:512;
    }
    return model(handle,buffer,bytes,actual);
}
KEEP int32_t dependency_read(uint32_t handle,void *buffer,uint32_t bytes,uint32_t *actual) {
    return route(2,handle,buffer,bytes,actual,(Bytes)0x2102bf01u);
}
KEEP int32_t dependency_write(uint32_t handle,void *buffer,uint32_t bytes,uint32_t *actual) {
    return route(3,handle,buffer,bytes,actual,(Bytes)0x2102bf05u);
}
