# Future work

Updated 6 October 2026. This tracker covers the requested overdub workflow,
recording history, browser configurator and optional stereo AUX send. Requirements
below are confirmed where stated; proposed behavior remains open for discussion.
Unchecked items are planned work, not implemented features.

The immediate foundation remains reliable capture and single-pad handoff on the
L6. The [current architecture](architecture.md), [progress](progress.md) and
[remaining device gates](research/remaining_device_gates.txt) track that work.
All three small firmware trials now have recorded stock restoration. Capture
and automatic handoff still need device integration and validation.

## Work order and status

| Work | Status | Dependency and next result |
| --- | --- | --- |
| Reliable capture and single-pad handoff | Existing integration work | Complete the device gates before enabling automatic publication. |
| Take links and timing | Folder references and branching agreed | Finalize the small history format; clarify timing and export separately. |
| Four-pad take history | Requested | Prove pad catalogue/file placement and recovery across several assignments. |
| Normal and overdub modes | Requested | Define saved pad banks and when a mode change takes effect. |
| DAW export script | Future consumer of take links | Choose the initial DAW and export behavior after the metadata contract is agreed. |
| Browser configurator | Requested | Inventory editor functions and verify browser/device communication. |
| Stereo AUX option | Promising offline evidence | Prototype consistent stereo controls and verify output processing and hardware. |

Design take links now, alongside capture integration. Add rotation and mode
switching after the basic handoff works. Browser protocol research and AUX
investigation can proceed independently; neither is a prerequisite for capture.

## Four-pad take history

**Confirmed:** pad 1 holds the newest take, pad 2 the second newest, pad 3 the
third newest and pad 4 the fourth newest. This is a shifting history, rather
than cycling the destination of each new take through pads 1 to 4.

Confirmed successful transition, newest first: `[C, B, A, empty]` becomes
`[D, C, B, A]` after D is verified and published. Takes that fall out of the four
slots remain on disk. Failed or cancelled captures do not shift the history.
Pad order follows recording chronology, even when D uses A as backing and its
history excludes B and C. The pads offer recent takes to choose from; they do
not represent the ancestry of the newest take.

- [x] Keep the four newest recordings on the pads, independently of take ancestry.
- [ ] Define selecting an older backing, undo, redo and starting a new song.
- [ ] Establish how files remain selectable across the four pad-specific
      folders and catalogues. Do not assume changing assignments alone works,
      or that moving a file cannot invalidate another reference.
- [ ] Extend the single-pad controller to snapshot, assign and verify the
      complete intended bank, preserving each pad's agreed playback settings.
- [ ] Define durable recovery for partial catalogue, assignment and settings
      changes, including power loss. Never report a partially shifted bank as ready.
- [ ] Test first through fifth takes, older-backing selection, failed saves,
      missing files, full catalogues, restart and repeated overdubs.

Completion means the bank has the expected ordering after each successful pass,
old audio remains recoverable and interruption cannot silently change which take
will be used as backing. The current controller changes only one pad; its four
diagnostic result records are not a complete history or rotation implementation.

## Normal and overdub modes

**Confirmed:** provide a setting to switch between the overdub feature and normal
sound-pad functionality.

Proposed behavior is to retain separate normal and overdub pad banks. Returning
to normal mode restores the user's normal assignments and settings; returning
to overdub mode restores the song's take bank. Mode changes take effect only at
a stopped boundary after recording, playback and pending file work have finished.

- [ ] Decide where the setting is available on the device and in the configurator.
- [ ] Agree on the initial mode, whether it survives reboot and whether normal
      mode disables extra capture and take metadata as well as automatic rotation.
- [ ] Define which pad settings belong to each bank and how external editor
      changes interact with the saved banks.
- [ ] Implement bank persistence and a recoverable mode transition.
- [ ] Verify normal pad behavior, repeated switching, restart and failed restoration.

Completion means both modes are usable without losing their saved assignments
or unexpectedly changing mode during a take.

## Take links and recording history

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

## Browser configurator

**Confirmed:** create a web-based configurator to replace the Zoom tool.

Start with a parity inventory covering connection, settings, pad assignment,
file-transfer controls and whichever other editor functions are needed. Existing
[device helpers](../tools/device/) provide protocol and readback starting points;
the [initial editor inspection](research/editor_findings.txt) is historical research,
not a complete protocol specification.

- [ ] Agree on supported computers, browsers and required editor functions.
- [ ] Test whether browser MIDI with SysEx permission can reach the necessary
      device endpoints. Evaluate a local bridge only if direct access is insufficient.
- [ ] Separate device control from SD-card file access and establish each workflow.
- [ ] Implement connection/status and read-only settings inspection first.
- [ ] Add verified settings changes and normal pad configuration, then custom
      firmware mode, take history and any supported stereo AUX setting.
- [ ] Detect firmware capabilities and avoid offering unsupported controls.
- [ ] Test disconnect/reconnect, file-transfer transitions, stale state and
      conflicts with another connected editor.

Completion means the agreed editor workflows work with verified device state.
Browser access, protocol coverage and file access remain feasibility checks;
full editor replacement is not yet a proven scope. A history browser and DAW
export interface are possible later additions, not prerequisites for this tool.

## Optional stereo AUX send

**Confirmed:** investigate an option to use AUX 1 and AUX 2 as one stereo send.
The [stereo AUX investigation](research/stereo_aux_findings.txt) finds a practical
firmware route: the original mixer retains separate input lanes and independent
gains to both AUX buses. Eleven offline test groups verify stereo separation
with proposed gain settings, native pan/balance factors and separate output
conversion/copy paths. The mode is not implemented; physical outputs and the
intervening gain/protection processing still need validation.

Proposed interpretation: AUX 1 carries left and AUX 2 carries right, with a
linked send level and defined stereo placement. Agree whether this should be
an independent stereo send mix or a copy of the main stereo mix before implementation.

- [ ] Decide whether send pan follows channel pan or has a separate setting,
      and how stereo inputs, pads and effects returns feed the pair.
- [ ] Define linked levels, pre/post behavior and restoration of independent mono settings.
- [x] Establish that the stock mixer can route separate left/right input samples
      into the AUX pair and preserve them through the examined output conversion/copy.
- [ ] Implement a coefficient adapter covering control changes, scenes, startup,
      MIDI/editor updates and synchronized gain ramps. Linking knob values alone
      still produces mono sums.
- [ ] Validate full output gain/protection processing, DMA/codec routing and the
      two physical jacks, including stereo delay and gain matching.
- [ ] Measure code space, processing cost and interaction with recording and effects.
- [ ] If feasible, prototype behind an optional mode and verify left/right isolation,
      gain, clipping, timing and unchanged mono behavior when disabled.

The candidate reuses existing audio mixing loops and requires no extra capture
buffer or file I/O. Its control overhead and firmware size remain unmeasured.
Initial scope is the six input strips; direct pad/internal-effect sends would
require additional routing work.

### Proposed scene behavior

Use a **global AUX routing mode with scene-specific send mixes**. The global
setting selects two independent mono sends or one stereo send, with AUX 1 as
left and AUX 2 as right. Recalling a scene changes the mix without changing
that mode, because the mode reflects how the outputs are connected.
This is a design proposal, not implemented behavior.

Stock scenes already store AUX send amounts, pre/post choices, channel pan,
levels and mute settings. See the [official L6 manual](https://zoomcorp.com/manuals/l6-en/),
Saving settings (scenes). The stereo adapter must interpret those settings
during recall; applying stock AUX gains unchanged would restore mono sums.

| Setting or action | Proposed behavior in stereo mode |
| --- | --- |
| Routing mode | Global; scene recall leaves it unchanged. |
| Send amount | One amount per channel, recalled from the scene. |
| Pre/post choice | One shared choice per channel for the stereo pair. |
| Stereo placement | Follow the recalled channel pan/balance. |
| Recall transition | Recalculate both AUX gain rows together and coordinate gain ramps to avoid abrupt or inconsistent left/right changes. |
| Return to mono mode | Restore independent AUX settings rather than using the derived left/right gains as mono send values. |

For existing scenes, use their **AUX 1 send amount and pre/post choice** as the
stereo-send settings. Retain their AUX 2 settings for independent mono operation.
Simply recalling an old scene must not rewrite its stored settings or switch
the global mode. Send-mute behavior must also be defined explicitly so the two
sides cannot acquire conflicting states.

Saving a scene while in stereo mode needs a persistence rule before implementation.
In particular, decide whether stereo edits update the scene's AUX 1 settings
while retaining AUX 2, or whether separate stereo values preserve both original
mono sends. Also define which independent settings are restored after recalling
several scenes in stereo mode. Do not claim that both original mono settings
survive a save until that rule and storage mechanism are implemented.

Saving stereo/mono mode inside each scene is an alternative, but is not the
recommended default: recalling a mono scene could send two unrelated mixes to
an external effect connected as a stereo pair.

- [ ] Finalize global-mode persistence across reboot and its device/configurator control.
- [ ] Finalize scene-save behavior, send mute and restoration of independent settings.
- [ ] Integrate paired gain updates with physical and MIDI scene recall, startup
      restoration and editor changes.
- [ ] Test old scenes, stereo scene saves, switching back to mono and reboot.
      Confirm recall preserves the global mode and unsaved recalls leave stored
      scene data unchanged.
- [ ] Verify transitions with different channel levels, pan, send amounts,
      pre/post choices and mute states, including left/right ramp consistency.

## Keeping this tracker current

Record agreed decisions here and check off work only with a linked implementation
or validation result. Keep historical experiments in `research/` and device
evidence in the existing progress and experiment records. An emulator result
does not complete a hardware acceptance item.
