#ifndef OD_RELOAD_TRANSPORT_H
#define OD_RELOAD_TRANSPORT_H
#include "reload_ownership.h"
/* Emulator-only replacement transports. These are larger than the existing
 * 32-byte callback and 20-byte UI queues. Both endpoints and queue allocation
 * must change together; this does not describe an installed firmware patch. */
typedef struct {RlEnvelope tag;uint32_t body[8];} RtWorkerPacket;
typedef struct {RlEnvelope tag;uint32_t body[5];} RtUiPacket;
enum {RT_IDLE,RT_READY,RT_RUNNING,RT_ERROR,RT_COMPLETE,RT_DONE};
typedef struct {
    uint32_t lock,phase;RlEnvelope tag;
    uint32_t error,body_result,body[8];
} RtTask;
typedef struct {uint32_t lock,owner,sends,body_result;} RtProducer;
typedef struct {
    int32_t (*producer)(void);
    int32_t (*worker)(const uint32_t *);
    int32_t (*ui)(const uint32_t *);
    int32_t (*send_worker)(const RtWorkerPacket *);
    int32_t (*send_ui)(const RtUiPacket *);
    int32_t (*close)(uint32_t);
    int32_t (*open)(uint32_t,uint32_t,uint32_t,uint32_t);
    int32_t (*write)(uint32_t,uint32_t,uint32_t,uint32_t *);
} RtPort;
typedef struct {RlCoordinator *coordinator;const RtPort *port;} RtRuntime;
/* Permanent zero-once contexts, one producer/task context per execution task.
 * Scheduler must bind the correct task at intercepted stock boundaries. A task
 * may not be reused while READY/RUNNING/ERROR/COMPLETE. No locks span RTOS waits
 * except each task's own nonblocking reentry guard (never shared across tasks).
 * Native producer body calls rt_queue through a boundary trampoline. Native
 * worker calls rt_event and native I/O uses the attributed wrappers below. */
int32_t rt_produce_managed(RtRuntime *,RtProducer *,uint32_t parent,uint32_t token);
int32_t rt_produce(RtRuntime *,RtProducer *,uint32_t parent);
/* Retire only after external verification; permits this producer's next job. */
int32_t rt_retire(RtRuntime *,RtProducer *);
int32_t rt_queue(RtRuntime *,RtProducer *,const uint32_t body[8]);
int32_t rt_receive(RtTask *,const void *packet,uint32_t role);
/* BUSY retains the copied packet and return phase; retry never reexecutes a
 * body which has returned. Final postcondition verification remains external. */
int32_t rt_run(RtRuntime *,RtTask *);
int32_t rt_event(RtRuntime *,RtTask *,const uint32_t body[5]);
int32_t rt_close(RtRuntime *,RtTask *,uint32_t handle);
/* args[4] is the trusted public-open caller LR, captured per task by the entry
 * trampoline. Only the stock settings writer's existing-file probe permits
 * NOT_FOUND; its subsequent creation attempt and all other errors are checked. */
int32_t rt_open(RtRuntime *,RtTask *,const uint32_t args[5]);
int32_t rt_write(RtRuntime *,RtTask *,const uint32_t args[4]);
#endif
