# Keystroke Logging (Typing Dynamics)

Records **how** annotators produce free-text responses — the pauses, bursts,
revisions and pastes — without ever recording **what** they type.

This lets you distinguish a response that was **composed** (typed, with the
hesitations and revisions of real thought) from one that was **transcribed**
(retyped from another window) or **pasted** (dropped in from an LLM). The
finished text rarely reveals which; the writing process usually does.

For the detection rules built on top of this data, see
[Writing-Process Detection](writing_process_detection.md). Before enabling it on
human participants, read [Keystroke Logging Ethics](keystroke_logging_ethics.md).

---

## Quick start

```yaml
keystroke_logging:
  enabled: true
```

Those two lines are the whole minimum configuration. Every free-text field in
the project starts producing a content-blind event stream, a ~40-field summary,
and a set of detection flags.

A runnable example lives at `examples/advanced/keystroke-logging/`:

```bash
python potato/flask_server.py start examples/advanced/keystroke-logging/config.yaml -p 8000
```

!!! warning "Off by default"
    `enabled` defaults to `false`. Upgrading Potato never silently starts
    recording your annotators.

---

## What gets captured

Each event records a timestamp, an input type, a key **class**, the caret
position, and the change in field length:

```
{t_ms: 1240, input_type: "insertText",            key_class: "letter", pos: 41, delta: +1}
{t_ms: 1310, input_type: "insertText",            key_class: "letter", pos: 42, delta: +1}
{t_ms: 3980, input_type: "deleteContentBackward", key_class: "bksp",   pos: 42, delta: -1}
{t_ms: 9120, input_type: "insertFromPaste",       key_class: "unknown",pos: 43, delta: +287,
    meta: {paste_source: "external", paste_hash: "sekqf3"}}
```

### What is deliberately *not* captured

| Not captured | Why |
|---|---|
| The characters typed | The stream reconstructs the *process*, not the text. |
| Pasted text | Only a length, a source label, and a salted hash. |
| Intermediate drafts | Not reconstructable from length deltas alone. |
| Anything in a password field | `getFieldIdentity` refuses `type="password"` outright. |
| Clipboard contents generally | Read at paste time to classify, then discarded. |

### Key classes

The key itself is never stored — only which family it belongs to:

`letter`, `digit`, `punct`, `space`, `enter`, `bksp`, `del`, `nav`, `mod`,
`func`, `unknown`

### Input types

Potato's primary signal is `InputEvent.inputType`, not `keydown`. This is the
central technical choice: paste, drag-and-drop, IME composition, dictation,
autofill and undo **all mutate a field without firing `keydown` at all**, so a
keydown-only logger is blind to precisely the cases this feature exists to
detect.

`insertText`, `insertReplacementText`, `insertFromPaste`, `insertFromDrop`,
`insertCompositionText`, `insertLineBreak`, `insertParagraph`,
`deleteContentBackward`, `deleteContentForward`, `deleteWordBackward`,
`deleteWordForward`, `deleteByCut`, `deleteByDrag`, `historyUndo`,
`historyRedo`, plus the synthetic `focus`, `blur` and `keydown`.

`keydown`/`keyup` are still listened to, but only to count *physical* keystrokes
and measure dwell. The gap between "characters that appeared" and "keys actually
pressed" is the single strongest signal collected — see `silent_insert_ratio`.

---

## Which fields are instrumented

By default, **every free-text field**: the `text` schema, free-response boxes
inside `radio` and `multiselect`, and the rationale/notes textareas in
`text_edit`, `pairwise`, `trajectory_eval` and similar schemas.

Fields are identified by the `schema` and `label_name` attributes that Potato
already stamps on every annotation input, falling back to splitting the `name`
attribute on `:::`.

Restrict the scope with either list:

```yaml
keystroke_logging:
  enabled: true
  include_schemas: [rationale]      # allowlist; empty = all fields
  exclude_schemas: [scratch_notes]  # denylist
```

Or opt a single element out in custom HTML:

```html
<textarea data-keystroke-logging="off" ...></textarea>
```

---

## Configuration reference

```yaml
keystroke_logging:
  enabled: false                # master switch
  fidelity: events              # off | summary | events
  include_schemas: []           # empty = every free-text field
  exclude_schemas: []
  store_events: true            # persist raw streams (needs fidelity: events)
  classify_paste_source: true   # label pastes self/instance_text/ai_suggestion/external
  idle_session_ms: 30000        # close a session after this much inactivity
  flush_interval_ms: 5000       # how often the browser posts completed sessions
  pause_thresholds_ms: [500, 1000, 2000, 5000, 10000]
  disclose_to_annotators: true  # show a recording notice on every page
  disclosure_text: null         # null = built-in notice; set a string to override
  detection:
    enabled: true
    calibrate: false            # use project-fitted thresholds
    on_external_insert: flag    # allow | warn | block | flag
    thresholds: {}              # per-rule overrides
```

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Master switch. Nothing is captured when false. |
| `fidelity` | `events` | `off` disables; `summary` computes features but stores no stream; `events` stores both. |
| `include_schemas` | `[]` | Allowlist of schema names. Empty means all. |
| `exclude_schemas` | `[]` | Denylist, applied after the allowlist. |
| `store_events` | `true` | Persist raw streams. Ignored unless `fidelity: events`. |
| `classify_paste_source` | `true` | Compare pastes against the passage, AI suggestions, and the field's own contents. |
| `idle_session_ms` | `30000` | Inactivity before a session is closed and flushed. |
| `flush_interval_ms` | `5000` | Browser flush cadence. |
| `pause_thresholds_ms` | `[500,1000,2000,5000,10000]` | Pause counts are reported at each. |
| `disclose_to_annotators` | `true` | Render the recording notice described below. Turning it off logs a warning. |
| `disclosure_text` | `null` | Replace the built-in notice wording. `null` uses the default. |

### The recording notice

When `disclose_to_annotators` is on, Potato renders a quiet bar directly under
the navigation header, on **every** page that can contain a free-text field —
annotation pages and phase pages (consent, instructions, training, surveys)
alike:

> ✎ This task records the timing and rhythm of your typing in text boxes (when
> you pause, revise, or paste) — not the individual keys you press.

It is rendered server-side, so it still appears if `keystroke_tracker.js` fails
to load, and it cannot be removed by disabling JavaScript. It is deliberately
**not** dismissible: it is a standing statement about what the task records
rather than a one-time alert. It is styled as a status line rather than a
warning, because an alarming banner would change how people write — which is
the behaviour being measured.

Override the wording with `disclosure_text` when your ethics approval specifies
particular language:

```yaml
keystroke_logging:
  enabled: true
  disclosure_text: >-
    Study ID 2026-0142 records typing timing (pauses, revisions, pasting) in
    all text boxes. It does not record which keys you press.
```

This bar is a **reminder, not consent**. It appears alongside the task, at a
point where the annotator has already agreed to participate. Informed consent
belongs in your consent phase, before any typing happens — see
[Ethics, Consent and IRB](keystroke_logging_ethics.md) for language you can
adapt.

Detection keys are documented in
[Writing-Process Detection](writing_process_detection.md).

### Choosing a fidelity

| Fidelity | Stream stored | Recompute new metrics later? | Use when |
|---|---|---|---|
| `off` | — | — | Feature disabled for this project. |
| `summary` | No | **No** | You are certain about which features you need, or your ethics approval does not cover retaining streams. |
| `events` | Yes | Yes | Default. Roughly 2 bytes per keystroke. |

`events` is recommended: a 500-word response costs about 5 KB, and it means a
metric you think of after data collection can still be computed.

---

## Summary features

One summary per (user, instance, field), grouped by what each measures. Feature
families follow Crossley et al. (2024) — see
[Writing-Process Detection](writing_process_detection.md#research-grounding).

### Volume / product-to-process

| Field | Meaning |
|---|---|
| `keystrokes` | Physical keydowns that produced text |
| `final_chars` | Field length at session end |
| `chars_typed` / `chars_inserted` | Characters inserted by typing / by any means |
| `chars_deleted` | Characters removed |
| `chars_per_keystroke` | Above ~1.1 implies text arriving without keystrokes |
| `active_ms` / `wall_ms` | Time on the field, excluding / including time away |

### Rhythm (process variance)

| Field | Meaning |
|---|---|
| `iki_median_ms`, `iki_mean_ms` | Inter-key interval central tendency |
| `iki_p10/p25/p75/p90_ms` | IKI distribution shape |
| `iki_log_sd`, `iki_log_cv` | Dispersion on a log scale. **Low = metronomic = transcription.** |

Log scale because IKI distributions are heavily right-skewed. Intervals above
30 s are excluded from these statistics so one coffee break cannot dominate them.

### Pausing

| Field | Meaning |
|---|---|
| `pause_counts` | Counts at each configured threshold |
| `pause_total_ms` | Total time in pauses |
| `pre_word_pause_mean_ms` | Mean pause before starting a word |
| `pre_sentence_pause_mean_ms` | Mean pause after punctuation |
| `intraword_iki_median_ms` | Median interval *within* words (keyboarding skill) |

### Bursting

| Field | Meaning |
|---|---|
| `bursts`, `burst_mean_chars`, `burst_max_chars` | Run-of-production statistics |
| `p_bursts` | Bursts terminated by a pause |
| `r_bursts` | Bursts terminated by a revision |

### Revision

| Field | Meaning |
|---|---|
| `backspaces`, `deletes`, `undo_events` | Deletion behaviour |
| `non_terminal_edits` | Edits made *behind* the end of the text — going back to revise |
| `caret_jumps` | Non-adjacent caret movements |
| `revision_ratio` | `chars_deleted / chars_typed` |

### External insertion — the AI tell

| Field | Meaning |
|---|---|
| `paste_events`, `pasted_chars`, `largest_paste_chars` | Paste volume |
| `pasted_fraction` | Share of the final text that was pasted |
| `drop_events` | Drag-and-drop insertions |
| `silent_insert_chars` / `silent_insert_ratio` | Characters with **no corresponding keystroke** |
| `external_insert_chars` / `external_insert_ratio` | As above, **excluding** self-quotes and passage quotes |
| `paste_sources`, `paste_chars_by_source` | Counts and characters per source label |

`external_insert_ratio` is the one to use for detection.
`silent_insert_ratio` counts *all* silent insertion, including the legitimate
kind.

### Attention

| Field | Meaning |
|---|---|
| `blur_events`, `blur_total_ms` | Time away from the page |
| `max_blur_before_insert_ms` | Longest absence **immediately preceding a large insertion** |
| `first_keystroke_latency_ms` | Thinking time before the first character |

### Integrity

| Field | Meaning |
|---|---|
| `untrusted_events` | `InputEvent.isTrusted === false` — scripted or automated input |
| `composition_events` | IME composition |
| `virtual_keyboard` | Mobile/soft keyboard detected |

---

## Where the data is stored

Two destinations, for two different reasons.

### Raw streams → SQLite

`<task_dir>/project.sqlite`, table `typing_sessions`, one row per session. Uses
the same universal persistence layer as memos and the codebook.

Queryable summary columns are denormalized alongside a full JSON summary and a
zlib-packed event blob:

```bash
sqlite3 <task_dir>/project.sqlite "
  SELECT user_id, schema_name, keystrokes, final_chars,
         pasted_fraction, silent_insert_ratio, iki_log_cv,
         json_extract(flags,'\$.level') AS level
  FROM typing_sessions;"
```

The stream is stored as one packed blob per session rather than one row per
keystroke: it is only ever read back wholesale, and at ~2 bytes per event a
row-per-keystroke schema would put tens of millions of rows in a project file
for no query benefit.

#### Phase pages

Free-text answers in the training phase and in prestudy/poststudy surveys are
captured too. Those pages have no instance id, so their sessions are bucketed
under the `__phase_page__` sentinel — the same one the rest of the behavioral
system uses — and identified by their `phase` and `page` columns instead:

```sql
SELECT phase, page, count(*) FROM typing_sessions GROUP BY phase, page;
```

This is what makes the
[calibration example](https://github.com/davidjurgens/potato/tree/master/examples/advanced/keystroke-calibration)
work: a copy-the-passage task in the training phase yields transcription
exemplars that can be told apart from ordinary composed answers by `phase` alone.

### Summary → `user_state.json`

The compact sketch is mirrored into
`<output_annotation_dir>/<user>/user_state.json` under
`instance_id_to_behavioral_data.<instance>.typing_summaries`, keyed
`"{schema}:::{label}"`, so it travels with the annotation into the admin
dashboard and the exports.

Raw streams deliberately do **not** go there: that file is fully re-serialized
and atomically rewritten on every annotation save, and a long response is
thousands of events.

---

## Exporting

### Summary features alongside annotations

```yaml
export_include_typing_dynamics: true
```

Produces `typing_dynamics.csv` (or `.tsv`) next to `annotations.csv`, one row
per (user, instance, field), with the summary features and the detector verdict.

### Raw streams

```bash
python -m potato.export.cli <config.yaml> --format keystrokes
```

Writes `keystroke_sessions.parquet` and `keystroke_events.parquet`, falling back
to JSONL when `pyarrow` is not installed.

```python
import pandas as pd
events = pd.read_parquet("keystroke_events.parquet")

# Inter-key intervals for one session
s = events[events.session_id == events.session_id.iloc[0]].sort_values("t_ms")
iki = s.t_ms.diff().dropna()
print(iki.median(), iki.std())

# Every externally-sourced paste in the project
print(events[events.paste_source == "external"])
```

---

## API endpoints

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/track_typing` | Receive completed sessions from the browser |
| `GET` | `/api/typing_summary/<instance_id>` | Summaries for one instance, current user |
| `GET` | `/admin/api/writing_process` | Per-annotator rollup (**admin key required**) |

Sessions are summarized **server-side**. The browser never sends a computed
summary, so the numbers cannot be forged by a modified client, and a metric
added later can be recomputed from the stored streams.

---

## How sessions work

A session begins when a field is focused and ends at whichever comes first:
losing focus, navigating to another instance, `idle_session_ms` of inactivity,
or page unload. Completed sessions are posted every `flush_interval_ms`, and via
`navigator.sendBeacon` on unload so an in-progress session is not lost.

Multiple sessions on the same field are **merged** before the summary is written
to the user state, so leaving a field and coming back reads as one response
rather than several suspiciously short ones. Counts and durations add;
distribution statistics are keystroke-weighted approximations — use the raw
streams if you need an exact pooled distribution.

---

## Troubleshooting

**No data is being recorded.**
Check `keystroke_logging.enabled: true` and that `fidelity` is not `off`. In the
browser console, `window.keystrokeTracker` should exist with
`isInitialized === true`. If it is `undefined`, the config never reached the
template.

**The tracker exists but no sessions appear.**
Check field identification:

```js
const el = document.querySelector('textarea');
window.keystrokeTracker.getFieldIdentity(el);   // null means it is not tracked
```

`null` means the element has no `schema`/`label_name` attributes and no
`:::`-separated `name`, or it is excluded by config.

**`silent_insertion` flags every mobile annotator.**
It should not — the rule is suppressed when `virtual_keyboard` is true. If
detection is misfiring, check that the client set that flag; see the
false-positive section in
[Writing-Process Detection](writing_process_detection.md#false-positives).

**`project.sqlite` is growing.**
Roughly 2 bytes per keystroke. Set `fidelity: summary` to keep the features and
drop the streams, or use `typing_store.delete_for_user()` to remove a
participant's data.

**Numbers look wrong for automated tests.**
Browser automation types at near-zero intervals, which genuinely trips
`implausible_speed`. That is the flag working, not a bug.

---

## Related documentation

- [Writing-Process Detection](writing_process_detection.md) — the detection rules
- [Keystroke Logging Ethics](keystroke_logging_ethics.md) — IRB, consent, participant rights
- [Behavioral Tracking](behavioral_tracking.md) — the broader interaction-tracking system
- [Quality Control](../workflow/quality_control.md) — attention checks and gold standards
- [Admin Dashboard](../administration/admin_dashboard.md) — the Writing Process panel
