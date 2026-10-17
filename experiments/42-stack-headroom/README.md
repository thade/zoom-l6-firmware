# Task stack headroom

[Release 0.3.0](../41-linked-limiters/README.md) with the status query, which
now reports how much stack the stock recorder, Main and MIDI tasks and the
worker have never used, and the least stack each hook found free. Trial build
(diagnostic); not for everyday use.

**Built 17 October 2026; not yet installed.**

## Why

The hooks run on stock tasks whose stack sizes had not been looked up, and
only the worker's stack had been measured. A stack overflow on the recorder
would crash the mixer rather than degrade audio. The sizes and the hooks'
depth are in the [task stack findings](../../docs/research/task_stack_findings.txt):
the recorder has 16 KiB and the hooks add at most about 400 bytes; Main has
32 KiB and the hooks add about 220. The query itself runs on a 4 KiB MIDI
task, and that is the margin this build is for.

## What it reports

Zoom's kernel fills every task stack with `A5` bytes when it creates the
task, so the bytes at the bottom that are still `A5` have never been used.
Status schema 8 (built with `-DSTACK_DIAG`, the release sources unchanged)
replaces the AUX gain rows with:

- the headroom in bytes of RecPlayCtl (the recorder), Main,
  MidiSettingRcvMsg (which runs the Editor parser and so the query) and the
  worker;
- for each of the five hooks (record start, stop, pad start, Main's receive,
  the query), the least stack it found free below its own frame and the task
  it ran on.

`tools/device/l6_padref_probe.py` decodes both into `headroom` and `hooks`.

## Build and checks

- `tools/firmware/build_master_trial.py stack_diag`.
- `tests/emulation/verify_stack_diag.py` (3 groups: the build patches the
  release sites plus the query and the tree still builds 0.3.0; schema 8
  reads the headroom from control blocks and stacks laid out as the creator
  leaves them; each hook notes its minimum and the task it ran on).

## Procedure

1. Install over 0.3.0 and let the mixer start up. Sample the status
   (`l6_padref_probe.py --output deployment/42_stack_diag/idle.jsonl`): the
   four headroom figures, and `query` as the one hook that has run, on
   `midisetting`.
2. Record a take with pads playing, stop it, let the chain assign it, open
   the Editor and change a few settings, switch the AUX mode and the chain
   off and on. Sample again: every hook has a task (`admit` and `stop` on
   `recplayctl`, `play` and `receive` on `main`) and a free figure.
3. Leave the mixer in ordinary use for a session and sample once more. The
   headroom figures can only fall; the final ones are the result.

What to compare: each hook's free figure against its remaining depth in the
findings (the figure is taken below the hook's own frame, so what remains is
its callees, at most 48 bytes), and each task's headroom against its size.
Below about 1 KiB on any task is worth a change.

## Results

Not yet installed.
