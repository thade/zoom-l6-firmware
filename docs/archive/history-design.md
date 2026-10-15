# Recording history design record (archived)

The design agreed before the history was implemented, moved from
`docs/future-work.md` for release 0.1.0. What was built differs: pads play the
stock masters, so there are no pad recordings or pad-folder history files, and
version 2 lists entries newest first with a 100-line limit. The format as
implemented: [history format](../history-format.md).

## Take links and recording history (original design)

**Implemented in [experiment 28](../../experiments/28-take-history/README.md)**
for pads that play the stock masters: `HISTORY.TXT` in each take folder, a
plain list of `RECORDER/<take>` and `SOUND <path>` lines between an
`L6 HISTORY 1` header and an `END <n>` line, built from the pad files that
actually started during the take. With no separate pad recordings, the
pad-folder history files described below are not needed. The text below is
the original design.

**Confirmed:** each overdub pad recording must reference the main recording it
was created alongside. Both that pad recording and its associated main recording
must reference every other main recording included through overdubbing. Keep
one complete, deduplicated list of inherited master folders, without separating
direct from indirect contributions. Store history in a file in
each pad folder and each main recording folder so a later script can collect
stems for a DAW project, including sessions with undo and alternate takes.

Here, a **master folder** means the normal recording folder containing the input
stems and master mix, not the MASTER.WAV file alone. A pad recording means the
additional stereo take used as backing. Its source master folder is the normal
recording made in the same session; the pad audio is not necessarily a copy of
MASTER.WAV.

**All history references point to master folders.** Master-folder history never
references pads, and pad history also references only master folders. A pad
entry also identifies its own source master folder. This keeps history independent of
later pad rotation and assignment changes.

### Agreed history behavior

The user chooses which take contributes to the next layer. If a take adds
nothing useful, they can use its predecessor as backing for the next recording.
Each selected layer is intended to contribute a unique element, and every
included layer must be tracked. This is a user choice, not a requirement for
automatic silence detection or audio comparison.

Each take retains the history of what was included when it was recorded.
Selecting an older take changes the ancestry of the next recording; it does
not rewrite or delete the histories of takes on the abandoned branch.

For example, record A, use A for B, use B for C, then return to A to record D:

| Take | Included master folders | Own master folder | Complete source set for export |
| --- | --- | --- | --- |
| A | None | A | A |
| B | A | B | A, B |
| C | A, B | C | A, B, C |
| D | A | D | A, D |

D's history excludes B and C. B and C keep their recording folders and their
own histories, and remain available for later use or export. This also applies
when B or C added nothing useful: skipping a take never erases its record.
The pad bank remains `[D, C, B, A]`: chronological access and recording ancestry
are separate.

### Minimal folder history format

Keep the core format as one list of master folders, with a source master folder
on each pad entry. Separate song IDs, pad-take IDs, mix settings and timing
events are not required for this folder-collection format. Field names and JSON
encoding below are a proposal; the folder-only reference model is confirmed.

| Field | Master-folder file | Pad history entry |
| --- | --- | --- |
| `source_master_folder` | Implicit in the containing folder; omit it. | The normal recording folder this pad take was created alongside. |
| `included_master_folders` | Unique list of all inherited master folders. | Same inherited folder list as its source master recording. |

For C recorded using B, with B already including A, the file in master folder C
would contain:

```json
{
  "included_master_folders": ["RECORDER/A", "RECORDER/B"]
}
```

The corresponding entry in a pad folder would contain:

```json
{
  "source_master_folder": "RECORDER/C",
  "included_master_folders": ["RECORDER/A", "RECORDER/B"]
}
```

A, B and C stand for actual recording-folder names. Paths are proposed to be
relative to the SD-card root, using one consistent separator. The master folder
itself is not an inherited source: exporting C collects its own stems plus A
and B. A first take without backing has an empty included list; its
pad entry still identifies its source master folder.

Each pad folder can contain several audio files. Its history file therefore
needs a separate entry for each retained recording, provisionally keyed by the
local audio filename. That key identifies the local entry; all history links
inside it still point exclusively to master folders. Rotation must carry the
matching entry with the audio. The final filename and container format remain open.

### Propagating history into a new take

1. Read and retain the history entry for the backing actually used, before its
   pad assignment can change. Assigned-but-unplayed pads contribute no history.
2. Combine that entry's `source_master_folder` with its `included_master_folders`, removing
   duplicates, to form the new inherited list.
3. Write the list into the new master folder's history file.
4. Write the same list into the new pad entry and set `source_master_folder`
   to the new master folder.

For example, using A to record D writes included `[A]` in D's
master history, and source `D` with that same list in D's pad entry. B and C
are untouched. If multiple backing recordings are supported, combine their
source folders and inherited lists using the same rule.

### Export scope

The flat list is sufficient to identify which recording folders to collect,
without recursively reading earlier histories. It does not preserve which
intermediate take was used as the immediate backing; that distinction is not
required for this collection workflow. List order does not encode parentage.

Whether export also needs timing
information remains open: starting midway, looping or replaying a source cannot
be described by a unique folder list alone. Keep any later timing extension
separate from the agreed core history and use master-folder references there too.
Exact mix recreation is also a separate question from gathering source stems.

### Decision checklist

- [x] Keep one complete unique list of inherited folders; do not distinguish
      direct from indirect contributions.
- [x] Selecting an older backing starts a branch; excluded takes retain their
      folders and original histories.
- [x] Store history files in each pad folder and each main recording folder.
- [x] All history references point only to master folders, never to pads.
- [ ] Finalize the proposed source-folder field, list name, history filename
      and per-audio-file entries within the pad-folder history file.
- [ ] Choose the initial DAW and whether export targets aligned clean stems,
      the heard mix, or both.
- [ ] Establish whether backing always starts at the beginning or may start
      midway, loop, stop early, or use multiple pads in one recording.
- [x] Pad order follows recording chronology, independently of selected ancestry.
- [ ] Decide how new songs are identified and whether unrelated/imported backing
      files may be used. Such files must be identifiable even without source stems.

### Implementation and validation

- [ ] Validate the proposed folder-list examples for a chain, a branch and no
      backing; settle partial or imported backing behavior before fixing the schema.
- [ ] Associate the ordinary recorder folder and extra capture within the same
      recording session, without guessing from timestamps or current pad assignments.
- [ ] Implement the history propagation rules using the actual backing's saved
      entry; define timing collection separately if the export scope requires it.
- [ ] Serialize metadata writes through the file worker, outside audio callbacks.
- [ ] Define an authoritative record and reconciliation rules for copies in
      several folders; interrupted writes must be detectable and repairable.
- [ ] Define what happens when audio completes but metadata fails. Preserve
      the audio and make incomplete lineage explicit before automatic handoff.
- [ ] Validate missing folders, duplicate or inconsistent paths, cycles, corrupted
      history, renamed folders, power interruption and sessions longer than four takes.
- [ ] Verify that the master history and matching pad entry contain the same
      included list, with no duplicates or reference to their own source folder.
- [ ] Test A → B → C followed by A → D: D includes only A and itself, while
      B and C retain their original links and remain independently exportable.
- [ ] Build a read-only export prototype from fixture sessions before connecting
      it to real recordings; report missing sources instead of silently omitting them.
- [ ] Verify the chosen take exports the correct source recordings with the
      correct placement, excluding abandoned branches and duplicate ancestor layers.

