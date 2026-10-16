# Firmware-written anchors and a full flash backup

Two steps toward 0.2.0 in one diagnostic build:

- **No manual anchor copying.** While the take chain is on (once after
  start-up, whenever it is switched on, and after each card or File Transfer
  Mode change), the firmware gives each pad folder without `MASTER.WAV` the
  anchor file itself, and Main adds it to that
  pad's file list, so installing needs only `L6.BIN`.
- **A full flash backup**, the first step toward testing recovery from a bad
  firmware ([experiment 18](../18-recovery-hang/README.md)): a read-only status
  query returns the mixer's serial flash, bootloader included, 256 bytes at a
  time.

Trial build (diagnostic, with the status query); not for everyday use.

**Prepared locally; not yet installed.** The mixer runs 0.1.0 (experiment 38).

## Anchors (part of 0.2.0)

Stock reload keeps a pad's assigned path only while the pad's folder lists a
file of the same name, so each pad the chain uses needs
`A:\SOUND_PAD\PADn\MASTER.WAV` ([master reference findings](../../docs/research/master_reference_findings.txt),
section 4).

- The worker checks one pad folder per poll, only while the recorder is idle
  (not recording, playing or finalizing) and no take is being handled. A
  folder that already has a `MASTER.WAV`, ours or anyone's, is left alone.
- After a storage change (card inserted or removed, File Transfer Mode in or
  out) every folder is checked again while the chain is on, but only once Main has handled the
  change (the mode change and remount run on Main), the card has been quiet
  for 2 s, and the stock File Transfer Mode flag (`CONFIG+0x2340`, which
  Zoom's own card code checks) is clear. The firmware never touches the card
  while a computer has it. A folder that fails (no card, say) waits for the
  next storage change rather than being retried.
- A missing one is written as `MASTER.TMP` (the same 38,912-byte, 0.1 s
  silent 48 kHz stereo float file as the installers' anchor, byte for byte),
  closed and renamed, inside the same storage-change guard as the history
  files. A recording that starts mid-write stops it after the current 4 KiB
  chunk; the temp file left then (or by a power cut) is replaced next time,
  and the stock pad scan never lists `.TMP` files.
- Main then adds the name to that pad's file list with the stock function
  `0x80008dd8` (as the stock post-record step does for a new pad recording),
  unless it is already listed, so the chain can use the pad at once, with no
  rescan. While the recorder is busy (RecPlayCtl rebuilds the pad lists after
  a pad recording) or an assignment to that pad is loading, Main leaves the
  list alone and the worker asks again about a second later. A request from
  before a storage change is dropped (the card may differ; every folder is
  checked again).
- Status schema 7 reports the pending folders and the existed, created,
  failed and listed counts.

## Flash backup (diagnostic only)

- Kind-8 query: offset and length (1–256 bytes) in, the bytes out (seven per
  eight MIDI bytes), through the stock serial-flash read `0x8001aee8`, which
  waits for the chip to be idle before each read. Refused while the recorder
  records, plays or is busy. Nothing is written to flash.
- `tools/device/l6_flash_backup.py` reads all 4 MiB twice, re-reads blocks
  whose passes differ, and checks the result: the MAIN region must equal the
  installed image and the PANEL and AUDIOGUIDE regions Zoom's stock file. The
  backup (Zoom's code) stays in the ignored `Reference/flash-backup/`.
- Start it at least 30 s after power-on and 15 s after the last panel or
  Editor change: the mixer saves its settings about 10 s after a change and
  once during start-up.
- The stock driver locks the SPI bus per transfer, not per read, as for
  Zoom's own concurrent reads; a settings save running at the same moment is
  the residual risk (it could at worst corrupt that save, not the bootloader
  or firmware), so the backup runs with the mixer idle and untouched.

## Build and checks

- `tools/firmware/build_master_trial.py flash_diag`.
- `tests/emulation/verify_master_ref.py` (27 groups; the anchor group writes
  the folders with the build's code, compares the file with the installers'
  anchor byte for byte, leaves another `MASTER.WAV` alone, waits while
  recording, lists the new names through the stock catalogue code, and the
  chain then uses the pad; then a card change, File Transfer Mode, a
  recording mid-write, a storage change mid-write, no card, and listing while
  the recorder is busy) and `verify_flash_diag.py` (3 groups: reads of
  every region of a synthetic flash, refusals, schema 7).

## Procedure

1. Install over 0.1.0. With the chain on (it is), a few seconds after
   start-up: status shows the four folders checked (existing anchors counted
   as existed).
2. Move `SOUND_PAD/PAD3/MASTER.WAV` aside on the card (File Transfer Mode),
   restart, and confirm the firmware writes it back and lists it (a take then
   reaches pad 3).
3. With the mixer idle and untouched (30 s after power-on, 15 s after any
   change), run the flash backup; it must match the known regions.
