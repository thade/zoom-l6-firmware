/* Separate OFFLINE boot overlay, not a deployable layout. Original compressed
 * DSP bytes are consumed first, then replaced by code and zeroed globals.
 * The planner must also prove no overlap with loader or unread code input. */
ENTRY(extra_capture)
PHDRS { code PT_LOAD FLAGS(5); globals PT_LOAD FLAGS(6); }
MEMORY {
 added_code (rx) : ORIGIN = 0x800a9688, LENGTH = 0x7378
 added_globals (rw) : ORIGIN = 0x800b0a00, LENGTH = 0x780
}
SECTIONS {
 PROVIDE(health_parser_resume = 0x800301f4);
 . = 0x800a9688;
 placement_code_start = .;
 .text : { *(.text*) *(.rodata*) } >added_code :code
 .ARM.exidx : { *(.ARM.exidx*) } >added_code :code
 placement_code_end = .;
 . = 0x800b0a00;
 placement_globals_start = .;
 .data : AT(placement_code_end) { *(.data*) } >added_globals :globals
 placement_data_load = LOADADDR(.data);
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } >added_globals :globals
 placement_globals_end = .;
 placement_load_end = placement_code_end + SIZEOF(.data);
 ASSERT(SIZEOF(.data) == 0, "source reuse supports only zero-initialized globals")
 /* MEMORY regions enforce the code/global boundary on final section sizes. */
 ASSERT(placement_globals_end <= 0x800b1180, "reused globals exceed reserved interval")
}
