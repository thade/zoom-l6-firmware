/* Synthetic emulator placement only. Not an L6 patch map. */
ENTRY(extra_capture)
SECTIONS {
 . = 0x10010000;
 .text : { *(.text*) *(.rodata*) }
 .ARM.exidx : { *(.ARM.exidx*) }
 .data : { *(.data*) }
 .bss : { *(.bss*) *(COMMON) }
}
