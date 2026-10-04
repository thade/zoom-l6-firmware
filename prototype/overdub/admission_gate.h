#ifndef OD_ADMISSION_GATE_H
#define OD_ADMISSION_GATE_H
#include <stdint.h>

/* Proposed cooperative admission protocol, NOT installed stock hooks.
 * Zero-initialize once before any participants run. Never reset a live gate.
 * Every accepted activity owns exactly one count until actual completion,
 * including time in a queue and asynchronous I/O. Rejected work owns none.
 * Caller identity and balanced ownership are integration responsibilities.
 * Internal promotion work uses its owner's exclusive admission; it must not
 * re-enter the ordinary work API. No public fault recovery is provided. */
typedef struct { uint32_t word; } OdGate;
enum { OD_GATE_OK, OD_GATE_BUSY, OD_GATE_FAULT, OD_GATE_MISUSE };
#define OD_GATE_PROMOTING UINT32_C(0x80000000)
#define OD_GATE_FAILED UINT32_C(0x40000000)
#define OD_GATE_COUNT UINT32_C(0x3fffffff)
int32_t od_gate_work_begin(OdGate *);
int32_t od_gate_work_end(OdGate *);
int32_t od_gate_promote_begin(OdGate *);
/* Only a caller already owning one work admission may use this. On failure
 * it still owns that admission and must finish/release it normally. */
int32_t od_gate_upgrade(OdGate *);
int32_t od_gate_promote_end(OdGate *, uint32_t failed);
void od_gate_fail(OdGate *);
#endif
