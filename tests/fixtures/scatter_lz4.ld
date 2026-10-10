/* Emulator-only loader, inside the source span already repacked by the stock
 * codec experiment. It must not overwrite itself or use uninitialized globals. */
ENTRY(scatter_lz4)
PHDRS { code PT_LOAD FLAGS(5); }
SECTIONS {
 . = 0x800a9408;
 .text : { *(.text*) *(.rodata*) } :code
 .ARM.exidx : { *(.ARM.exidx*) } :code
 .data : { *(.data*) } :code
 .bss : { *(.bss*) *(COMMON) } :code
 ASSERT(SIZEOF(.data) == 0 && SIZEOF(.bss) == 0, "loader must have no mutable globals")
 ASSERT(. <= 0x800a9808, "offline loader exceeds 1 KiB budget")
}
