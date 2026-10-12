/* Pad 1 references the last ordinary take's stock master, for stock L6 v1.10.
 * The recorder task notes the take folder at RecStop; a low-priority worker
 * waits for RecStop to finish and checks the file; Main assigns it to pad 1
 * with the Editor's select steps. Nothing here writes to the card. */
#include <stddef.h>
#include "master_ref.h"
#include "../retention.h"

#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define W(a) (*(volatile uint32_t *)(a))
#define B8(a) (*(volatile uint8_t *)(a))

/* Stock recorder state. The take folder (A:\RECORDER\<take>, UTF-16) is
 * written only at record start (0x80022de0) and stays put until the next. */
#define TAKE_DIR ((const volatile uint16_t *)0x8060ff80u)
#define REC_STOP_RETURN 0x8004ba4du   /* RecStop's call of the setter; PlayStop also calls it */
#define RECORDER_BUSY W(0x80578ec0u)  /* RecPlayCtl is running a callback (RecStop includes finalize) */

typedef int32_t (*Open)(uint32_t*,const uint16_t*,uint32_t,uint32_t);
#define OPEN ((Open)0x8005ffe9u)
#define CLOSE ((int32_t (*)(uint32_t))0x8005c1f9u)
#define INFO ((int32_t (*)(uint32_t,uint32_t*))0x8005ef41u)
#define DELAY ((void (*)(uint32_t))0x80074159u)
#define ALLOC ((void *(*)(uint32_t))0x8006de79u)
#define CREATE ((int32_t (*)(void (*)(void*),const char*,uint32_t,void*,uint32_t,uint32_t*))0x80076c61u)
#define RECEIVE ((int32_t (*)(uint32_t*))0x80020691u)
/* Stock pad calls, as used by the Editor's select handler 0x80009ba0. */
#define POST ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t))0x80020ca1u)
#define LOOKUP ((int32_t (*)(uint32_t,const uint16_t*))0x80008ec1u)
#define PATH_OF ((const uint16_t *(*)(uint32_t,int32_t))0x80008e89u)
#define COUNT ((uint32_t (*)(uint32_t))0x80008ee9u)
#define VALIDATE ((uint32_t (*)(const uint16_t*,uint32_t,int32_t))0x80009569u)
#define PLAYING ((uint32_t (*)(uint32_t))0x80002441u)
#define STOP_PAD ((void (*)(uint32_t))0x80002d09u)
#define ASSIGN ((void (*)(uint32_t,const uint16_t*,uint32_t,int32_t,uint32_t,uint32_t))0x80008c69u)
#define RECORD_TARGET ((uint32_t (*)(void))0x80034da9u)
#define CONFIG_PATH(p) ((const volatile uint16_t *)(0x80440dc8u+0x798u+(p)*0x20au)) /* saved pad paths */
#define PENDING(p) B8(0x8044337fu+(p))  /* assignment queued, completion not yet handled (0x800060d0) */
#define RETRY_POLLS 40u         /* about one second of worker polls */
#define POSTS 30u
#define READ ((int32_t (*)(uint32_t,void*,uint32_t,uint32_t*))0x80060621u)
#define NOT_FOUND 0xffffd75au
#define HEAD 1024u              /* stock masters: fmt at 12, PAD, data at 902 */

KEEP MasterRef *mr_state;    /* heap; published once the worker exists */
KEEP uint32_t mr_startup_status;
KEEP const uint32_t mr_layout[]={sizeof(MasterRef),offsetof(MasterRef,revoked),offsetof(MasterRef,task),
    offsetof(MasterRef,handoff_state),offsetof(MasterRef,stop_path),offsetof(MasterRef,path),
    offsetof(MasterRef,posted_path),offsetof(MasterRef,next),offsetof(MasterRef,assigned)};
static const uint16_t RECORDER[]=u"A:\\RECORDER\\";
static const uint16_t MASTER[]=u"\\MASTER.WAV";
static const uint16_t SPLIT[]=u"\\MASTER_01.WAV";   /* the second part of a split take */
static const uint16_t ANCHOR[]=u"MASTER.WAV";
static const uint16_t ANCHOR_PATH[]=u"A:\\SOUND_PAD\\PAD1\\MASTER.WAV";
#define ANCHOR_DIGIT 16u        /* index of the pad digit in ANCHOR_PATH */

static uint32_t interrupt(void) {uint32_t v;__asm__ volatile("mrs %0, ipsr":"=r"(v));return v;}
/* Equal strings of at most n units including the NUL. */
static int same16(const uint16_t *a,const uint16_t *b,uint32_t n) {
    for(uint32_t i=0;i<n;i++){if(a[i]!=b[i])return 0;if(!a[i])return 1;}
    return 0;
}
static int prefix16(const uint16_t *a,const uint16_t *prefix) {
    for(uint32_t i=0;prefix[i];i++)if(a[i]!=prefix[i])return 0;
    return 1;
}
/* Copy src (NUL-terminated) to dst at position at; 0 if it does not fit. */
static uint32_t append(uint16_t *dst,uint32_t at,const uint16_t *src) {
    for(uint32_t i=0;;i++) {
        if(at+i>=MR_PATH)return 0;
        dst[at+i]=src[i];
        if(!src[i])return at+i;
    }
}

/* ---- Recorder task ---- */
static int normal_recording(void) {
    static const uint8_t channels[]={0,1,2,4,6,8,10};
    if(B8(0x801f5f00u)!=255 || (W(0x8077ce70u)&0x557u)!=0x557u)return 0;
    for(uint32_t i=0;i<7;i++)if(!W(0x8077e87cu+channels[i]*4u))return 0;
    return 1;
}
/* Stock recorder start, after all seven streams are registered (0x8000b158).
 * Pad-record takes (a pad record target) are not ordinary takes. */
KEEP void mr_admit(void) {
    MasterRef *g=LD(&mr_state);if(!g)return;
    /* Any admission ends a take whose stop never reached the setter (card
     * cleanup finalizes without it). */
    g->open_take=0;
    if(!normal_recording() || interrupt()){ST(&g->stock_recording,0);return;}
    g->admit_revoked=LD(&g->revoked);
    ST(&g->stock_recording,1);g->open_take=1;
    ST(&g->admitted,g->admitted+1);
}
/* Stock stop cursor setter (0x80006918), inside RecStop before the stock
 * files are finalized. Only RecStop's call ends a take. */
KEEP void mr_stop(uint32_t selected,uint32_t caller) {
    (void)selected;
    MasterRef *g=LD(&mr_state);if(!g)return;
    if(caller!=REC_STOP_RETURN)return;
    ST(&g->stock_recording,0);
    if(!g->open_take)return;
    g->open_take=0;
    /* Build locally: stop_path changes only together with stopped. */
    uint16_t path[MR_PATH];uint32_t n=0;
    while(n<MR_DIR && TAKE_DIR[n]){path[n]=TAKE_DIR[n];n++;}
    path[n]=0;
    if(n>=MR_DIR || n<=sizeof(RECORDER)/2-1 || !prefix16(path,RECORDER) || !append(path,n,MASTER) ||
       LD(&g->revoked)!=g->admit_revoked){g->stop_faults++;return;}
    for(uint32_t i=0;i<MR_PATH;i++)g->stop_path[i]=path[i];
    g->stop_revoked=g->admit_revoked;
    ST(&g->stopped,g->stopped+1);
}

/* ---- Main: assign pad 1, as the Editor's select does ---- */
/* Final states are written only from POSTED and only for the posted serial;
 * a newer POSTED, LOST or SUPERSEDED is never overwritten. The serial is then
 * never handled again. Main does not block between the check and the swap. */
static void handoff_done(MasterRef *g,uint32_t serial,uint32_t state,uint32_t result) {
    uint32_t posted=MR_HANDOFF_POSTED;
    g->handled=serial;
    if(serial!=g->handoff_serial)return;
    g->handoff_result=result;
    __atomic_compare_exchange_n(&g->handoff_state,&posted,state,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
}
/* A saved pad path the chain carries: a take master that fits our buffers. */
static int carried(uint16_t *dst,uint32_t pad) {
    const volatile uint16_t *src=CONFIG_PATH(pad);
    uint32_t n=0;
    while(n<MR_PATH && (dst[n]=src[n]))n++;
    if(n>=MR_PATH || !prefix16(dst,RECORDER))return 0;
    uint32_t tail=sizeof(MASTER)/2-1;
    return n>tail && same16(dst+n-tail,MASTER,tail+1);
}
static int saved_as(uint32_t pad,const uint16_t *path) {
    const volatile uint16_t *src=CONFIG_PATH(pad);
    for(uint32_t i=0;i<MR_PATH;i++){if(src[i]!=path[i])return 0;if(!path[i])return 1;}
    return 0;
}
/* Main task only (priority 13). The stock calls below can block on the card,
 * letting the worker run and supersede this serial meanwhile. */
static void handoff(MasterRef *g,uint32_t serial) {
    if((int32_t)(serial-g->handled)<=0)return;
    if(LD(&g->handoff_state)!=MR_HANDOFF_POSTED || serial!=g->handoff_serial)return;
    /* Revocation is incremented on Main only, so this comparison is exact. */
    if(LD(&g->revoked)!=g->handoff_revoked){handoff_done(g,serial,MR_HANDOFF_SKIPPED,5);return;}
    /* A new take or any RecPlayCtl callback: leave it posted for a repost. */
    if(LD(&g->stock_recording) || RECORDER_BUSY)return;
    /* An assignment still loading has not saved its path yet: wait for its
     * completion (Main clears the flag on success and on failure alike). */
    for(uint32_t p=0;p<MR_PADS;p++)if(PENDING(p))return;
    if((RECORD_TARGET()&255u)<MR_PADS){handoff_done(g,serial,MR_HANDOFF_SKIPPED,2);return;}
    /* Each pad's anchor entry stands in for its master: stock reload keeps
     * an assigned path only while the pad's folder lists this basename. The
     * chain covers the pads from pad 1 up to the first without an anchor. */
    int32_t index[MR_PADS];
    uint16_t anchor[sizeof(ANCHOR_PATH)/2];
    uint32_t pads=0;
    for(uint32_t i=0;i<sizeof(ANCHOR_PATH)/2;i++)anchor[i]=ANCHOR_PATH[i];
    for(;pads<MR_PADS;pads++) {
        anchor[ANCHOR_DIGIT]=(uint16_t)('1'+pads);
        if((index[pads]=LOOKUP(pads,ANCHOR))<0)break;
        if(!same16(PATH_OF(pads,index[pads]),anchor,sizeof(anchor)/2)){handoff_done(g,serial,MR_HANDOFF_FAILED,4|pads<<12);return;}
    }
    if(!pads){handoff_done(g,serial,MR_HANDOFF_FAILED,3);return;}
    /* The new chain: the new take, then the takes now saved on the chain pads
     * in order, skipping hand-picked or empty pads and repeats. Pads past its
     * end keep their sound; pads already holding their entry are skipped. */
    uint32_t length=1,mask=1;
    for(uint32_t i=0;i<MR_PATH;i++)g->next[0][i]=g->posted_path[i];
    for(uint32_t p=0;p<pads && length<pads;p++) {
        if(!carried(g->next[length],p))continue;
        uint32_t repeat=0;
        for(uint32_t q=0;q<length;q++)repeat|=same16(g->next[q],g->next[length],MR_PATH);
        if(!repeat)length++;
    }
    for(uint32_t p=1;p<length;p++)if(!saved_as(p,g->next[p]))mask|=1u<<p;
    /* Format is judged from each pad's anchor entry (48 kHz); of the path only
     * the extension is read. Every pad is checked before any is assigned. */
    for(uint32_t p=0;p<MR_PADS;p++) {
        if(!(mask>>p&1))continue;
        uint32_t format=VALIDATE(g->next[p],p,index[p]);
        if(format){handoff_done(g,serial,MR_HANDOFF_FAILED,0x100u|format|p<<12);return;}
    }
    for(uint32_t p=0;p<MR_PADS;p++)if((mask>>p&1) && PLAYING(p))STOP_PAD(p);
    if(LD(&g->handoff_state)!=MR_HANDOFF_POSTED || serial!=g->handoff_serial){g->handled=serial;return;}
    /* Queued oldest first: the assignments complete (and save) in order, so a
     * shift cut short repeats a take rather than losing one. The stock
     * assignment queues the path pointer: keep it until the next one. */
    for(uint32_t p=MR_PADS;p-->0;) {
        if(!(mask>>p&1))continue;
        for(uint32_t i=0;i<MR_PATH;i++)g->assigned[p][i]=g->next[p][i];
        ASSIGN(0,g->assigned[p],p,index[p],COUNT(p),1);
    }
    /* Queued, not yet loaded: the stock loader opens each master on its task. */
    g->chain_mask=mask;
    handoff_done(g,serial,MR_HANDOFF_ASSIGNED,0);
}

/* ---- Main: five original receive calls ---- */
KEEP int32_t mr_main_receive(uint32_t *packet) {
    int32_t result=RECEIVE(packet);
    MasterRef *g=LD(&mr_state);if(!g)return result;
    if(packet[0]==MR_HANDOFF_EVENT && packet[1]==MR_HANDOFF_MAGIC)handoff(g,packet[2]);
    uint32_t storage=(packet[0]==0 && packet[2]>=0x32 && packet[2]<=0x35) ||
        (packet[0]==1 && packet[1]==0 && packet[2]<=5) ||
        (packet[0]==2 && (packet[2]==0xa2 || packet[2]==0xa3));
    if(storage) {
        /* Paired with the worker: either it sees this revocation before its
         * next file call, or we see file_open and wait for its probe. */
        g->revoke_packet=packet[0]<<16|(packet[1]&255)<<8|(packet[2]&255);
        __atomic_fetch_add(&g->revoked,1,__ATOMIC_SEQ_CST);
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        if(!LD(&g->file_open))g->main_timed_out=0;
        else if(!g->main_timed_out) {
            for(uint32_t i=0;i<MR_WAIT_TICKS && LD(&g->file_open);i++)DELAY(1);
            g->main_timed_out=LD(&g->file_open);
        }
    }
    return result;
}

/* ---- Worker ---- */
static void post(MasterRef *g) {
    g->handoff_posts++;g->handoff_posted_at=g->polls;
    POST(MR_HANDOFF_EVENT,MR_HANDOFF_MAGIC,g->handoff_serial,0,0);
}
static int revoked(MasterRef *g) {return LD(&g->revoked)!=g->take_revoked;}
/* Clean and invalidate the buffer's lines: before a read so no dirty line can
 * later overwrite what DMA wrote, after it so stale lines are dropped. */
static void coherent(const void *p,uint32_t n) {
    uint32_t a=(uint32_t)p&~31u,end=((uint32_t)p+n+31u)&~31u;
    __asm__ volatile("dsb":::"memory");
    for(;a<end;a+=32)W(0xe000ef70u)=a;
    __asm__ volatile("dsb\n\tisb":::"memory");
}
/* Read-only probe. 1 exists (size in *bytes, first *got bytes in head when
 * head is given), 0 not found, -1 error. */
static int probe(const uint16_t *path,uint32_t *bytes,uint8_t *head,uint32_t *got) {
    uint32_t handle=0,info[4]={0};
    int32_t opened=OPEN(&handle,path,0,0x100);
    if(opened)return !handle && (uint32_t)opened==NOT_FOUND?0:-1;
    int ok=!INFO(handle,info);
    if(ok && head) {
        coherent(head,HEAD);
        ok=!READ(handle,head,HEAD,got) && *got<=HEAD;
        coherent(head,HEAD);
    }
    if(CLOSE(handle))ok=0;
    *bytes=info[0];return ok?1:-1;
}
static uint32_t u32(const uint8_t *p) {return p[0]|p[1]<<8|p[2]<<16|(uint32_t)p[3]<<24;}
static int is(const uint8_t *p,const char *t) {return p[0]==t[0] && p[1]==t[1] && p[2]==t[2] && p[3]==t[3];}
/* 48 kHz stereo PCM or float (the anchor's format, which the validator judges
 * for every take) whose data chunk ends exactly at the end of the file, as
 * stock postprocess writes it. A stale header fails the size match. */
static int playable(const uint8_t *h,uint32_t got,uint32_t bytes) {
    if(got<44 || !is(h,"RIFF") || !is(h+8,"WAVE"))return 0;
    int format=0;
    for(uint32_t at=12;at+8<=got;) {
        uint32_t size=u32(h+at+4);
        if(size>bytes)return 0;
        if(is(h+at,"data"))return format && size && at+8+size==bytes;
        if(is(h+at,"fmt ")) {
            if(size<16 || at+24>got)return 0;
            uint32_t tag=h[at+8]|h[at+9]<<8,channels=h[at+10]|h[at+11]<<8;
            format=(tag==1 || tag==3) && channels==2 && u32(h+at+12)==48000;
        }
        at+=8+size+(size&1);
    }
    return 0;
}
static uint32_t check(MasterRef *g) {
    __atomic_store_n(&g->file_open,1,__ATOMIC_SEQ_CST);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    _Alignas(32) uint8_t head[HEAD];
    uint16_t split[MR_PATH];
    uint32_t n=0,bytes=0,got=0,ignored;
    while(g->path[n])n++;
    n-=sizeof(MASTER)/2-1;
    for(uint32_t i=0;i<n;i++)split[i]=g->path[i];
    int master=revoked(g)?-2:probe(g->path,&bytes,head,&got);
    int second=master!=1 || revoked(g) || !append(split,n,SPLIT)?-2:probe(split,&ignored,0,0);
    ST(&g->file_open,0);
    g->master_bytes=bytes;
    if(master==-2 || revoked(g))return MR_REVOKED;
    if(master<0)return MR_IO;
    if(!master)return MR_MISSING;
    if(second<0)return MR_IO;
    if(second)return MR_SPLIT;   /* pad 1 would play only the first part */
    return playable(head,got,bytes)?MR_OK:MR_FORMAT;
}
KEEP uint32_t mr_worker_step(void) {
    MasterRef *g=LD(&mr_state);if(!g)return 0;
    g->polls++;
    uint32_t s=LD(&g->stopped);
    if(s!=g->seen) {
        /* Copy, then confirm no newer stop overwrote the path meanwhile. */
        for(uint32_t i=0;i<MR_PATH;i++)g->path[i]=g->stop_path[i];
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        if(LD(&g->stopped)!=s)return 10;
        g->seen=s;g->pending=1;g->take_revoked=g->stop_revoked;
        /* A newer take replaces one Main has not handled yet. */
        uint32_t posted=MR_HANDOFF_POSTED;
        __atomic_compare_exchange_n(&g->handoff_state,&posted,MR_HANDOFF_SUPERSEDED,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
    }
    if(g->pending) {
        /* Our stop ran inside a RecStop callback; once RecPlayCtl is idle
         * (or recording again), that callback has finalized every file. */
        if(LD(&g->stock_recording) || RECORDER_BUSY)return 10;
        g->pending=0;g->checked++;
        uint32_t status=check(g);
        g->last_status=status;
        if(status){g->refused++;return 0;}
        for(uint32_t i=0;i<MR_PATH;i++)g->posted_path[i]=g->path[i];
        g->handoff_serial++;g->handoff_posts=0;g->handoff_revoked=g->take_revoked;
        ST(&g->handoff_state,MR_HANDOFF_POSTED);post(g);
        return 0;
    }
    /* Repost a handoff Main has not handled (its queue may have been full). */
    if(LD(&g->handoff_state)==MR_HANDOFF_POSTED && g->polls-g->handoff_posted_at>=RETRY_POLLS) {
        uint32_t posted=MR_HANDOFF_POSTED;
        if(g->handoff_posts<POSTS)post(g); /* Main ignores handled serials */
        else __atomic_compare_exchange_n(&g->handoff_state,&posted,MR_HANDOFF_LOST,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
    }
    return 0;
}
#ifdef MR_STACK_PAINT
/* Trial builds measure the worker stack: paint 7 KiB below the entry frame of
 * the 8-KiB stack once; the status query finds the deepest overwritten word. */
KEEP uint32_t *mr_stack_low,*mr_stack_high;
#endif
KEEP __attribute__((noreturn)) void mr_worker_entry(void *unused) {
    (void)unused;
#ifdef MR_STACK_PAINT
    uint32_t sp;__asm__ volatile("mov %0, sp":"=r"(sp));
    uint32_t *high=(uint32_t*)((sp-128u)&~3u),*low=(uint32_t*)((sp-7u*1024u)&~3u);
    for(volatile uint32_t *p=low;p<high;p++)*p=MR_STACK_PAINT;
    mr_stack_low=low;ST(&mr_stack_high,high);
#endif
    for(;;)DELAY(mr_worker_step()==10?10u:25u);
}

/* ---- Startup: two original startup sites ---- */
#define WORKER_WORDS 2048u
#define WORKER_PRIORITY 1u      /* below every stock task: nothing here is timed */
KEEP void startup_observe(uint32_t unused,uint32_t first_result) {
    (void)unused;
    if(!mr_startup_status)mr_startup_status=first_result?2:1;
}
/* After stock idle-task creation. One attempt; state and worker stay until
 * reboot. Hooks do nothing until the state is published, after the worker. */
KEEP void startup_register(void) {
    if(mr_startup_status!=1)return;
    mr_startup_status=3;
    MasterRef *g=ALLOC(sizeof(MasterRef));if(!g)return;
    for(uint32_t i=0;i<sizeof(*g);i++)((uint8_t*)g)[i]=0;
    if(CREATE(mr_worker_entry,"L6PadRef",WORKER_WORDS,0,WORKER_PRIORITY,&g->task)!=1 || !g->task)return;
    ST(&mr_state,g);mr_startup_status=4;
}
