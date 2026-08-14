# Annotation Telemetry

How a bounding box, polygon or mask was *produced* — the drawing-process
counterpart of [keystroke logging](keystroke_logging.md).

The headline signal is **AI-accept latency**. Everything else on this page is
supporting context for it.

## The problem it addresses

Pre-labelling makes annotators faster. It also makes rubber-stamping
frictionless: a suggestion appears, the annotator clicks accept, and the
resulting dataset is a record of a model agreeing with itself. Nothing in the
annotation itself distinguishes that from careful review — the geometry is
identical, agreement statistics are *higher*, and every quality measure Potato
has looks better, not worse.

The only place the difference shows up is in the timing.

> A human cannot inspect a mask boundary and decide in 300ms. Once, maybe —
> the object was obvious. As a **median across many items**, it is not fast
> expertise. It is not looking.

## What is recorded

An event carries a timestamp, an action, a geometry kind, and one integer.

| Action | Meaning | The integer |
|---|---|---|
| `shape_add` | a shape was committed | vertices (4 for a box, `len(points)` for a polygon, 0 for a mask) |
| `shape_edit` | an existing shape was moved or reshaped | — |
| `shape_remove` | a shape was deleted | — |
| `stroke` | one brush or eraser stroke finished | stroke length in **image** pixels |
| `fill` | flood fill applied | pixels filled |
| `zoom` | zoom level changed | level × 100 |
| `pan` | one pan drag finished | distance in screen pixels |
| `tool`, `undo`, `redo` | | — |
| `ai_suggest` | a suggestion was rendered to the annotator | — |
| `ai_accept` / `ai_reject` | | — |

**No coordinates are recorded, ever.** A stream reconstructs how an annotation
was made; it cannot reconstruct the annotation. That is a structural property of
the event record, not a policy — there is no field a coordinate could go in, and
a test asserts it.

Stroke length is in image pixels rather than screen pixels, so the same stroke
measures the same whether the annotator was zoomed in or out.

## Configuration

```yaml
annotation_telemetry:
  enabled: true
  fidelity: events           # off | summary | events
  store_events: true
  include_schemas: []        # empty = every geometry schema
  exclude_schemas: []
  idle_ms: 120000            # gap above which time is idle, not active
  flush_interval_ms: 10000
  disclose_to_annotators: true
  detection:
    enabled: true
    calibrate: false         # fit thresholds from this project's own data
    thresholds: {}
```

`fidelity: summary` derives every feature but persists no raw stream. Use it when
you want the numbers without keeping a replayable record of each annotator's
session.

`idle_ms` defaults to two minutes rather than something tighter because
**inspecting a hard image is real work that produces no events at all**. A
30-second idle cut-off would charge careful looking to idle time and reward
whoever clicked fastest.

## What the numbers mean

| Feature | Reading it |
|---|---|
| `ai_accept_latency_median_ms` | the primary signal |
| `ai_accepted_then_edited` | accepts that were subsequently corrected — evidence of actual review |
| `shape_interval_median_ms` | pace of **hand-drawn** shapes, only meaningful against the project's own distribution |
| `shapes_drawn` / `shapes_from_ai` | how the shapes got there |
| `revision_ratio` | edits ÷ (creates + edits) |
| `zoomed_fraction` | share of the session spent above 1.05× |
| `active_ms` / `idle_ms` | time on task, split at `idle_ms` |
| `vertices_median` | polygon detail — a 4-vertex "polygon" around a curved object is a box in disguise |

### Screening flags

| Flag | Fires when | What it does **not** establish |
|---|---|---|
| `rubber_stamping` | ≥5 accepts, median latency < 500ms, ≤5% subsequently corrected | that the annotator was wrong. A genuinely excellent detector produces suggestions that *deserve* to be accepted. Check the suggestions before the annotator. |
| `hasty` | ≥4 **hand-drawn** shapes, median interval < 700ms | that the work is bad. Drawing boxes on obvious objects is legitimately quick. |
| `never_zoomed` | never magnified — **and only when another flag already fired** | anything on its own. A project whose objects fill the frame needs no zoom. |

`never_zoomed` is deliberately never reported alone. Flagging every annotator on
a task that does not require zoom would train reviewers to ignore the flag, and
a flag people ignore is worse than no flag.

### Accepted suggestions are not "drawing"

The client commits an accepted suggestion through the same path as a hand-drawn
shape, so it arrives as a `shape_add` milliseconds later. Pace is therefore
measured over `shapes_drawn` only.

This is not a technicality. An annotator who reviews eight suggestions for four
seconds each and then accepts them produces eight shapes in rapid succession —
so counting accepted shapes as drawing would have the latency measure report
"careful" and the pace measure report "hasty" about the same behaviour, firing
hardest on exactly the annotators doing it right. Found by running the exporter
on a two-annotator fixture and noticing the careful one was flagged too.

### These are screening signals, not findings

The correct use of everything on this page is deciding **what to look at**. None
of it is evidence of misconduct, and the API returns each flag with a note
saying so, because a flag surfaced in a dashboard without its caveat gets read
as a finding.

## Calibration

Thresholds cannot be transplanted between tasks — the same finding as
Conijn, Roeser & van Zaanen (2019) for keystrokes. The built-in defaults are
documented **starting points**, not values with evidence behind them.

```yaml
annotation_telemetry:
  detection:
    calibrate: true
```

This fits thresholds from the project's own distribution (default: the fastest
5% of its sessions). It refuses to fit on fewer than 30 sessions and falls back
to the defaults — a threshold from a handful of sessions is worse than a
documented constant, because it *looks* principled.

An explicit `thresholds:` override always wins over a fitted value, being the
most specific statement of intent.

## Where the data goes

| Destination | What | Why |
|---|---|---|
| `<task_dir>/project.sqlite` | raw event streams + per-session features | `user_state.json` is rewritten **in full** on every annotation save |
| `user_state.json` | the compact summary only, under `annotation_telemetry` | so it travels with the annotation through export |

Sessions on the same schema and instance are merged before the summary is
written: leaving an image and coming back is one piece of work, not two
suspiciously short ones. The flags are re-evaluated against the *merged* view,
so five fast accepts within one short session may be a small fraction of the
item's total once everything is counted.

## Admin

`GET /admin/api/annotation_process` — per-annotator rollup, ranked by
`annotation_process_risk`. Also available as the `annotation_process` key of
`/admin/api/behavioral_analytics`.

Annotators who never used AI assistance sort **last** rather than first:
ordering on a null latency would otherwise put the people with no signal at all
above the ones worth looking at.

## Export

```bash
potato export <config.yaml> --format annotation_telemetry
```

Writes `annotation_sessions.parquet` and `annotation_events.parquet` (JSONL when
pyarrow is absent). The event table promotes `suggestion_id` to its own column,
because pairing suggest to accept is the first thing anyone does with it.

Because these are behavioural measurements of identifiable annotators, this is
deliberately **not** part of the default annotation export.

## Disclosure and ethics

Annotators see a persistent notice by default. It is rendered server-side, so it
survives a script that fails to load and cannot be removed by disabling
JavaScript. It states the limit of the collection as well as its existence —
someone told only "your annotation is recorded" will reasonably assume something
more invasive than timing.

Setting `disclose_to_annotators: false` logs a warning. The same reasoning as
[keystroke logging ethics](keystroke_logging_ethics.md) applies in full: this is
behavioural data about people, and consent documentation should cover it.

## Citations

- Skitka, L., Mosier, K., Burdick, M. (1999). Does automation bias
  decision-making? *International Journal of Human-Computer Studies* 51(5).
  doi:10.1006/ijhc.1999.0252
- Parasuraman, R., Manzey, D. (2010). Complacency and Bias in Human Use of
  Automation. *Human Factors* 52(3). doi:10.1177/0018720810376055
- Conijn, R., Roeser, J., van Zaanen, M. (2019). Understanding the keystroke log.
  *Reading and Writing* 32(9). doi:10.1007/s11145-019-09953-8 — why thresholds
  must be calibrated per task.

## Related

- [Keystroke Logging](keystroke_logging.md) — the free-text counterpart
- [Behavioral Tracking](behavioral_tracking.md)
- [Geometry Agreement](geometry_agreement.md) — agreement catches disagreement;
  this catches agreement that was never actually reached
