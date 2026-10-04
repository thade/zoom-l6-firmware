#ifndef OD_RELOAD_MANAGER_H
#define OD_RELOAD_MANAGER_H
#include "reload_transport.h"
#include "overdub.h"
#define RM_SETTINGS 0x1094
/* Supplied by the publication owner BEFORE reload. Full expected settings
 * image, plus the four intended runtime pad states, never derived from the
 * state being verified. Unused UTF-16 bytes after path terminators are ignored.
 * opaque[0] lives outside this settings file and is checked in runtime only. */
typedef struct {Pad pads[4];uint8_t settings[RM_SETTINGS];} RmPlan;
typedef struct {
    /* Must attest a caller-owned continuous exclusion of pad edits, playback,
     * recorder/card/USB mutation from plan creation through DONE. Device binding
     * still unimplemented; a reload ledger alone is NOT that exclusion. */
    int32_t (*fenced)(void);
} RmPort;
enum {RM_IDLE,RM_ACQUIRE,RM_START,RM_WAIT,RM_CHECK,RM_VERIFY,RM_RETIRE,RM_RELEASE,RM_DONE,RM_FAILED};
typedef struct {
    uint32_t lock,phase,error,parent,owner;
    RtRuntime *runtime;RtProducer *producer;const RmPort *port;
    RmPlan plan;
} RmManager;
/* Initialize permanent zero-once storage before enabling receive hooks. */
int32_t rm_init(RmManager *,RtRuntime *,RtProducer *,const RmPort *);
int32_t rm_start(RmManager *,const RmPlan *,uint32_t parent);
int32_t rm_step(RmManager *);
/* Cross-task completion query under the manager latch; BUSY retains caller
 * ownership. No file work or state advancement is performed here. */
int32_t rm_completed(RmManager *);
int32_t od_stock_check_settings(const uint8_t expected[RM_SETTINGS]);
#endif
