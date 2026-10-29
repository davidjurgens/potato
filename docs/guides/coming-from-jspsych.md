# Coming from jsPsych

[jsPsych](https://www.jspsych.org/) is a JavaScript library for behavioral
experiments in the browser. Potato is a server for annotation and survey
studies. The two overlap: both show participants stimuli, collect responses,
randomize, branch, and send people back to Prolific or SONA with a completion
code. This page maps jsPsych concepts to Potato configuration, says where
Potato is the better fit and where jsPsych is, and shows how to run a jsPsych
task inside a Potato study when you need both.

## When to use which

Use **jsPsych** when the task is the experiment: millisecond-level stimulus
control, reaction-time paradigms (Stroop, flanker, IAT, visual search), eye
tracking, audio with precise onsets, or custom canvas drawing.

Use **Potato** when the study is mostly judgments on items: labeling,
rating, ranking, span marking, pairwise comparison, surveys, with assignment of
items to participants, quality control, inter-annotator agreement, and an
admin dashboard. Potato also runs the parts around a task: consent,
screeners, instructions, training with feedback, post-study surveys, and the
crowdsourcing hand-off.

Use **both** when a study needs a timed task and annotation or surveys: put
the jsPsych timeline in a [`type: jspsych` phase](../workflow/jspsych_phase.md)
and let Potato handle everything else. The jsPsych data is stored per
participant and exported with the rest.

## Concept map

| jsPsych | Potato | Notes |
|---|---|---|
| Timeline | `phases.order` | Consent, prestudy, instructions, training, annotation, poststudy. Several pages per phase |
| Trial | A phase page, or one annotation item | Items come from `data_files`, not from the config |
| Timeline variables | Fields in the data file | Each item is a row; `instance_display` chooses which fields to show |
| `conditional_function` on a timeline | Page `show_when` | [Experiment flow](../workflow/experiment_flow.md). Same grammar as question-level `display_logic` |
| Conditional display of one question | `display_logic` | [Conditional logic](../configuration/conditional_logic.md) |
| End the experiment early (`abortExperiment`) | Page `exit_when` | Screen-out with a message, or the platform's screen-out code |
| `loop_function` | `training.failure_action: repeat_training` | Only the training phase loops |
| `randomize_order`, `sample` | `assignment_strategy: random`; `randomize_questions` on a survey page | Item order is seeded per participant |
| Shuffled response options | `randomize_order` on a scheme | [Presentation order](../advanced/presentation_order.md). The order shown is recorded |
| `jsPsych.randomization.factorial`, condition assignment | `conditions` | Balanced, random or round-robin assignment to cells; `condition.<factor>` in rules |
| Counterbalanced block order, Latin square | `phases.counterbalance` with `method: latin_square` | Balanced (Williams) squares |
| `survey-likert`, `survey-multi-choice`, `survey-multi-select`, `survey-text` | `likert`, `radio`, `multiselect`, `text` schemes | Plus 55 [validated instruments](../advanced/survey_instruments.md) by name |
| `html-slider-response` | `slider`, `vas` | |
| `maxdiff` | `bws` (best-worst scaling) | With scoring |
| `free-sort` | `card_sort` | Closed or open sorting |
| `cloze` | `cloze` | [Cloze](../annotation-types/text/cloze.md). The answer key stays on the server |
| `same-different-*` | `pairwise` | Without timed sequential presentation |
| `*-keyboard-response` with `trial_duration` | `trial_timing` | [Timed trials](../workflow/timed_trials.md): fixation, stimulus duration, deadline, key-to-label RT |
| `instructions`, `external-html` | `type: instructions` pages, HTML files | |
| `jsPsych.data` interaction data (blur, focus) | `authenticity` paradata | Page leaves, copies, external pastes, automation signals |
| Mouse-tracking extension | `extensions: [mouse-tracking]` in a jsPsych phase | x/y trajectories per trial. On annotation items, `authenticity` keeps pointer totals only |
| `jspsych-contrib` self-paced reading, maze | `trial_timing.presentation` | [Self-paced reading and maze](../workflow/self_paced_reading.md): moving window, centred, cumulative, maze; per-region reading times |
| `audio-*-response` quality ratings, headphone checks | `listening_test` scheme, `type: headphone_check` page | [Listening tests](../annotation-types/multimedia/listening_tests.md) (MUSHRA, ACR, ABX, ...) and the [headphone check](../workflow/runtime_phases.md#headphone-check) |
| Writing process | `keystroke_logging` | Content-blind keystroke timing on free-text fields |
| Prolific URL variables, completion redirect | `login.type: url_direct` (or `prolific`) and `completion_code` | Completion and screen-out codes; `login.type: prolific` adds API monitoring |
| SONA | `crowdsourcing.sona` | Automatic credit |
| `jsPsych.data.get().csv()` | `python -m potato.export` | 71 formats, including CSV, JSONL, Parquet, Psych-DS and Frictionless Data Package. The CSV/TSV export adds `participants`, `trials` and `regions` tables |
| JATOS, Pavlovia, Cognition.run | `potato deploy`, Hugging Face Spaces | Potato is the server |
| `simulation` mode | `python -m potato.simulator` | Simulated annotators against a running server |

## What Potato does not do

- Frame-locked stimulus presentation on canvas, audio scheduled with Web
  Audio, or anything else that needs code on the trial. Use a jsPsych phase.
- Eye tracking (WebGazer) and webcam recording. Mouse trajectories need a
  jsPsych phase with the mouse-tracking extension.
- Fullscreen across items. Each Potato item is a page load, and browsers leave
  fullscreen on navigation. A jsPsych phase can hold fullscreen for its whole
  timeline.
- General loops and branches inside the item queue. Branching is per page
  (`show_when`), per question (`display_logic`) and per training attempt.

## A study with both

```yaml
conditions:
  factors:
    feedback: [none, immediate]

phases:
  order: [consent, screener, stroop, annotation, debrief]
  consent:
    type: consent
    file: surveys/consent.json
  screener:
    type: prestudy
    file: surveys/screener.json
    exit_when:
      show_when:
        - {schema: colour_vision, operator: equals, value: "Yes"}
      message: This study needs normal colour vision.
  stroop:
    type: jspsych
    timeline: tasks/stroop.js
    plugins: [instructions, html-keyboard-response]
  debrief:
    type: poststudy
    file: surveys/debrief.json
    randomize_questions: true

login:
  type: url_direct
  url_argument: PROLIFIC_PID
completion_code: "C1ABCDEF"
```

The complete version is in `examples/advanced/jspsych-stroop/`.

## Related

- [Experiment flow](../workflow/experiment_flow.md)
- [jsPsych phase](../workflow/jspsych_phase.md)
- [Timed trials](../workflow/timed_trials.md)
- [Multi-phase workflows](../workflow/surveyflow.md)
- [Crowdsourcing guide](crowdsourcing-guide.md)
