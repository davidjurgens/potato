# Experiment Flow

Five settings cover the design side of an experiment:

| Setting | What it does |
|---|---|
| `conditions` | Assigns each participant to one cell of a design |
| `show_when` on a phase page | Skips the page unless a condition holds |
| `exit_when` on a phase page | Ends the study for the participant (a screener) |
| `phases.counterbalance` | Orders a group of pages per participant, at random or by Latin square |
| `randomize_questions` on a survey page | Orders that page's questions per participant |

Everything a participant was assigned or shown is recorded, and the CSV/TSV
export writes it to `participants.csv`.

## Conditions

```yaml
conditions:
  factors:
    feedback: [none, immediate]
    font: [serif, sans]
  assignment: balanced        # balanced | random | round_robin
  balance_on: assigned        # assigned | completed
  max_per_cell: 40            # optional
```

Two factors with two levels each give four cells. A participant is assigned a
cell the first time the server sees them and keeps it.

| Key | Default | Meaning |
|---|---|---|
| `factors` | required | Factor name to a list of at least two levels |
| `assignment` | `balanced` | `balanced` picks the cell with the fewest participants (ties broken at random per participant); `random` draws a cell, seeded per participant; `round_robin` cycles through cells in arrival order |
| `balance_on` | `assigned` | `completed` counts participants who reached the end without being screened out, and those still in progress whose assignment or last activity is within `in_progress_minutes`; anyone else is a dropout and is replaced |
| `in_progress_minutes` | `60` | With `balance_on: completed`, how long an unfinished participant still counts toward their cell. Set it to about the study's expected duration; `0` counts finishers only |
| `max_per_cell` | none | A full cell is skipped. When every cell is full, the least-filled one is used and a warning is logged |
| `cells` | full factorial | An explicit list of cells, a subset of the factorial, each with an optional `weight` |

Weighted cells:

```yaml
conditions:
  factors:
    prime: [none, positive, negative]
  cells:
    - {prime: none, weight: 2}
    - {prime: positive}
    - {prime: negative}
```

Quote level names YAML would read as booleans (`"yes"`, `"no"`, `"on"`,
`"off"`). `potato validate` and the server report an unquoted one as an error.

### Testing a condition in rules

Rules address a factor as `condition.<factor>`, in page `show_when`, page
`exit_when`, and question `display_logic`. A value compared with a factor
must be one of its levels; a typo would otherwise hide the page or question
from everyone, so the validator reports it.

```yaml
- name: feedback_rating
  annotation_type: likert
  description: How useful was the feedback?
  size: 5
  display_logic:
    show_when:
      - {schema: condition.feedback, operator: equals, value: immediate}
```

A question hidden by its condition is not required, on the page or on the
server.

To give each cell its own items, name batch groups after a factor's levels:

```yaml
conditions:
  factors:
    list: [list_a, list_b]
assignment_strategy: batch
batch_assignment:
  auto_assign_annotators: true
  group_by_condition: list
  groups:
    - {name: list_a, data_file: data/list_a.jsonl}
    - {name: list_b, data_file: data/list_b.jsonl}
```

Item IDs must be unique across all data files, including the files of
different groups. The server will not start when two lists share an ID, so a
stimulus that appears in both lists needs a distinct ID in each (for example
`h1_a` and `h1_b`).

A [`type: jspsych`](jspsych_phase.md) timeline receives the conditions as
`potato.conditions`, and its trial data gets a `condition_<factor>` column.

## Wording per condition

`{condition.<factor>}` anywhere on a page, in item text, question wording or
option labels, is replaced by the participant's level of that factor. This
is how an endorsement experiment or a factorial vignette varies its text:

```yaml
conditions:
  factors:
    endorser: ["The city council", "A neighbourhood association"]
```

```json
{"id": "p1", "text": "{condition.endorser} proposes turning the car park into a park."}
```

The replacement is HTML-escaped. A placeholder for a factor the participant
has no level of stays on the page as written, so a typo is visible.
`/api/current_instance`, `/api/instance_data` and `/api/spans/<id>` return the
filled text, and span offsets count the characters of the filled text, as the
participant saw it. Exports write the item text as it is in the data file,
with the placeholder. A span after a placeholder therefore does not line up
with the exported text: shift it by the difference in length between the
placeholder and the participant's level (their conditions are in the export),
or do not put placeholders in text that is annotated with spans.
[List experiments](../annotation-types/measurement/sensitive_questions.md)
use the same mechanism to show a statement to one group only.

## Skipping pages: `show_when`

```yaml
phases:
  order: [screener, smoking_followup, general, annotation]
  screener:
    type: prestudy
    file: surveys/screener.json
  smoking_followup:
    type: prestudy
    file: surveys/smoking.json
    show_when:
      - {schema: smoker, operator: equals, value: "Yes"}
  general:
    type: prestudy
    file: surveys/general.json
```

The grammar is the one question-level
[display_logic](../configuration/conditional_logic.md) uses: a list of
conditions with `schema`, `operator` and `value`, combined with `logic: all`
(default) or `logic: any`, and the same 19 operators and nested `all` / `any` / `not` groups. A rule can test any
question asked on an earlier page, in any phase, and any `condition.<factor>`.

The rule is checked when the participant leaves the page before it. A hidden
page is passed over in both directions: Next skips it, and Previous does not
land on it. Each skip is recorded.

The server will not start with a rule that names a question no page asks, or
one asked on the same page or later (it could only ever be unanswered). The
annotation phase itself cannot be skipped.

## Ending the study: `exit_when`

```yaml
screener:
  type: prestudy
  file: surveys/screener.json
  exit_when:
    show_when:
      - {schema: age, operator: lt, value: 18}
    message: This study is for adults only. Thank you for your time.
```

Checked when the participant submits the page. When it holds, the
participant goes to the end of the study:

- Without a crowdsourcing provider they see `message`.
- With one (Prolific, SONA, Connect and so on) they get the platform's
  screen-out outcome, never the completion code.

`exit_when` can test questions on its own page. It is supported on consent,
prestudy, instructions and poststudy pages.

A screened-out participant stays at the end of the study: Previous does not
take them back, even with `allow_phase_back_navigation`, and the server
stores nothing more they send. Answers they gave before the screen-out remain
in `user_state.json`; the screen-out is in `participants.csv`, not in
`annotations.csv`.

## Counterbalanced page order

```yaml
phases:
  order: [intro, block_a, block_b, block_c, annotation]
  # ...block definitions...
  counterbalance:
    - pages: [block_a, block_b, block_c]
      method: latin_square        # or random
```

The pages keep the slots they hold in `order`; each participant gets their own
arrangement of them.

- `random`: a permutation seeded on the participant, so it is the same after a
  reload or a restart.
- `latin_square`: rows of a balanced (Williams) Latin square, taken in
  arrival order. With `conditions` configured, the order of arrival counts
  within each cell, so every condition works through the whole square and
  page order is balanced inside each condition rather than confounded with
  it. For an odd number of pages the square has twice as many rows. The
  counters are rebuilt from saved states when the server restarts.

All pages in a group must have the same phase type. Pages of different types
are never next to each other in a study, so they cannot trade places.

## Question order on a survey page

```yaml
big_five:
  type: poststudy
  instrument: tipi
  randomize_questions:
    pin_last: [comments]       # or: randomize_questions: true
```

Each participant sees the page's questions in their own order, seeded on the
participant and the page and recorded the first time the page is shown.
`pin_first` and `pin_last` keep named questions at the ends. Pages laid out
with `layout.groups` are left as they are.

Option order within a question is a separate setting,
[`randomize_order`](../advanced/presentation_order.md).

## The flow record

`user_state.json` holds a `flow_record` for each participant:

| Key | Content |
|---|---|
| `conditions`, `condition_cell`, `condition_ordinal` | The assigned cell and study-wide arrival number |
| `cell_ordinal` | Arrival number within the cell; picks the Latin-square row when conditions are configured |
| `latin_ordinal` | Arrival number for Latin-square rows when no conditions are configured |
| `page_orders` | Each counterbalanced group's order |
| `question_orders` | Each randomized page's question order |
| `skipped_pages` | Pages passed over by `show_when` |
| `screened_out` | The page and time of a screen-out |
| `runtimes` | Kind, status, attempts, page loads, trial count and run id of each [runtime page](runtime_phases.md) (jsPsych, headphone check, external task) |
| `runtime_answers` | What runtime pages derived from their runs, such as a headphone check's `<page>_passed` |

The CSV and TSV exports write one row per participant to
`participants.csv` (or `.tsv`). With a `feedback` factor its header is:

```text
user_id,condition_feedback,condition_ordinal,cell_ordinal,latin_ordinal,final_phase,screened_out,screened_out_page,skipped_pages,page_orders,question_orders,runtime_runs,runtime_answers
```

`skipped_pages` is `|`-separated; the last four columns are JSON.

The MySQL backend does not store the flow record; a server using it logs a
warning when these features are configured.

## Example

`examples/advanced/jspsych-stroop/` uses `conditions`, `exit_when`, a jsPsych
phase and `randomize_questions`:

```bash
python potato/flask_server.py start examples/advanced/jspsych-stroop/config.yaml -p 8000
```

## Related

- [Multi-phase workflows](surveyflow.md)
- [Conditional logic](../configuration/conditional_logic.md)
- [jsPsych phase](jspsych_phase.md)
- [Timed trials](timed_trials.md)
- [Presentation order](../advanced/presentation_order.md)
- [Coming from jsPsych](../guides/coming-from-jspsych.md)
