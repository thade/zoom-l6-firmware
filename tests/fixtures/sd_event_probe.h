/* OFFLINE ONLY: caller must pin the object and exclude old IRQ/task posts. */
#ifndef L6_SD_EVENT_PROBE_H
#define L6_SD_EVENT_PROBE_H
#include <stdint.h>
enum { SDP_EV_CONTEXT=1,SDP_EV_IRQ,SDP_EV_IDENTITY,SDP_EV_SCHEMA,
       SDP_EV_HARDWARE,SDP_EV_FLAGS,SDP_EV_TOKEN,SDP_EV_PENDING,SDP_EV_REARM };
typedef struct { uint32_t calls,fault,takes,disabled,rearmed,flags_before; } SdEventProbe;
extern volatile SdEventProbe sdp_event_state;
extern volatile uint32_t sdp_kernel_port;
int32_t sdp_event_context_ready(void);
int32_t sdp_event_drain(uint32_t unit,uint32_t event);
#endif
