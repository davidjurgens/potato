# World-Model and Generative-Video Evaluation

Several videos of the same scenario, frame-locked on one timeline. The
annotator finds **the frame at which each rollout stops making sense**, says
why, picks a winner, and — where the scenario carries an intervention — judges
whether the divergence follows from it.

Potato then reports whether the annotators agreed on where the break was.

---

## Why a break-point rather than a rating

Rating a generated video 3/5 for "physical plausibility" produces a number that
cannot be checked, cannot be localised, and cannot be used to fix anything.

The annotation that *can* is a point in time plus a category:

- it is **checkable** — a researcher can open frame 47 and look;
- it is **localised** — the failure has a place in the tensor, not just a score;
- it is **comparable** — two annotators' answers are two points on a line, so a
  real chance-corrected agreement statistic applies.

Video-generation benchmarks report FVD and win rates. None of them reports
whether the humans producing those win rates agree with each other, which means
none of them can separate a model difference from annotator noise. That is what
this schema is for.

---

## Quick start

```bash
python examples/agent-traces/world-model-rollouts/generate_rollouts.py
python potato/flask_server.py start \
    examples/agent-traces/world-model-rollouts/config.yaml -p 8000
```

The example ships three scenarios. Each model rollout is wrong in one specific,
findable way, and the frame it goes wrong at is deliberately **not** in the data
— that is what the annotator is being asked to find. The generator's docstring
lists the answers.

---

## Configuration

```yaml
annotation_schemes:
  - annotation_type: rollout_evaluation
    name: rollout_review
    description: "Where does each rollout stop making sense?"

    # The item fields holding each rollout's video.
    streams:
      - field: real
        name: "Recording"
        role: real          # `real` | `model` | `counterfactual`
      - field: gen_a
        name: "Model A"
      - field: gen_b
        name: "Model B"

    fps: 25                 # required for frame numbers -- see below

    prompt_field: prompt
    intervention_field: intervention
    intervention_time_field: intervention_t

    layers: [violations, preference, counterfactual]

    blind: true             # hide the generator names
    shuffle: true           # permute panel order per annotator
    require_clean: true     # warn before leaving a panel unanswered
```

### Every option

| Key | Default | What it does |
|---|---|---|
| `streams` | — | List of `{field, name, role, id, fps}`. Required unless `manifest_field` is set. |
| `manifest_field` | — | Item field holding a path to a rollout manifest, for datasets shipped as directories. |
| `fps` | — | Declared frame rate. Without it, **frame numbers are omitted** rather than guessed. |
| `prompt_field` | `prompt` | Item field carrying the scenario text. |
| `intervention_field` | `intervention` | Item field describing what was changed partway through. |
| `intervention_time_field` | `intervention_t` | When the intervention happened, in seconds. |
| `layers` | all three | Any of `violations`, `preference`, `counterfactual`. |
| `violation_types` | 10 physics categories | `{name, description}`; the description becomes the option's tooltip. |
| `severities` | 3-point scale | `{value, name, description}`. Ordinal — the values are compared as numbers. |
| `cf_verdicts` | 4 verdicts | Counterfactual plausibility options. |
| `rubric` | — | `{dimension: description}`, scored 1–5 alongside the preference. |
| `blind` | `true` | Replace generator names with positional letters. |
| `shuffle` | `true` | Permute the panel order per annotator. |
| `require_clean` | `true` | Warn before leaving an item with an unanswered panel. |
| `max_violations` | — | Cap on marks per item. |

---

## The frame rate must be declared

HTML5 video exposes no frame rate. There is no `video.fps`, and deriving one by
timing `requestVideoFrameCallback` gives the *display* rate, not the encoded
one.

So Potato takes the frame rate from `fps` on the schema (or from a manifest),
and **when nothing declares one, frame numbers are omitted** rather than
computed from a guess. The output of this schema is "the physics breaks at
frame 47", checked against a tensor by someone who was not in the room; a frame
number off by a factor of 30/24 is worse than no frame number, because it looks
right.

Frame stepping and mark nudging are also unavailable without it, and the
interface says so rather than doing nothing.

Marks are **stored in seconds**, snapped to the middle of the frame they fall
in. The half-frame offset is not cosmetic: `frame / fps` is a boundary, and
which frame a browser shows at a boundary is unspecified, so two panels can
land on different frames from the same expression.

---

## "No breaks" is an answer

A panel with no marks is ambiguous. Did the annotator watch it and find
nothing, or never get to it?

Those two readings give **opposite detection agreements**, so Potato does not
guess: marking a panel clean (the *No breaks* button, or `c`) is an explicit
act, and an annotator who did neither is excluded from that panel's agreement
rows rather than counted as having found nothing.

With `require_clean: true` the interface keeps a running "2 of 3 panels
answered" line and warns once before you leave an item with a panel
unanswered. It **warns and allows** rather than blocking: a panel whose video
failed to decode can never be answered, and a hard block would trap the
annotator with no way forward.

---

## Blinding and panel order

Both are decided server-side, per annotator.

- **Order** is permuted so preference judgements do not inherit a position
  bias. The permutation is seeded from `(annotator, item)`, so it is the *same*
  every time that annotator returns to that item — otherwise their second look
  disagrees with their first and the answers cannot be pooled. Annotations
  reference the **stream id**, never the panel position.
- **Blinding** replaces the display names with `A`, `B`, `C`.

**What blinding does and does not do.** The stream ids still travel to the
browser, because they are what annotations reference and what agreement joins
on — so a determined annotator can read `value="gen_a"` off a radio button in
devtools. This is deliberate. Blinding defeats the bias that actually occurs
(seeing a model's name next to a clip and rating it accordingly) and does not
defeat someone who sets out to defeat it. If you need the stronger property,
give the streams non-revealing ids in the config (`id: s1`, `id: s2`) and keep
the mapping outside Potato.

---

## Keyboard

Every action has a shortcut, and every shortcut is the only keyboard path to
what it does.

| Key | Action |
|---|---|
| `space` | Play / pause every panel |
| `,` `.` | Step one frame back / forward |
| `1`–`9` | Choose a panel |
| `m` | Mark a break at this frame on the chosen panel |
| `c` | Mark the chosen panel as having no breaks |
| `[` `]` | Move between marks |
| `←` `→` | Nudge the selected mark one frame |
| `Delete` | Delete the selected mark |

Shortcuts are suppressed while typing in a field.

---

## The violation taxonomy

> **"Break" and "violation" are the same thing.** The interface says *break*
> because it fits on a button and reads naturally mid-task ("mark a break", "no
> breaks"); the config keys and the stored JSON say *violation* because that is
> the term the literature uses. Nothing distinguishes them.

The default categories, each with the definition shown as its tooltip:

| Category | An object… |
|---|---|
| `object_permanence` | vanishes, or appears, with nothing causing it |
| `rigid_body_violation` | solid object bends, stretches or changes size |
| `interpenetration` | two solid objects pass through each other |
| `gravity_violation` | floats, falls upward, or stands unsupported |
| `causality_violation` | an effect happens before, or without, its cause |
| `identity_flicker` | swaps identity or category between frames |
| `appearance_drift` | texture, colour or shape drifts with no event |
| `implausible_deformation` | deforms in a way its material would not |
| `agent_intent_break` | an agent abandons or reverses a goal it was pursuing |
| `affordance_violation` | is used in a way its form does not permit |

The definitions are not decoration. An annotator who cannot tell
`rigid_body_violation` from `implausible_deformation` will pick whichever is
first in the list, and the category agreement measured over their answers will
be about the list order rather than about the video.

Replace the list wholesale for a different domain.

---

## The counterfactual layer

This is the layer that separates a world model from a video generator.

Give an item an `intervention` and an `intervention_t` — "the wall was moved 50
px to the left at 1.5 s" — and the annotator is asked whether the rollout's
divergence *follows from* that intervention:

| Verdict | Meaning |
|---|---|
| `plausible` | The divergence follows from the intervention. |
| `implausible` | The divergence contradicts the intervention, or ignores it. |
| `unchanged` | The rollout ignored the intervention entirely. |
| `unclear` | Cannot tell from this rollout. |

A model that produces a beautiful continuation which ignores the intervention
has failed at the thing world models are for, and no plausibility rating
detects that, because the video *is* plausible.

The block is hidden on items with no intervention — asking the question about a
set with nothing to diverge from produces an answer to a question that was not
asked.

---

## Agreement over break-points

Reported by the standard IAA machinery (`/admin/iaa`), decomposed the same way
[geometry agreement](../advanced/geometry_agreement.md) is, because the question
decomposes the same way:

| Measure | Question | Method |
|---|---|---|
| `detection` | Do annotators agree this rollout breaks *at all*? | Krippendorff's α over present/absent per matched break cluster |
| `localization` | Given both marked one, do they agree *when*? | Mean offset in seconds **and frames**, plus σ and KS against a between-item chance baseline |
| `category` | Do they agree *why*? | α over the violation type, on clusters at least two annotators marked |
| `severity` | Do they agree *how badly*? | α, **ordinal** — the distance from "subtle" to "breaks the scene" is larger than between adjacent grades |
| `preference` | Do they pick the same winner? | Nominal α |
| `counterfactual` | Do they give the same verdict? | Nominal α |

Plus `coverage.answered_fraction`: detection is computed only over panels an
annotator answered about, which correctly but silently narrows the denominator.
A 0.9 detection α over a third of the panels is a different claim from a 0.9
over all of them.

### The tolerance is swept, not chosen

Two break-points count as the same break when they fall within a tolerance
window, and **every number above depends on that window**. Annotators who agree
to within two seconds may agree on nothing at a quarter-second.

So the report is a sweep — by default 0.04 s (about one frame), 0.25, 0.5, 1.0
and 2.0 — and the curve itself is the finding:

- agreement **flat across the sweep** means annotators identify the same
  instant;
- agreement that **only appears at two seconds** means the most that can be
  claimed is "they agree something is wrong in this clip".

Picking one tolerance and quoting a single number makes the claim
unfalsifiable, because the reader cannot tell a tight agreement from a generous
window. The headline tolerance (0.5 s by default) is reported alongside the
full sweep, never instead of it.

`/admin/iaa?format=html` draws the sweep as its own table — one row per window,
one column per measure, the headline row tinted — under the flat metric list.
Read a column downwards: that is the curve. The JSON at `/admin/iaa` carries
the same sweep under `schemas.<name>.metrics.sweep`, unflattened, which is what
an analysis script should read.

Where a coefficient is undefined the report says why rather than printing a
blank. "Every annotator marked the same breaks, so there is no variation for
alpha to correct against" is perfect agreement; "fewer than two judgements to
compare" is no data. Both are α = `null` in the JSON and they are opposite
findings, so the reason travels with the value — inline in the metric list, and
as a numbered footnote under the sweep table.

`localization.sigma` is **conditional on a match**, so it is bounded by the
tolerance by construction and rises as the tolerance falls. That is not a
defect to correct for; it is why the sweep exists. For a number to quote
directly, use `mean_offset_frames`.

---

## VLM-as-judge over rollouts

The judge samples frames from a rollout, assembles them into a numbered contact
sheet, and asks a vision endpoint for the first frame at which the scene stops
being coherent, plus a category.

The point is not to replace the annotator. It is to make automated world-model
benchmarks **checkable**: the judge's break-point is scored against the human
one with the same matcher humans are scored against each other with, so
"our automatic metric agrees with human judgement" becomes a number rather than
an assertion.

Requires ffmpeg (to sample frames), Pillow (to assemble the sheet), and a
vision-capable AI endpoint.

### Running it

| Endpoint | Purpose |
|---|---|
| `POST /api/rollout/judge` | Judge the annotator's **current** item. One interactive check. |
| `POST /admin/api/rollout/judge-batch` | Judge **every** rollout in the project and persist the predictions. |
| `GET /admin/api/rollout/alignment` | Score the persisted predictions against the human consensus. |

```bash
# judge at most 50 items, one model call per stream
curl -X POST localhost:8000/admin/api/rollout/judge-batch \
     -H "X-API-Key: $POTATO_ADMIN_KEY" -H 'Content-Type: application/json' \
     -d '{"max_items": 50, "streams": ["gen_a"]}'

# then score it — as often as you like, at any tolerance, for free
curl "localhost:8000/admin/api/rollout/alignment?tolerance=0.5" \
     -H "X-API-Key: $POTATO_ADMIN_KEY"
```

The batch is **not** free: one model call per stream plus an ffmpeg seek per
sampled frame, so a four-panel comparison over 500 items is 2000 calls. Hence
`max_items`, `streams`, and a summary that lists everything it skipped and why
— an alignment number computed over a silently truncated sample is worse than
no number at all. Scoring is a separate call because it costs nothing, so the
tolerance can be varied and the report re-run as more people annotate.

Predictions are stored per prompt version in `rollout_predictions.json`, so
re-running after changing the prompt compares like with like instead of
overwriting the previous run's evidence.

### There is no single human answer, so one is built

The judge is scored against a **consensus** derived per stream from every
annotator who answered about it:

- more annotators marked it **clean** than marked a break → the consensus is
  "no break", a real answer the judge can be right or wrong about;
- more marked a break → the consensus time is the **median** of their marks and
  the category is the modal one. Median, so one annotator who marked the wrong
  moment entirely moves the answer by one position rather than dragging it
  across the clip;
- **nobody answered** → the stream contributes nothing. Counting silence as
  "clean" would manufacture agreement with a judge that also found nothing.

Where several marks sit on one stream, the earliest counts: the question is
where the rollout *stops* making sense, and a later mark is a further failure,
not a competing answer.

Unlike the agreement report, one annotator is enough. A single person's answer
is a perfectly good thing for a judge to be right or wrong about; the
two-annotator floor exists because a person cannot agree with themselves.

**Why a contact sheet.** Almost every vision endpoint takes one image per call.
Asking "is this frame wrong?" about a single frame cannot be answered — a
physically impossible state is usually only visible as a *change*, and one
frame of a floating cup looks like a cup on a shelf. A numbered grid gives the
model the sequence in the one image the API accepts.

**The resolution is part of the answer.** A 12-tile sheet of a 6-second clip
localises a break to ±0.25 s and no better, so every prediction carries its own
`resolution` and the alignment **refuses** a tolerance finer than that rather
than reporting a disagreement that is an artifact of the sampling.

**A failed call is not a verdict.** A model that timed out has said nothing
about the rollout; it gets an `error` prediction that is excluded from
alignment, never a "no break found". Counting an outage as agreement with an
annotator who also found nothing is how an automatic metric flatters itself.

---

## Storage

One JSON blob under a single `_data` key, as every other blob schema uses:

```json
{"violations": [{"stream": "gen_a", "t": 3.42, "type": "interpenetration",
                 "severity": 2, "note": ""}],
 "clean": ["real"],
 "preference": {"winner": "gen_a", "confidence": "2", "rubric": {"physics": 4}},
 "counterfactual": {"verdict": "plausible", "t": 2.10, "note": ""}}
```

Times are in **seconds**, matching every other temporal schema. Frames are
displayed, never stored — the frame rate is a declaration, and a stored frame
index would be wrong the moment it changed.

---

## Troubleshooting

**The timeline is empty and the time reads 0.00 s.** No panel has reported its
length. Give it a few seconds; if it persists, the browser probably cannot
decode the videos — Chromium ships without an H.264 decoder, so MP4 rollouts
need converting to WebM/VP9:

```bash
ffmpeg -i rollout.mp4 -c:v libvpx-vp9 -crf 30 -b:v 0 rollout.webm
```

**No frame numbers anywhere.** Set `fps` on the schema. Potato will not guess
one.

**A panel says "video not found".** The stream field's value is resolved
relative to `media_directory`. Absolute URLs and paths already starting with
`/` are used as-is.

**"Choose a panel first".** A break belongs to one rollout. Press `1`–`9` or
click a panel's button before marking.

**Panels differ in length.** Reported as a warning rather than hidden: a short
rollout is usually a generation that terminated early, which is itself worth
annotating. The timeline runs to the longest.

---

## Related

- [Judge Alignment](judge_alignment.md) — the categorical human↔judge machinery
  this builds on
- [Geometry Agreement](../advanced/geometry_agreement.md) — the same
  decomposition applied to 2D shapes
- [Embodied Episodes](../annotation-types/embodied/episodes.md) — multi-stream
  video with time-series lanes
- [Video Annotation](../annotation-types/multimedia/video_annotation.md)
