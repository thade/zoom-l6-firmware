/* Separate offline fixture beside capture-only.elf; no device address plan. */
ENTRY(dependency_write)
SECTIONS {
 . = 0x10020000;
 .text : { *(.text*) *(.rodata*) }
 .ARM.exidx : { *(.ARM.exidx*) }
 .data : { *(.data*) }
 .bss : { *(.bss*) *(COMMON) }
 ASSERT(. <= 0x10030000, "offline capture I/O fixture exceeds its mapped page range")
}
