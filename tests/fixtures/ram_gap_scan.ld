/* Offline scanner controls, never a deployed firmware layout. */
ENTRY(gap_arithmetic)
stock_memset = 0x8000178f;
SECTIONS {
  .text 0x800c0000 : { *(.text*) }
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }
}
