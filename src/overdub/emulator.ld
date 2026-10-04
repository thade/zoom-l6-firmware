/* Deliberately unrelated to device placement. Never use as a patch map. */
ENTRY(od_promote)
SECTIONS {
  . = 0x10000000;
  .text : { *(.text*) *(.rodata*) }
  .ARM.exidx : { *(.ARM.exidx*) }
  .data : { *(.data*) }
  .bss : { *(.bss*) *(COMMON) }
  ASSERT(. <= 0x10010000, "offline overdub image overlaps capture fixture")
}
