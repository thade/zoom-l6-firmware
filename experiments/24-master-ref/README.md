# Master reference: pad 1 plays the last take's MASTER.WAV

Experiments 20–23 captured a pre-compressor copy of each take in real time,
which works but overruns when the stock filesystem stalls for over a second.
This trial drops the capture altogether: after each ordinary take, pad 1 is
assigned the stock master the take just wrote,
`A:\RECORDER\<take>\MASTER.WAV`, in place. The master compressor is baked into
that file, so overdub with the master compressor off.

**Installed 12 October 2026; passed. The overdub loop works with the stock
master, with no real-time capture.** Recovery from an image that fails before
Main remains unproven ([experiment 18](../18-recovery-hang/README.md) is parked).

## Results

| Step | Take folder | Master | Worker check | Pad 1 afterwards |
|---|---|---|---|---|
| Takes 1–2 (two recordings) | `261012_150924` (second) | 18,681,230 bytes, about 49 s | ok, ok | that take; plays correctly (user check) |
| Take 3, overdub with pad 1 playing | `261012_153024` | 16,611,726 bytes, about 43 s | ok, no storage packets | that take; both layers play (user check) |
| Cold reboot | | | | still `261012_153024`, both layers |
| File Transfer Mode cycle | | | | still `261012_153024`, both layers |

Every take was checked and assigned on the first post (`handoff_posts` 1), with
no refusals or stop faults. `L6PADSETTING.ZST` saved pad 1 as
`A:\RECORDER\261012_153024\MASTER.WAV`; pads 2–4 were unchanged. The take
folder held its seven stock files and no `Work` folder. The anchor was intact,
and the pad name shows `MASTER.WAV` (catalogue index 4 of 11), as designed.
Pad 1 played the previous master from `A:\RECORDER` while the next take
recorded to the same card. Worker stack peaked at 2,356 of 8,192 bytes, and
free heap stayed at 154,736 bytes, 26 KB more than experiment 23.

Staging finding: writing the anchor from macOS made an AppleDouble companion
`._MASTER.WAV` in PAD1. The staging script now removes the one it creates
(older `._` files elsewhere on the card were already present and harmless).
Evidence stays in `deployment/24_master_ref/`.

Untested: deleting the referenced take folder, and takes long enough to split.

## How it works

1. **RecStop** (stop cursor setter, RecStop's call only): copy the take folder
   the stock recorder keeps at `0x8060ff80` and append `\MASTER.WAV`. Pad-record
   takes and PlayStop are ignored.
2. **Worker** (priority 1, polls every 25 ms): once the RecPlayCtl callback that
   contained the stop has ended (busy word `0x80578ec0` clear), the stock files
   are finalized and renamed. It opens the master read-only and reads its
   header: 48 kHz stereo, with the data chunk ending exactly at the end of the
   file as stock postprocess writes it. It also checks there is no
   `MASTER_01.WAV` (a take split at about 93 minutes in 32-bit float would
   play only its first part). Then it posts a private Main event, reposting about once a second
   for 30 seconds.
3. **Main**: the Editor select steps, but looking up the **anchor**
   `MASTER.WAV` in the PAD1 catalogue and passing the take's full path; stop
   pad 1 if it plays, then queue the stock assignment. Stock code loads the file
   and saves `L6PADSETTING.ZST`.

Nothing is written to the card, the DSP code and stock ring size are stock, and
there is no real-time path.

### The anchor file

Stock reload (boot, File Transfer Mode exit) keeps a pad's saved full path only
if the pad's folder lists a file with the same name; otherwise it falls back to
the first valid file there and saves that. So `A:\SOUND_PAD\PAD1\MASTER.WAV` must
exist permanently: a 0.1-second silent 48 kHz stereo float WAV with the header
layout experiment 21's files used. Staging copies it. Without it, nothing is
assigned (`handoff_result` 3). Emulated with the original reload, assignment
and settings code: with the anchor, the reference survives the queued
assignment, a save, a cold-boot load and the reload; without it, a PAD1 file
such as `BACKING.WAV` replaces it.

Side effects to expect:
- The mixer's and the Editor's pad name shows `MASTER.WAV` for every take.
- Selecting `MASTER.WAV` from PAD1 manually assigns the silent anchor.
- Deleting the referenced take folder leaves pad 1 pointing at a missing file
  until the next take (untested).

## What it answers

- Does pad 1 play a stock master in place from `A:\RECORDER`, in 32-bit float
  (or the recorder's configured format)?
- Does the reference survive a reboot and a File Transfer Mode cycle with the
  anchor present?
- Can the next take record while pad 1 plays the previous master from the same
  card, with stock files intact?
- Do status and the stock pad name behave as expected?

## Image

- Local image: `deployment/24_master_ref/trial_master_ref/L6.BIN`; anchor
  `deployment/24_master_ref/anchor/MASTER.WAV` (38,912 bytes).
- SHA256 and sizes: in `deployment/24_master_ref/manifest.json`.
- Ten patch sites (two startup, admission, stop setter, five Main receive calls,
  query parser); no DSP or ring patches.
- Builder: `tools/firmware/build_master_trial.py`. Offline checks:
  `tests/emulation/verify_master_ref.py` (13 groups) and
  `tests/emulation/verify_master_trial.py` (5 groups, exact image).

## Status query

`tools/device/l6_padref_probe.py` (request `F0 52 00 00 6F 07 <token> F7`,
reply kind 7): recorder counts, the worker's last check (`ok`, `revoked`,
`missing`, `split`, `io`, `format`), master size, handoff state and
result, worker stack, heap, and the path Main last assigned.

## Procedure

Staging uses `deployment/24_master_ref/stage24.py` with the MIDI transfer tool,
as for experiment 23, and also copies the anchor into PAD1.

1. Idle samples with `--session --manifest deployment/24_master_ref/manifest.json`.
2. Record about 30 seconds with something audible, stop, wait five seconds,
   then an after sample with `--before-take`: handoff `assigned`, and the
   assigned path is the new take folder's `MASTER.WAV`.
3. Play pad 1: it plays the take just recorded.
4. Record a second pass with pad 1 playing, then repeat step 2: pad 1 now holds
   the second take, which contains both layers.
5. Reboot, and also cycle File Transfer Mode: pad 1 still plays the latest take.

A refused check or a skipped or failed handoff is a finding to record with its
code. Stock recordings and pads 2–4 must stay unchanged throughout. Restore
stock with `deployment/01_usb_marker/stock_control/L6.BIN` if anything looks
wrong.
