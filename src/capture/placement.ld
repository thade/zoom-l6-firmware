/* Offline candidate only. Neither interval has device ownership approval.
 * Data initializers require a copier; BSS requires zeroing before hook entry.
 * The vendor MAIN loader's acceptance of extended code is still unknown. */
ENTRY(extra_capture)
PHDRS {
 code PT_LOAD FLAGS(5);
 globals PT_LOAD FLAGS(6);
}
SECTIONS {
 . = 0x800b6b00;
 placement_code_start = .;
 .text : { *(.text*) *(.rodata*) } :code
 .ARM.exidx : { *(.ARM.exidx*) } :code
 placement_code_end = .;
 . = 0x80960080;
 placement_globals_start = .;
 .data : AT(placement_code_end) { *(.data*) } :globals
 placement_data_load = LOADADDR(.data);
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } :globals
 placement_globals_end = .;
 placement_load_end = placement_code_end + SIZEOF(.data);
 ASSERT(placement_load_end < 0x801f5400, "candidate code reaches a stock scatter destination")
 ASSERT(placement_globals_end <= 0x809600e0, "candidate globals exceed proposed arena")
}
