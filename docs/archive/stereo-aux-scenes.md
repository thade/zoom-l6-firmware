# Stereo AUX scene behaviour proposal (archived)

The scene proposal written before the stereo AUX send was built, moved from
`docs/future-work.md` for release 0.1.0. As built (experiments 30-34): the
mode is global and not stored in scenes, stereo uses each channel's AUX 1
send amount and send point, and AUX 2 settings are kept for mono. Saving a
scene in stereo stores the stock settings unchanged.

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

