/* OFFLINE ONLY. Native pre-address checks under an explicit source lease.
 * The QUIET provider must exclude/join old hardware, IRQ and task posts and
 * pin both SD/event users through address programming and completion. It is
 * not permission inferred from software generations or quiet register bits. */
#ifndef L6_SD_ADMISSION_PROBE_H
#define L6_SD_ADMISSION_PROBE_H
#include <stdint.h>
typedef struct { uint32_t address,site,task,prepared,calls,fault; } SdAdmissionProbe;
extern volatile SdAdmissionProbe sdp_admission_state;
extern volatile uint32_t sdp_chunk_admit_port;
void sdp_admission_begin(void);
void sdp_before_address(uint32_t address,uint32_t site);
int32_t sdp_native_admit(uint32_t unit,uint32_t event,uint32_t address,uint32_t site);
/* Caller must already have a valid source lease and exclusively own the span.
 * This predicate does not establish either contract or recover a failed IO. */
int32_t sdp_native_chunk_join(uint32_t unit,uint32_t event,uint32_t address,uint32_t bytes);
#endif
