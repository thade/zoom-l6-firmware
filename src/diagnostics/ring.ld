ENTRY(health_parser)
PHDRS { probe PT_LOAD FLAGS(7); }
SECTIONS {
 health_parser_resume = 0x800301f4;
 health_sd_resume = 0x8006837c;
 timing_read_resume = 0x80060624;
 timing_write_resume = 0x800622b4;
 . = 0x800b2400;
 .text : { *(.text*) *(.rodata*) } :probe
 .ARM.exidx : { *(.ARM.exidx*) } :probe
 . = ALIGN(32);
 .probe_state : { KEEP(*(.probe_state)) } :probe
 ring_end = .;
 .data : { *(.data*) } :probe
 .bss : { *(.bss*) *(COMMON) } :probe
 ASSERT(SIZEOF(.data)==0 && SIZEOF(.bss)==0,"no separate data/BSS")
 ASSERT(ring_end<=0x800b6ae4,"probe exceeds original MAIN length")
}
