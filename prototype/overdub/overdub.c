#include "overdub.h"
#include <stddef.h>

/* Read by the offline harness; avoids duplicating compiler struct alignment. */
__attribute__((used, retain)) const uint32_t od_layout[] = {sizeof(State),sizeof(Job),sizeof(Pad),sizeof(Port),
    offsetof(State,history),offsetof(State,sources),offsetof(State,destinations),
    offsetof(State,before),offsetof(State,prepared),offsetof(Pad,mode),
    offsetof(Job,master)};

static uint32_t u16(const uint8_t *p) { return p[0] | ((uint32_t)p[1] << 8); }
static uint32_t u32(const uint8_t *p) { return u16(p) | (u16(p+2) << 16); }
static int same(const void *a, const void *b, uint32_t n) {
    const uint8_t *x=a, *y=b;
    for (uint32_t i=0;i<n;i++) if (x[i]!=y[i]) return 0;
    return 1;
}
static int pathcopy(uint16_t *out, const uint16_t *in) {
    for (uint32_t i=0;i<OD_PATH;i++) { out[i]=in[i]; if (!in[i]) return i!=0; }
    return 0;
}
static int patheq(const uint16_t *a, const uint16_t *b) {
    for (uint32_t i=0;i<OD_PATH;i++) { if (a[i]!=b[i]) return 0; if (!a[i]) return 1; }
    return 0;
}
static int masterpath(const uint16_t *p) {
    const char prefix[]="A:\\RECORDER\\", suffix[]="\\MASTER.WAV";
    uint32_t n=0;
    while (n<OD_PATH && p[n]) n++;
    if (n>=OD_PATH || n<sizeof(prefix)+sizeof(suffix)-1) return 0;
    for (uint32_t i=0;i<sizeof(prefix)-1;i++) if (p[i]!=(uint8_t)prefix[i]) return 0;
    for (uint32_t i=0;i<sizeof(suffix)-1;i++)
        if (p[n-(sizeof(suffix)-1)+i]!=(uint8_t)suffix[i]) return 0;
    /* A single take-directory component, no traversal or extra separators. */
    for (uint32_t i=sizeof(prefix)-1;i<n-(sizeof(suffix)-1);i++)
        if (p[i]=='.' || p[i]=='/' || p[i]=='\\' || p[i]==':') return 0;
    return 1;
}
static void destination(uint16_t *out, uint32_t pad, uint32_t serial) {
    const char *prefix="A:\\SOUND_PAD\\PAD";
    uint32_t i=0;
    while (*prefix) out[i++]=(uint8_t)*prefix++;
    out[i++]='1'+pad; out[i++]='\\'; out[i++]='O'; out[i++]='D';
    for (int shift=28;shift>=0;shift-=4) out[i++]="0123456789ABCDEF"[(serial>>shift)&15];
    out[i++]='.';out[i++]='W';out[i++]='A';out[i++]='V';out[i]=0;
}
static int32_t close_handle(State *s, const Port *p, uint32_t *h) {
    if (!*h) return OD_OK;
    int32_t r=p->close(*h);*h=0;
    if (r) { s->cleanup_error=1; return OD_IO; }
    return OD_OK;
}
static int32_t read_exact(const Port *p,uint32_t h,void *buf,uint32_t n) {
    uint32_t got=0;
    if (p->read(h,buf,n,&got) || got!=n) return OD_IO;
    return OD_OK;
}
static int32_t discard(State *s,const Port *p,uint32_t h,uint32_t n) {
    while (n) {
        uint32_t k=n>OD_BLOCK?OD_BLOCK:n;
        if (read_exact(p,h,s->a,k)) return OD_IO;
        n-=k;
        if (p->checkpoint()) return OD_CANCELLED;
    }
    return OD_OK;
}
/* Strict support for the stereo 48 kHz float32 RIFF format observed on this L6.
 * Handles PAD/bext/unknown chunks by length, odd padding, and trailing chunks.
 * This is container validation, not sample analysis or the stock audio loader. */
static int32_t validate(State *s,const Port *p,const uint16_t *path,uint32_t *length) {
    uint32_t h=0,info[4]={0},pos=12,fmt=0,data=0;
    int32_t r=OD_IO;
    if (p->open(&h,path,0,0x100)) return r;
    if (p->info(h,info) || info[0]<44 || read_exact(p,h,s->a,12)) goto done;
    r=OD_WAV;
    if (!same(s->a,"RIFF",4) || !same(s->a+8,"WAVE",4) || u32(s->a+4)!=info[0]-8) goto done;
    while (pos<info[0]) {
        if (info[0]-pos<8) goto done;
        if (read_exact(p,h,s->a,8)) { r=OD_IO;goto done; }
        uint32_t n=u32(s->a+4),isfmt=same(s->a,"fmt ",4),isdata=same(s->a,"data",4);
        pos+=8;
        if (n>info[0]-pos || (n&1)>info[0]-pos-n) goto done;
        uint32_t left=n+(n&1);
        if (isfmt) {
            if (fmt || n!=16) goto done;
            if (read_exact(p,h,s->a,16)) {r=OD_IO;goto done;}
            if (u16(s->a)!=3 || u16(s->a+2)!=2 || u32(s->a+4)!=48000 ||
                u32(s->a+8)!=384000 || u16(s->a+12)!=8 || u16(s->a+14)!=32) goto done;
            fmt=1;left-=16;
        } else if (isdata) {
            if (!fmt || data || !n || (n&7)) goto done;
            data=1;
        }
        int32_t e=discard(s,p,h,left);
        if (e) { r=e;goto done; }
        pos+=n+(n&1);
    }
    if (fmt && data) {*length=info[0];r=OD_OK;}
done:
    if (close_handle(s,p,&h)) r=OD_IO;
    return r;
}
static int32_t copy_verified(State *s,const Port *p,uint32_t pad) {
    uint32_t src=0,dst=0,info[4]={0},n=s->sizes[pad],got=0;
    int32_t r=OD_IO;
    if (p->open(&src,s->sources[pad],0,0x100)) goto done;
    if (p->info(src,info) || info[0]!=n) goto done;
    /* Unique, exclusive files; never truncate, rename or delete old material.
     * Unselected partial/orphan files remain on failure. Scanner exclusion must
     * be provided by enter(), because these files have a WAV extension. */
    if (p->open(&dst,s->destinations[pad],0x501,0x80)) goto done;
    while (n) {
        uint32_t k=n>OD_BLOCK?OD_BLOCK:n;
        if (read_exact(p,src,s->a,k) || p->write(dst,s->a,k,&got) || got!=k) goto done;
        n-=k;
        if (p->checkpoint()) {r=OD_CANCELLED;goto done;}
    }
    r=OD_OK;
done:
    if (close_handle(s,p,&dst)) r=OD_IO;
    if (close_handle(s,p,&src)) r=OD_IO;
    if (r) return r;
    uint32_t verified=0;
    r=validate(s,p,s->destinations[pad],&verified);
    if (r) return r;
    if (verified!=s->sizes[pad]) return OD_IO;
    r=OD_IO;
    if (p->open(&src,s->sources[pad],0,0x100)) goto compared;
    if (p->open(&dst,s->destinations[pad],0,0x100)) goto compared;
    if (p->info(src,info) || info[0]!=verified || p->info(dst,info) || info[0]!=verified) goto compared;
    while (verified) {
        uint32_t k=verified>OD_BLOCK?OD_BLOCK:verified;
        if (read_exact(p,src,s->a,k) || read_exact(p,dst,s->b,k) || !same(s->a,s->b,k)) goto compared;
        verified-=k;
        if (p->checkpoint()) {r=OD_CANCELLED;goto compared;}
    }
    r=OD_OK;
compared:
    if (close_handle(s,p,&dst)) r=OD_IO;
    if (close_handle(s,p,&src)) r=OD_IO;
    return r;
}
/* Shared publication body: callers supply a complete newest-first snapshot.
 * enter() must keep file readers, recording and card/catalogue mutations excluded
 * throughout every copy, assignment and rollback. These are worker calls. */
static int32_t publish_paths(State *s,const Port *p,const uint16_t *const *paths,
                             uint32_t count,uint32_t qualify) {
    if (s->fault) return OD_FAULT;
    if (s->busy) return OD_BUSY;
    if (!count || count>4 || s->count>4 || s->serial==0xffffffff) return OD_INVALID;
    for (uint32_t i=0;i<count;i++) {
        uint32_t n=0;while(n<OD_PATH && paths[i][n])n++;
        if (!n || n==OD_PATH) return OD_INVALID;
        for(uint32_t j=0;j<i;j++)if(patheq(paths[i],paths[j]))return OD_INVALID;
    }
    if (p->enter()) return s->fault?OD_FAULT:OD_BUSY;
    s->busy=1;s->prepared=0;s->inserted=0;s->attempted=0;s->cleanup_error=0;
    int32_t r=OD_OK;
    uint32_t equal=count==s->count;
    for(uint32_t i=0;i<count && equal;i++)equal=patheq(paths[i],s->history[i]);
    if(equal){r=OD_SKIPPED;goto out;}
    /* Own all paths before any filesystem/helper calls can reuse shared RAM. */
    for(uint32_t i=0;i<count;i++)pathcopy(s->sources[i],paths[i]);
    s->serial++;
    for (uint32_t i=0;i<count;i++) {
        destination(s->destinations[i],i,s->serial);
        if (p->snapshot(i,&s->before[i])) {r=OD_ASSIGN;goto out;}
        int32_t n=p->count(i);
        if (n<0 || n>=1000) {r=OD_CATALOGUE;goto out;}
        if (qualify && p->qualify(s->sources[i])) {r=OD_INVALID;goto out;}
        r=validate(s,p,s->sources[i],&s->sizes[i]);
        if (r) goto out;
    }
    for (uint32_t i=0;i<count;i++) {
        r=copy_verified(s,p,i);
        if (r) goto out;
        s->prepared++;
    }
    for (uint32_t i=0;i<count;i++) {
        /* Do not select the entry during catalogue insertion. */
        if (p->insert(i,s->destinations[i],0)) {r=OD_CATALOGUE;goto out;}
        s->inserted++;
    }
    if (p->checkpoint()) {r=OD_CANCELLED;goto out;}
    for (uint32_t i=0;i<count;i++) {
        s->attempted=i+1; /* Include a failing call: it may have partially applied. */
        if (p->assign(i,s->destinations[i],&s->before[i]) || p->snapshot(i,&s->observed) ||
            !patheq(s->observed.path,s->destinations[i]) ||
            !same(&s->observed.mode,&s->before[i].mode,24)) {r=OD_ASSIGN;goto rollback;}
    }
    if (p->save()) {r=OD_PERSIST;goto rollback;}
    for (uint32_t i=0;i<count;i++) pathcopy(s->history[i],s->sources[i]);
    s->count=count;
    goto out;
rollback:
    for (uint32_t i=s->attempted;i>0;i--) {
        uint32_t pad=i-1;
        if (p->restore(pad,&s->before[pad]) || p->snapshot(pad,&s->observed) ||
            !patheq(s->observed.path,s->before[pad].path) ||
            !same(&s->observed.mode,&s->before[pad].mode,24)) s->fault=1;
    }
    if (p->save()) s->fault=1;
out:
    /* Close errors leave handle ownership/durability uncertain; block retries. */
    if (s->cleanup_error) s->fault=1;
    if (s->fault) r=OD_FAULT;
    s->busy=0;p->leave();return s->fault?OD_FAULT:r;
}

int32_t od_promote(State *s,const Port *p,const Job *job) {
    if(s->fault)return OD_FAULT;
    if(s->busy)return OD_BUSY;
    if(job->target>=0)return OD_SKIPPED;
    if(s->count>4 || !job->master_closed_ok || !job->postprocess_done || job->parts!=1 ||
       !masterpath(job->master) || s->serial==0xffffffff)return OD_INVALID;
    for(uint32_t i=0;i<s->count;i++)if(patheq(job->master,s->history[i]))return OD_SKIPPED;
    const uint16_t *paths[4]={job->master};
    uint32_t count=s->count<4?s->count+1:4;
    for(uint32_t i=1;i<count;i++)paths[i]=s->history[i-1];
    return publish_paths(s,p,paths,count,1);
}
/* Internal trusted-caller entry: completion provenance comes from the manager's
 * locked result visitor, not a pathname or fabricated ordinary-MASTER flags.
 * Container validation and copy/readback still run. No generic UI exposure. */
int32_t od_publish_completed_paths(State *s,const Port *p,const uint16_t *const *paths,uint32_t count) {
    return publish_paths(s,p,paths,count,0);
}
