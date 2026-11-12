# Self-Paced Reading and the Maze Task

`trial_timing.presentation` shows each item's text one region at a time and
records how long the participant spends on each. It covers the reading-time
methods of psycholinguistics:

| `mode` | Method | What the participant sees |
|---|---|---|
| `moving_window` | Self-paced reading (Just, Carpenter & Woolley 1982) | The sentence as dashes; each key press reveals the next region and masks the one before |
| `cumulative` | Cumulative self-paced reading | As above, but earlier regions stay visible |
| `centered` | Centred self-paced reading, RSVP-style | One region at a time in the centre of the screen |
| `maze` | Maze task (Forster, Guerrera & Elliot 2009; A-maze, Boyce, Futrell & Levy 2020) | Two words side by side; the participant picks the one that continues the sentence |

It builds on [timed trials](timed_trials.md): the same fixation, inter-trial
interval, frame-aligned onsets, server checks and trial record. Each region
appears on a frame boundary, and its reading time is the next key press minus
that frame.

## Self-paced reading

```yaml
item_properties:
  id_key: id
  text_key: sentence

trial_timing:
  enabled: true
  fixation_ms: 400
  iti_ms: 500
  presentation:
    mode: moving_window
    field: sentence
    region_separator: "|"
    advance_key: space
    question_field: question
  response:
    schema: comprehension
    keys: {f: "Yes", j: "No"}

annotation_schemes:
  - annotation_type: radio
    name: comprehension
    description: Answer the question
    labels: ["Yes", "No"]
    label_requirement:
      required: true
```

```json
{"id": "gp1", "condition": "ambiguous",
 "sentence": "The horse | raced | past | the barn | fell | to the ground.",
 "question": "Did the horse fall?"}
```

Regions are split on `region_separator`, or on whitespace (one word per
region) when it is not set. The first key press shows the first region; the
press after the last region ends the sentence.

With `question_field`, a sentence whose field is non-empty is followed by
its comprehension question, answered with the `response` keys like any timed
trial. A sentence with no question ends after its last region with the
outcome `completed`, and the participant moves on without answering.
Without `question_field`, every sentence asks the `response` scheme, which
suits an acceptability or plausibility judgment after each sentence.

With no `response` block at all, the page only records reading times; every
scheme on the page must then be `pure_display`.

## Maze

```yaml
trial_timing:
  enabled: true
  fixation_ms: 300
  presentation:
    mode: maze
    field: sentence
    distractor_field: distractors
    maze_keys: {left: e, right: i}
    on_error: stop

annotation_schemes:
  - annotation_type: pure_display
    name: instructions
    description: Choose the word that continues the sentence.
```

```json
{"id": "m1", "sentence": "The horse raced past the barn fell to the ground.",
 "distractors": "x-x-x clock holly toward soft hint knew duty hope fuel."}
```

`distractor_field` lists one distractor per region, split the same way as
the sentence. If it has one fewer, `x-x-x` is used for the first word, as in
A-maze. The correct word's side is random on every pair. `on_error: stop`
ends the sentence at the first wrong choice; `redo` flashes the pair, waits
for the right word, and records how many wrong presses came first.

A-maze distractors are usually generated with a language model to be
ungrammatical continuations matched for length and frequency. Potato takes
them from the data; generate them with the A-maze tools before importing.

## Options

| Key | Default | Meaning |
|---|---|---|
| `mode` | `moving_window` | `moving_window`, `cumulative`, `centered` or `maze` |
| `field` | `item_properties.text_key` | Item field with the text |
| `region_separator` | none | Split regions on this (1–3 characters) instead of whitespace |
| `advance_key` | `space` | Key that shows the next region (not `maze`) |
| `question_field` | none | Item field with a per-item comprehension question |
| `distractor_field` | required for `maze` | Item field with one distractor per region |
| `maze_keys` | `{left: e, right: i}` | Keys for the left and right word |
| `on_error` | `stop` | `stop` or `redo` (`maze`) |
| `mask_char` | `-` | Character the moving window masks letters with |

The moving-window and cumulative displays use a monospace font, so the masks
keep each word's length and the line does not move as words are revealed.
The advance and maze keys may not also be `response` keys.

## Data

The trial record in `user_state.json` carries a `regions` list, one entry
per region shown:

| Field | Meaning |
|---|---|
| `index` | Region position, from 0 |
| `text` | The region's text |
| `rt_ms` | Time from the region's onset frame to the key press |
| `correct`, `side`, `errors` | Maze only: whether the right word was chosen, which side was pressed, and wrong presses before it (`on_error: redo`) |

The CSV and TSV exports write the regions to `regions.csv` (or
`regions.tsv`), one row per region with the participant, item and condition
columns, the trial's outcome and its onset time. The `trials` file has one
row per trial and no region columns.

The server checks each record and adds flags:

| Flag | Meaning |
|---|---|
| `reading_exceeds_server_elapsed` | The total reading time is longer than the server saw the item for |
| `bad_region_rt` | A region has a negative `rt_ms`; the region is kept as sent |
| `completed_without_presentation` | The record says the trial ended after reading, but the item had no regions to read (no `presentation` block, or an empty text field); it does not count as finished |
| `completed_with_question` | The record says the trial ended after reading, but the item has a question to answer; it does not count as finished |
| `regions_incomplete` | Fewer (or more) regions than the sentence has; it does not count as finished |
| `maze_error` | A maze trial ended at a wrong choice (`on_error: stop`); the last region has `correct: false` |
| `reloaded_mid_trial` | The page was reloaded during the sentence, which starts it again; the regions are from the second reading |

## Timing keys with a reading task

`trial_duration_ms` and `stimulus_duration_ms` apply to the question that
follows the reading, not to the reading itself: the deadline starts when the
question appears, and `stimulus_duration_ms` hides the question text. An item
with no question has no deadline. `potato validate` warns when either is set
with `presentation`.

## Examples

```bash
python potato/flask_server.py start examples/advanced/self-paced-reading/config.yaml -p 8000
python potato/flask_server.py start examples/advanced/maze-task/config.yaml -p 8000
```

Garden-path sentences with and without the disambiguating relative clause.
For a full design, add `conditions` with a Latin square so each participant
sees one version of each item ([Experiment flow](experiment_flow.md)).

## Related

- [Timed trials](timed_trials.md)
- [Experiment flow](experiment_flow.md)
- [Coming from jsPsych](../guides/coming-from-jspsych.md)
