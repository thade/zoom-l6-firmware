/* Stock v1.10 addresses and access helpers shared by the master-reference
 * sources (take chain, history, anchors, switches, stereo AUX, status). */
#ifndef L6_STOCK_H
#define L6_STOCK_H
#include <stdint.h>

#define LD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define ST(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define W(a) (*(volatile uint32_t *)(a))
#define B8(a) (*(volatile uint8_t *)(a))

#define TICKS W(0x801f9050u)          /* 1 ms tick */
#define POST ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t))0x80020ca1u)   /* post an event to Main */
#define SAVE ((void (*)(void))0x80006ab9u)   /* request a settings save (as record start does) */
#define REC_STATE B8(0x80578ebcu)     /* recorder: 1 recording (any target), 2 playing, else 0 */
#define RECORDER_BUSY W(0x80578ec0u)  /* RecPlayCtl is running a callback (RecStop includes finalize) */

/* Global settings, saved to internal flash. Byte pairs in the spare run
 * CONFIG+0x30d..0x31c, which stock code never uses, checks or puts in
 * scenes, hold our switches: on only for the exact pair, so a mixer that
 * never switched (zero) behaves as stock. */
#define CONFIG 0x80440dc8u
#define AUX_MODE ((volatile uint8_t *)(CONFIG+0x30du))     /* A5 5A: stereo AUX */
#define CHAIN_MODE ((volatile uint8_t *)(CONFIG+0x30fu))   /* C3 3C: take chain on */
#define SKIP_MODE ((volatile uint8_t *)(CONFIG+0x311u))    /* 96 69: no track files for muted channels with no sends (track_mask.c) */
#define CONFIG_PATH(p) ((const volatile uint16_t *)(CONFIG+0x798u+(p)*0x20au))   /* saved pad paths */
#endif
