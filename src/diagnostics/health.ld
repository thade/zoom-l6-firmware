ENTRY(health_parser)
PHDRS { probe PT_LOAD FLAGS(7); }
SECTIONS {
 health_parser_resume = 0x800301f4;
 health_sd_resume = 0x8006837c;
 . = 0x800b6000;
 health_start = .;
 .text : { *(.text*) *(.rodata*) } :probe
 .ARM.exidx : { *(.ARM.exidx*) } :probe
 . = ALIGN(32);
 .probe_state : { KEEP(*(.probe_state)) } :probe
 health_end = .;
 .data : { *(.data*) } :probe
 .bss : { *(.bss*) *(COMMON) } :probe
 ASSERT(SIZEOF(.data)==0 && SIZEOF(.bss)==0,"probe must have no separate data/BSS")
 ASSERT(health_end<=0x800b6ae4,"probe exceeds original MAIN length")
}
