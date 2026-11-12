# Coming from Ibex and PCIbex

`potato import` reads an Ibex or PCIbex (PennController) experiment and
builds a Potato project with the same items, Latin-square lists and main
trial type. Use it to run a self-paced reading, maze, acceptability or
two-key task with Potato's recruitment, surveys and export, or alongside an
annotation task.

## Import

Point it at the experiment folder (the one with `data_includes/` and
`chunk_includes/`, as in a PCIbex Farm or Ibex project download):

```bash
potato import -i my_experiment/ -o my-study/
python potato/flask_server.py start my-study/config.yaml -p 8000
```

## What is translated

PCIbex studies are JavaScript, so the importer reads the parts with a fixed
shape:

| Ibex / PCIbex | Potato |
|---|---|
| `Template("table.csv", row => newTrial(...))` | One item per CSV row, every column kept |
| `newController("DashedSentence", {s: row.X})`, classic `DashedSentence` | [Self-paced reading](../workflow/self_paced_reading.md) (moving window) |
| `newController("Maze", {s: row.X, a: row.Y})` | The maze task, with the distractors from `row.Y` |
| `newScale(N)` with `.before` / `.after` texts, classic `AcceptabilityJudgment` | An N-point `likert` scale with those end labels |
| `newKey("F", "J")` with `newText(row.X)` | A [timed trial](../workflow/timed_trials.md) with those keys (rename the labels to what they mean) |
| Classic `"Question"` after a sentence | A comprehension question (F and J for the first two answers) |
| `newText(row.Q)` and `newKey(...)` after a `DashedSentence` | A comprehension question from column `Q`, answered with the template's first two keys as Yes and No (rename the answers if they mean something else) |
| A `Group` or `List` column; classic `["condition", N]` labels | A between-subjects factor `list`, one data file per list, and `batch_assignment.group_by_condition: list` |

Classic Ibex items labelled `["condition", N]` share group N; list k gets
the condition at position (k + N) mod (number of conditions), the usual
Latin-square rotation. Items outside the square go in every list, under a
different id in each.

## Not translated

Practice items and templates, `Message`, `Form` and `Html` screens,
`newTimer`, `Sequence` and `shuffleSequence` ordering, `Header` and
`Footer`, `newFunction` and other custom JavaScript, images, audio and
video elements, recording, and any template whose table is not in
`chunk_includes/`. The output and `IMPORT_REPORT.md` list them. A trial
that is none of the types above is refused with a message, and so is an
import that would have no items, or a PCIbex template whose stimulus column
is missing from its table. These are listed as warnings in the output and
in `IMPORT_REPORT.md`:

- a column the template reads that the table lacks;
- empty stimulus cells;
- two classic items with the same label in one group. Both are kept, since
  Ibex rotates a group by position.

Put consent and instructions on [survey pages](../workflow/surveyflow.md).
For stimulus timing that Potato's timed trials do not cover, run the task in
a [jsPsych phase](../workflow/jspsych_phase.md).

## Related

- [Self-paced reading and the maze task](../workflow/self_paced_reading.md)
- [Experiment flow](../workflow/experiment_flow.md)
- [Coming from jsPsych](coming-from-jspsych.md)
