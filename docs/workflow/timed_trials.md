# Timed Trials

`trial_timing` runs each annotation item as a timed trial: an optional
fixation cross, the stimulus for a set time, a response window with a
deadline, and keys mapped to labels. The reaction time is measured in the
browser from the frame the stimulus appeared.

Use it for speeded judgments on Potato's own items: lexical decision,
grammaticality or plausibility judgments under time pressure, rapid image
categorization. For frame-critical presentation, auditory onsets, or
paradigms that need code on each trial, use a
[jsPsych phase](jspsych_phase.md).

## Configuration

```yaml
annotation_schemes:
  - annotation_type: radio
    name: decision
    description: Is this a word?
    labels: [word, nonword]
    label_requirement:
      required: true

trial_timing:
  enabled: true
  fixation_ms: 500
  stimulus_duration_ms: 200       # omit: the stimulus stays up until the response
  trial_duration_ms: 2000         # omit: no deadline
  iti_ms: 500
  response:
    schema: decision
    keys: {f: word, j: nonword}
```

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Turn timed trials on |
| `fixation_ms` | `0` | Fixation cross before each stimulus. `0` for none |
| `fixation_symbol` | `+` | What the fixation shows |
| `stimulus_duration_ms` | none | Hide the stimulus after this many ms |
| `trial_duration_ms` | none | Deadline from onset. A trial that runs out is a timeout and the next item starts |
| `iti_ms` | `0` | Minimum blank time between a response and the next fixation. Loading the next page counts toward it |
| `response.schema` | required | A `radio` or `likert` scheme that records the answer |
| `response.keys` | | Key to label. One character, or `space`. Quote `y` and `n` |
| `response.allow_mouse` | `false` | Also accept a click on an option |
| `show_response_options` | `allow_mouse` | Show the scheme's options during the trial |
| `item_overrides` | none | Per-item timing from item fields, e.g. `{stimulus_duration_ms: soa_ms}`. `0` in the field means no limit |
| `disable_back_navigation` | `true` | Hide Previous, so no stimulus is shown twice |

## Trial sequence

1. A blank interval, until `iti_ms` has passed since the last response.
2. The fixation cross, for `fixation_ms`.
3. The item. A line under it lists the keys, e.g. `F = word    J = nonword`.
4. A mapped key selects that label, saves, and moves to the next item. Other
   keys do nothing. A mapped key pressed before the stimulus is counted as an
   early press and ignored.
5. At the deadline the item is recorded as a timeout and the next item starts.

The keyboard shortcuts of the normal annotation page (arrow keys, number
keys) are off while a trial runs.

## Trial record

Each item gets a trial record, stored in `user_state.json` next to the labels
and written to `trials.csv` (or `.tsv`) by the CSV/TSV export:

| Field | Meaning |
|---|---|
| `outcome` | `response` or `timeout` |
| `key`, `label` | The key pressed and the label it selected |
| `rt_ms` | Reaction time from stimulus onset |
| `intended_*` | The configured fixation, stimulus, deadline and ITI for this item |
| `fixation_ms_actual`, `stimulus_ms_actual`, `iti_actual_ms` | What the browser delivered |
| `frame_ms` | The display's frame interval, measured during the trial |
| `timer_resolution_ms` | The smallest step of the browser's clock |
| `early_keys` | Mapped keys pressed before the stimulus |
| `reloads` | Times the page was reloaded during this trial |
| `tab_hidden` | The participant switched away during the trial |
| `server_elapsed_ms` | Time between the server sending the page and receiving the record |
| `flags` | The server's checks (below) |

A timed-out item has no label, so `trials.csv` is the complete record of a
timed task; the main annotation export lists answered items only.

## Server checks

The browser reports the record; the server compares it with its own clock,
using the item's own timing when `item_overrides` set it, and with the
configuration:

- `rt_exceeds_server_elapsed`: the reaction time is longer than the item was
  out.
- `timeout_too_early`: a timeout arrived before the deadline could have
  passed.
- `timeout_without_deadline`: a timeout on an item that has no deadline.
- `not_served`: the server has no record of handing the item over, for
  example after a restart, so it cannot check the timing.
- `key_not_mapped`, `label_mismatch`, `label_not_in_scheme`: the key is not in
  `response.keys`, does not map to the label reported, or the label is not one
  of the scheme's.
- `label_not_saved`: the record's label is not the answer the same save
  stored.
- `tab_hidden`: the tab was hidden during the trial.

A timeout lets the participant move on without an answer only when it has
none of `timeout_too_early`, `timeout_without_deadline` and `not_served`.
Otherwise the item stays unanswered and required.

## Timeouts, quotas and attention checks

A timed-out item is finished for the participant: it counts toward their
progress, and they are not shown it again. It is not an annotation of the
item, so it does not count toward `max_annotations_per_item`, and other
participants can still be assigned the item. The progress badge shows a
timed-out item as not labeled.

A trial that runs out on an attention check is not graded as a failure; it
is in `trials.csv` as a timeout. A speeded task produces timeouts from
attentive participants, and blocking them for it would remove people for
the deadline rather than for inattention.

## Precision

The stimulus is revealed inside a `requestAnimationFrame` callback, and onset
is the timestamp of the next frame, the first one drawn with the stimulus.
The reaction time is the key event's timestamp minus that onset. Both use
the browser's high-resolution clock.

- Onset is known to the frame: about 17 ms at 60 Hz, 8 ms at 120 Hz.
- Keyboards and displays add latency the browser cannot see, commonly 5–30 ms
  and different on every machine.
- Browsers that coarsen timers for privacy (Firefox with
  `privacy.resistFingerprinting`, Tor Browser) round to tens of
  milliseconds. `timer_resolution_ms` shows this per participant.
- Each item is a page load, so fullscreen cannot be held across items.

Compare reaction times within participants, or model them with a participant
term. For millisecond-level work, or audio, use a jsPsych phase.

## Limits

- Phones and tablets are sent to the touch interface (`pocket`), which does
  not run timed trials. The server logs a warning when both are on.
- The response scheme must be `radio` or `likert`, and it must be the only
  question on the annotation page (display-only schemes are allowed). A
  second question cannot be answered while a trial owns the keyboard, so the
  validator reports it as an error; ask follow-up questions on a poststudy page.
- The MySQL backend does not store trial records.

## Example

```bash
python potato/flask_server.py start examples/advanced/timed-trials-lexical-decision/config.yaml -p 8000
```

## Related

- [jsPsych phase](jspsych_phase.md)
- [Experiment flow](experiment_flow.md)
- [Behavioral tracking](../advanced/behavioral_tracking.md)
- [Coming from jsPsych](../guides/coming-from-jspsych.md)
