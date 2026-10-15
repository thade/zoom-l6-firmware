# HISTORY.TXT format

Every ordinary take recorded with this firmware gets
`A:\RECORDER\<take>\HISTORY.TXT`: plain UTF-8 text listing the recordings and
pad sounds the take includes. It lets a script walk back from a final mix to
every original recording and its separate tracks. Version 2 is written from
0.1.0; version 1 was written by experiments 28–33.

```
L6 HISTORY 2
RECORDER/261015_204724
SOUND SOUND_PAD/PAD2/GLORY_BOX.WAV
RECORDER/261014_123107
RECORDER/261014_120212
END 4
```

## Lines

- `L6 HISTORY 2`: the header and version.
- One line per entry, no repeats, paths relative to the card root with `/`:
  - `RECORDER/<take>`: a recording folder (its `MASTER.WAV` and track files);
  - `SOUND <path>`: a pad sound that is not a take, as it was assigned.
- `OMITTED` (optional): older entries were left out to keep the list at 100
  lines. Nothing is lost: each listed take's own `HISTORY.TXT` lists what it
  included.
- `TRUNCATED` (optional): the list is incomplete. A played take's history was
  missing because it could not be read or written, a pad was started while its
  reassignment was still loading, more than eight pad files played in one take,
  or the file reached 4 KiB.
- `END <n>`: the number of entries, so a cut-off file is detectable.

A take with no backing has `END 0`. Every take whose master is on the card
gets a file, including takes under 2 seconds (which stay off the pads) and
split takes. A listed take without its own `HISTORY.TXT` was recorded before
this firmware, so its own history is unknown.

## Order and limit (version 2)

Newest first: first the pad files that played during the take (pads already
playing when recording began, then each pad file in the order it was started;
each a take folder or a `SOUND` line), then each played take's own history in
turn. At most 100 entries; past that the rest,
the oldest, is left out and `OMITTED` is written. With one take played per
layer, the list reads back through the layers in order.

Version 1 files list each played take's history before the take itself
(oldest first) and have no limit or `OMITTED` line. The firmware reads both
versions when it builds a new history.

## Collecting everything behind a take

Read the take's `HISTORY.TXT`. For a complete set, also read the history of
every `RECORDER/<take>` it lists and add what they list, repeating until
nothing new appears. That recovers entries an `OMITTED` file left out, and it
works across version 1 and 2 files.

## How it is written

After a take stops and the L6 has finished writing its own files, the
firmware's low-priority task builds the list, writes `HISTORY.TMP` in one
write, closes it and renames it to `HISTORY.TXT`, so a partial file never has
the final name. It makes no card access while the L6 records, plays back or
finalizes a recording; if you start the next take straight away, the history
is written after it. Details: [experiment 28](../experiments/28-take-history/README.md)
and [master reference findings](research/master_reference_findings.txt).
