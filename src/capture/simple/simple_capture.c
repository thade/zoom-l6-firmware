/* Pre-compressor stereo capture for stock L6 v1.10, simplified design.
 * The extra file exists only for a stock recording: it opens after the stock
 * recorder admits its seven streams and finishes at the stock stop cursor.
 * Storage changes revoke it; nothing here ever waits without a bound. */
#include "simple_capture.h"
#include "../retention.h"

#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define W(a) (*(volatile uint32_t *)(a))
#define B8(a) (*(volatile uint8_t *)(a))

/* Stock audio state (B=0x20010a48) and recorder state. */
#define CURSOR W(0x20015e2cu)
#define CAPACITY W(0x20015e30u)
#define CALLBACK W(0x20015e10u)
#define COPY_STATE B8(0x20015e1cu)
#define MIX_LEFT ((const volatile uint32_t *)0x20013e00u)
#define MIX_RIGHT ((const volatile uint32_t *)0x20013f00u)
#define SAVED_START W(0x80443154u)
#define REC_STOP_RETURN 0x8004ba4du   /* RecStop's call of the setter; PlayStop also calls it */

typedef int32_t (*Open)(uint32_t*,const uint16_t*,uint32_t,uint32_t);
typedef int32_t (*Transfer)(uint32_t,void*,uint32_t,uint32_t*);
#define OPEN ((Open)0x8005ffe9u)
#define WRITE ((Transfer)0x800622b1u)
#define READ ((Transfer)0x80060621u)
#define CLOSE ((int32_t (*)(uint32_t))0x8005c1f9u)
#define SEEK ((int32_t (*)(uint32_t,int32_t,uint32_t))0x8005f169u)
#define INFO ((int32_t (*)(uint32_t,uint32_t*))0x8005ef41u)
#define DELAY ((void (*)(uint32_t))0x80074159u)
#define CREATE ((int32_t (*)(void (*)(void*),const char*,uint32_t,void*,uint32_t,uint32_t*))0x80076c61u)
#define ALLOC ((void *(*)(uint32_t))0x8006de79u)
#define RECEIVE ((int32_t (*)(uint32_t*))0x80020691u)
#define NOT_FOUND 0xffffd75au
#define EXISTS 0xffffd75bu
#define LIMIT 0x7ffff000u

KEEP SimpleCapture *sc_state;
KEEP uint32_t sc_startup_status;
KEEP const uint32_t sc_layout[]={sizeof(SimpleCapture),offsetof(SimpleCapture,frames),
    offsetof(SimpleCapture,take),offsetof(SimpleCapture,revoked),offsetof(SimpleCapture,state),
    offsetof(SimpleCapture,completed),offsetof(SimpleCapture,path),offsetof(SimpleCapture,header),
    offsetof(SimpleCapture,fifo),offsetof(SimpleCapture,limit),offsetof(SimpleCapture,skipped)};

static uint32_t interrupt(void) {uint32_t v;__asm__ volatile("mrs %0, ipsr":"=r"(v));return v;}
static ScBlock *block(SimpleCapture *g,uint32_t frame) {
    uint32_t i=(frame/SC_FRAMES)&g->mask;
    return &g->history.segment[i>>g->shift][i&(g->history.per_segment-1)];
}

KEEP uint32_t sc_init(SimpleCapture *g,const ScHistory *h,uint32_t serial) {
    uint32_t n=h->segments,per=h->per_segment;
    if(!g || ((uint32_t)g&31u) || !n || n>SC_MAX_SEGMENTS || (n&(n-1)) || !per || (per&(per-1)) ||
       n*per<4 || LD(&sc_state))return SC_INVALID;
    for(uint32_t i=0;i<n;i++)if(!h->segment[i] || ((uint32_t)h->segment[i]&7u))return SC_INVALID;
    g->history=*h;g->mask=n*per-1;g->shift=0;
    while((1u<<g->shift)<per)g->shift++;
    g->serial=serial;g->limit=LIMIT;g->expected=UINT32_MAX;
    ST(&sc_state,g);return SC_OK;
}

/* ---- Audio: original DSP tap (pre-master mix) and post-cursor commit ---- */
KEEP void sc_stage(void) {
    SimpleCapture *g=LD(&sc_state);if(!g)return;
    uint32_t cursor=CURSOR,capacity=CAPACITY;
    g->staged=0;
    if(CALLBACK!=0x2022a791u || COPY_STATE==2 || capacity<SC_FRAMES || capacity%SC_FRAMES ||
       cursor>=capacity || cursor%SC_FRAMES)return;
    if(capacity!=g->capacity || cursor!=g->expected) {
        /* First block or a continuity break: start a new epoch at this cursor. */
        g->capacity=g->published_capacity=capacity;g->published_cursor=cursor;g->age=0;
        ST(&g->epoch,g->epoch+1);
    }
    /* Raw words: the audio path needs no FPU work for an exact copy. */
    ScBlock *b=block(g,g->frames);
    uint32_t *l=(uint32_t*)b->left,*r=(uint32_t*)b->right;
    for(uint32_t i=0;i<SC_FRAMES;i++){l[i]=MIX_LEFT[i];r[i]=MIX_RIGHT[i];}
    g->expected=cursor;g->staged=1;
}
KEEP void sc_commit(void) {
    SimpleCapture *g=LD(&sc_state);
    if(!g || !g->staged)return;
    g->staged=0;
    uint32_t next=g->expected+SC_FRAMES;if(next==g->capacity)next=0;
    if(CURSOR!=next || CAPACITY!=g->capacity){g->expected=UINT32_MAX;return;}
    g->expected=g->published_cursor=next;
    if(g->age<0x80000000u)g->age+=SC_FRAMES;
    ST(&g->frames,g->frames+SC_FRAMES);
}

/* ---- Recorder task: resolve stock ring cursors to published frames ---- */
/* Hooks below run in task context, so audio callbacks complete around them.
 * A stable epoch/frames pair whose cursor matches the stock cursor is current. */
static int resolve(SimpleCapture *g,uint32_t selected,uint32_t *frame,uint32_t *epoch) {
    for(uint32_t tries=0;tries<4;tries++) {
        uint32_t e=LD(&g->epoch),f=LD(&g->frames),published=g->published_cursor;
        uint32_t age=g->age,cap=g->published_capacity,cursor=CURSOR;
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        if(e!=LD(&g->epoch) || f!=LD(&g->frames))continue;
        if(!e || !cap || selected>=cap || cursor!=published)return 0;
        uint32_t distance=(cursor+cap-selected)%cap;
        if(distance>age || distance>g->mask*SC_FRAMES)return 0;
        *frame=f-distance;*epoch=e;return 1;
    }
    return 0;
}
static int normal_recording(void) {
    static const uint8_t channels[]={0,1,2,4,6,8,10};
    if(B8(0x801f5f00u)!=255 || (W(0x8077ce70u)&0x557u)!=0x557u)return 0;
    for(uint32_t i=0;i<7;i++)if(!W(0x8077e87cu+channels[i]*4u))return 0;
    return 1;
}
/* Stock recorder start, after all seven streams are registered (0x8000b158).
 * The stock saved start cursor is the first frame of every stock take file. */
KEEP void sc_admit(void) {
    SimpleCapture *g=LD(&sc_state);
    if(!g || !normal_recording())return;
    if(interrupt()){g->event_faults++;return;}
    if(g->open_take) {
        /* The previous take never reported a stop; do not guess its end. */
        ST(&g->abort_take,g->open_take);g->open_take=0;
    }
    if(LD(&g->take)!=LD(&g->done) || LD(&g->state)!=SC_IDLE){g->skipped++;return;}
    uint32_t start,epoch;
    if(!resolve(g,SAVED_START,&start,&epoch)){g->event_faults++;return;}
    g->start=start;g->take_epoch=epoch;g->take_revoked=LD(&g->revoked);
    uint32_t t=g->take+1;g->open_take=t;ST(&g->take,t);
}
/* Stock stop cursor setter (0x80006918). Only the RecStop call ends a take;
 * selected is the cursor the stock files end at. The worker runs at a lower
 * priority than this task, so it cannot observe the stop half-written. */
KEEP void sc_stop(uint32_t selected,uint32_t caller) {
    SimpleCapture *g=LD(&sc_state);
    if(!g || !g->open_take || caller!=REC_STOP_RETURN)return;
    uint32_t t=g->open_take,stop,epoch;g->open_take=0;
    if(interrupt() || !resolve(g,selected,&stop,&epoch) || epoch!=g->take_epoch ||
       (int32_t)(stop-g->start)<=0) {
        g->event_faults++;ST(&g->abort_take,t);return;
    }
    g->stop=stop;ST(&g->stop_take,t);
}

/* ---- Main: storage-changing packets revoke the extra file ---- */
/* Five original Main receive calls come here. The stock handler runs after we
 * return; give the worker a bounded chance to close first, then carry on. */
KEEP int32_t sc_main_receive(uint32_t *packet) {
    int32_t result=RECEIVE(packet);
    uint32_t storage=(packet[0]==0 && packet[2]>=0x32 && packet[2]<=0x35) ||
        (packet[0]==1 && packet[1]==0 && packet[2]<=5) ||
        /* Native category-2 dispatch selects by code alone; subtype is ignored. */
        (packet[0]==2 && (packet[2]==0xa2 || packet[2]==0xa3));
    SimpleCapture *g=LD(&sc_state);
    if(storage && g) {
        /* Paired with the worker: either it sees this revocation before its
         * next file call, or we see file_open and wait. */
        __atomic_fetch_add(&g->revoked,1,__ATOMIC_SEQ_CST);
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        for(uint32_t i=0;i<SC_WAIT_TICKS && LD(&g->file_open);i++)DELAY(1);
    }
    return result;
}

/* ---- Worker: the only filesystem caller ---- */
static void u32(uint8_t *p,uint32_t v) {for(uint32_t i=0;i<4;i++)p[i]=(uint8_t)(v>>(i*8));}
static void tag(uint8_t *p,const char *s) {for(uint32_t i=0;i<4;i++)p[i]=(uint8_t)s[i];}
static void header(SimpleCapture *g,uint32_t bytes) {
    uint8_t *h=g->header;
    for(uint32_t i=0;i<512;i++)h[i]=0;
    tag(h,"RIFF");u32(h+4,bytes+504);tag(h+8,"WAVE");tag(h+12,"fmt ");u32(h+16,16);
    h[20]=3;h[22]=2;u32(h+24,48000);u32(h+28,384000);h[32]=8;h[34]=32;
    tag(h+36,"JUNK");u32(h+40,460);tag(h+504,"data");u32(h+508,bytes);
}
static int put(SimpleCapture *g,const void *p,uint32_t n) {
    uint32_t actual=0;return WRITE(g->handle,(void*)p,n,&actual)==0 && actual==n;
}
static void finish(SimpleCapture *g,uint32_t status) {
    /* One close attempt. A failed close is forgotten, never retried or waited on. */
    if(g->handle) {
        uint32_t h=g->handle;g->handle=0;
        if(CLOSE(h) && !status)status=SC_IO;
    }
    g->last_status=status;
    if(status)g->failed++;else g->completed++;
    ST(&g->state,SC_IDLE);ST(&g->file_open,0);
}
static int revoked(SimpleCapture *g) {return LD(&g->revoked)!=g->take_revoked;}
/* 1 exists, 0 not found, -1 error. Read-only probe; leaves ext in path. */
static int exists(SimpleCapture *g,uint32_t n,const char *ext) {
    for(uint32_t i=0;i<5;i++)g->path[n+8+i]=(uint16_t)ext[i];
    uint32_t probe=0;int32_t found=OPEN(&probe,g->path,0,0x100);
    if(!found){(void)CLOSE(probe);return 1;}
    return !probe && (uint32_t)found==NOT_FOUND?0:-1;
}
static int used(SimpleCapture *g,uint32_t n,uint32_t serial) {
    static const char hex[]="0123456789ABCDEF";
    for(uint32_t i=0;i<8;i++)g->path[n+i]=(uint16_t)hex[(serial>>(28-i*4))&15u];
    int wav=exists(g,n,".WAV");
    return wav?wav:exists(g,n,".TMP");
}
/* Create OD_<serial>.TMP under the first free serial (no .WAV or .TMP). */
static uint32_t open_file(SimpleCapture *g) {
    const char *prefix="A:\\SOUND_PAD\\PAD1\\OD_";
    uint32_t n=0;int u;
    while(prefix[n]){g->path[n]=(uint16_t)prefix[n];n++;}
    if(!g->named) {
        /* First take after boot: names are normally used from 1 upward, so a
         * doubling then bisecting search finds a free one in O(log n) probes.
         * Any free name is acceptable if earlier ones were deleted. */
        uint32_t lo=0,hi=1;
        while((u=used(g,n,hi))==1) {
            if(revoked(g))return SC_REVOKED;
            if(hi>=0x40000000u)return SC_NAME;
            lo=hi;hi*=2;
        }
        while(u>=0 && hi-lo>1) {
            uint32_t mid=lo+(hi-lo)/2;
            if((u=used(g,n,mid))==1)lo=mid;else if(!u)hi=mid;
        }
        if(u<0)return SC_IO;
        g->serial=hi;g->named=1;
    }
    for(uint32_t tries=0;tries<8;tries++,g->serial++) {
        if(revoked(g))return SC_REVOKED;
        if((u=used(g,n,g->serial))!=0) {
            if(u<0)return SC_IO;
            continue;
        }
        int32_t created=OPEN(&g->handle,g->path,0x501,0x80);
        if(!created)break;
        if(g->handle || (uint32_t)created!=EXISTS){g->handle=0;return SC_IO;}
    }
    if(!g->handle)return SC_NAME;
    g->serial++;header(g,0);
    return put(g,g->header,512)?SC_OK:SC_IO;
}
/* Clean and invalidate our own lines after a read: CPU-copied data reaches
 * memory first, and a stale line cannot hide what DMA wrote. */
static void coherent(const void *p,uint32_t n) {
    uint32_t a=(uint32_t)p&~31u,end=((uint32_t)p+n+31u)&~31u;
    __asm__ volatile("dsb":::"memory");
    for(;a<end;a+=32)W(0xe000ef70u)=a;
    __asm__ volatile("dsb\n\tisb":::"memory");
}
static uint32_t complete(SimpleCapture *g) {
    if(g->fifo_used && !put(g,g->fifo,g->fifo_used)){finish(g,SC_IO);return 1;}
    g->bytes+=g->fifo_used;g->fifo_used=0;header(g,g->bytes);
    if(SEEK(g->handle,0,2) || !put(g,g->header,512)){finish(g,SC_IO);return 1;}
    uint32_t h=g->handle;g->handle=0;
    if(CLOSE(h)){finish(g,SC_IO);return 1;}
    /* The file is complete. Do not reopen it on a card that is changing. */
    if(revoked(g)){finish(g,SC_REVOKED);return 1;}
    /* Check the finished file as the card returns it: length and header. */
    uint32_t info[4]={0},actual=0;
    if(OPEN(&g->handle,g->path,0,0x100)){g->handle=0;finish(g,SC_VERIFY);return 1;}
    if(INFO(g->handle,info) || info[0]!=g->bytes+512 ||
       READ(g->handle,g->fifo,512,&actual) || actual!=512){finish(g,SC_VERIFY);return 1;}
    coherent(g->fifo,512);
    for(uint32_t i=0;i<512;i++)if(g->fifo[i]!=g->header[i]){finish(g,SC_VERIFY);return 1;}
    finish(g,SC_OK);return 0;
}
static uint32_t capture(SimpleCapture *g) {
    uint32_t t=g->done,history=g->mask*SC_FRAMES;
    for(uint32_t writes=0;writes<4;) {
        if(revoked(g)){finish(g,SC_REVOKED);return 1;}
        if(LD(&g->abort_take)==t){finish(g,SC_EVENT);return 1;}
        /* Once the stop is known its frames are bounded; a later continuity
         * break cannot affect them. Overwrites are caught by frame number. */
        uint32_t stopped=LD(&g->stop_take)==t;
        if(!stopped && LD(&g->epoch)!=g->take_epoch){finish(g,SC_TIMELINE);return 1;}
        if((stopped && g->cursor==g->stop) || g->bytes+g->fifo_used>=g->limit)return complete(g);
        uint32_t base=g->cursor&~(SC_FRAMES-1u),offset=g->cursor-base;
        uint32_t f=LD(&g->frames);
        if((int32_t)(f-base)<(int32_t)SC_FRAMES)return 10; /* not yet committed */
        if(f-base>history){finish(g,SC_OVERRUN);return 1;}
        ScBlock *b=block(g,base);float *out=(float*)(g->fifo+g->fifo_used);
        for(uint32_t i=offset;i<SC_FRAMES;i++){*out++=b->left[i]*0x1p-31f;*out++=b->right[i]*0x1p-31f;}
        /* The producer may have reused this slot while we copied it. */
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        if(LD(&g->frames)-base>history){finish(g,SC_OVERRUN);return 1;}
        /* Read the stop only after copying. If it is still unknown, it will
         * resolve at or after every frame published so far, including these. */
        uint32_t n=SC_FRAMES-offset;
        if(LD(&g->stop_take)==t) {
            uint32_t left=g->stop-g->cursor;
            if((int32_t)left<0){finish(g,SC_ORDER);return 1;}
            if(left<n)n=left;
        }
        g->cursor+=n;g->fifo_used+=n*8u;
        if(g->fifo_used>=SC_FIFO) {
            /* Whole 4-KiB writes keep every payload write sector-aligned. */
            if(!put(g,g->fifo,SC_FIFO)){finish(g,SC_IO);return 1;}
            g->bytes+=SC_FIFO;g->fifo_used-=SC_FIFO;
            uint32_t *to=(uint32_t*)g->fifo;const uint32_t *from=(const uint32_t*)(g->fifo+SC_FIFO);
            for(uint32_t i=0;i<g->fifo_used/4u;i++)to[i]=from[i];
            writes++;
        }
    }
    return 10;
}
KEEP uint32_t sc_worker_step(void) {
    SimpleCapture *g=LD(&sc_state);if(!g)return SC_INVALID;
    if(LD(&g->state)==SC_CAPTURING)return capture(g);
    uint32_t t=LD(&g->take);
    if(t==g->done)return 0;
    /* Mark the file open before any file call, so Main's wait covers it. */
    __atomic_store_n(&g->file_open,1,__ATOMIC_SEQ_CST);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    ST(&g->state,SC_CAPTURING);ST(&g->done,t);
    g->cursor=g->start;g->fifo_used=0;g->bytes=0;
    if(revoked(g)){finish(g,SC_REVOKED);return 1;}
    uint32_t s=open_file(g);
    if(s){finish(g,s);return 1;}
    return 10;
}
KEEP __attribute__((noreturn)) void sc_worker_entry(void *unused) {
    (void)unused;
    for(;;)DELAY(sc_worker_step()==10?1u:25u);
}

/* ---- Startup: two original startup sites ---- */
#define RING 0x81429800u
#define STRIDE 960000u
#define RING_FRAMES 223104u   /* shortened by the ring-size patch */
#define TAIL_BLOCKS 128u
_Static_assert(RING_FRAMES*4u+TAIL_BLOCKS*sizeof(ScBlock)<=STRIDE,"history must fit each lane tail");
KEEP void startup_observe(uint32_t unused,uint32_t first_result) {
    (void)unused;
    if(!sc_startup_status)sc_startup_status=first_result?2:1;
}
/* After stock idle-task creation. One attempt; allocations stay until reboot. */
KEEP void startup_register(void) {
    if(sc_startup_status!=1)return;
    sc_startup_status=3;
    uint8_t *raw=ALLOC(sizeof(SimpleCapture)+31u);if(!raw)return;
    SimpleCapture *g=(SimpleCapture*)(((uint32_t)raw+31u)&~31u);
    for(uint32_t i=0;i<sizeof(*g);i++)((uint8_t*)g)[i]=0;
    ScHistory h={.segments=SC_MAX_SEGMENTS,.per_segment=TAIL_BLOCKS};
    for(uint32_t i=0;i<SC_MAX_SEGMENTS;i++)h.segment[i]=(ScBlock*)(RING+i*STRIDE+RING_FRAMES*4u);
    uint32_t task=0;
    /* Create the worker first: without it, no hook should start a take. */
    if(CREATE(sc_worker_entry,"L6Capture",4096,0,1,&task)!=1 || !task)return;
    if(!sc_init(g,&h,1))sc_startup_status=4;
}
