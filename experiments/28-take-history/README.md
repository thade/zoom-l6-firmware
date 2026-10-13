# Take history: HISTORY.TXT in each take folder

The take chain (experiments 25–27) plus a history file in every take folder,
listing all the recordings that went into the take, so a script can follow
the chain back and collect every original stem folder. This implements the
history design in [future work](../../docs/future-work.md#take-links-and-recording-history),
adapted to pads that play the stock masters.

**Prepared locally; not staged or installed.** A trial build with the status
query; an everyday build follows once it works on the mixer.

## The file

`A:\RECORDER\<take>\HISTORY.TXT`, plain text:

```
L6 HISTORY 1
RECORDER/261013_164507
SOUND SOUND_PAD/PAD2/GLORY_BOX.WAV
END 2
```

- One line per included recording folder (`RECORDER/<take>`) or hand-picked
  sound (`SOUND <path>`), relative to the card root, no repeats, UTF-8.
- `END <n>` gives the number of entries, so a cut-off file is detectable.
- `TRUNCATED` before `END` means the list is incomplete: a played take's
  history was unreadable or failed to be written, a pad was started while its
  reassignment was still loading, more than eight pad files played in one
  take, or the file would exceed 4 KiB.
- A take with no backing has `END 0`. Every ordinary take whose master is
  present gets a file, including takes under 2 seconds and split takes.
- A listed take without its own `HISTORY.TXT` (recorded before this firmware)
  contributes just its folder; a script can see its history is unknown.

## How the list is built

- A new hook at the stock pad start (`0x80018316`, inside `0x80018310`, on
  Main for every trigger: pad buttons, MIDI and the Editor) records each pad
  file started while a take records, by its saved path at that moment. Pads
  already playing when recording starts are added at the start (their
  renderer playing flags). Pad starts after RecStop do not count.
- After the take, the worker builds the list: for each pad file that played,
  a take adds its own history's entries and then its folder, any other file a
  `SOUND` line. It writes `HISTORY.TMP` (one write), closes it and renames it
  to `HISTORY.TXT`, so a partial file never carries the final name.
- No history file call is made while a take records or the recorder is
  finalizing (the stock filesystem locks have no priority boosting, so the
  low-priority worker could otherwise delay the recorder). If you start the
  next take straight away, the history is written after it, before that
  take's own; pads are updated meanwhile as before.
- A take whose history could not be written is remembered (until reboot), and
  a leftover `HISTORY.TMP` also marks it, so takes that include it say
  `TRUNCATED` rather than treating it as a take from before this firmware.
- "Played" means the pad started, as the stock firmware sees it: a pad at
  level 0 still counts.

The stock firmware never lists files inside take folders and uses only its own
WAV names there; v1.10 has no on-device take delete, and its folder removal
deletes whole trees. Power loss in the moment the take folder's directory
entry is rewritten (just after each take) is the remaining risk.

## Image

- Local image: `deployment/28_take_history/trial_take_history/L6.BIN`; SHA256
  and sizes in `deployment/28_take_history/manifest.json`. 11 patch sites,
  8,564 bytes of code; about 23.9 KB of state on the heap.
- Builder: `tools/firmware/build_master_trial.py history`. Offline checks:
  `tests/emulation/verify_master_ref.py` (24 groups, nine for history,
  including the A → B → C, then A → D branch example) and
  `tests/emulation/verify_master_trial.py` (6 groups, exact image).

## Status query

`l6_padref_probe.py` schema 3: schema 2 plus history written, failed, last
status (`ok`, `revoked`, `create`, `write`, `close`, `rename`, `name`,
`pending`),
entries, and pad files played in the last take.

## Procedure

Staging uses `deployment/28_take_history/stage28.py`. After the update:

1. Take A with no pads playing; take B with pad 1 (A) playing; take C with
   pad 1 (B) playing; take D with pad 3 (A) playing. Before and after samples
   with `--before-take` as before.
2. A take with a hand-picked sound or two pads playing.
3. `stage28.py settings` in File Transfer Mode prints the newest takes'
   histories: A empty, B lists A, C lists A and B, D lists A.
