# Annotation critique (VLM as judge)

Ask a vision model to review the regions an annotator has already drawn, and
present what it doubts as a queue they work through.

This is the check inter-annotator agreement cannot make. Agreement asks whether
two people drew the same shape. It is silent when both are confidently wrong —
which is what an ambiguous guideline produces — and it says nothing at all when
there is only one annotator, which is the usual state of a pilot. A model
looking at each region independently answers a different question: *is the
outlined thing really a `{label}`, and does the outline fit it?*

It is also much weaker evidence than agreement, and the interface says so every
time it opens. A flag means "look at this again", never "the model says change
it".

---

## Overview

Pressing **Review** in the AI Assist bar sends the annotations currently on the
canvas to the server. For each one the server:

1. crops the region **with surrounding context**;
2. draws the annotator's own outline onto that crop in red;
3. asks the model whether the outlined region contains the label it was given,
   and whether the outline fits.

A separate whole-image pass asks what was missed.

Both halves of step 2–3 are load-bearing:

- **Without context**, the object fills the frame by construction, so every
  boundary looks tight and "is this boundary loose?" has no answerable form.
- **Without the drawn outline**, the model cannot see where the boundary is and
  answers about one it imagined.

Cropping rather than sending the whole image matters for the same reason: a
4000×3000 photograph downsampled to a model's input resolution loses a
twenty-pixel object entirely, and the model then confirms annotations it cannot
see.

## Requirements

A vision endpoint that can also explain itself. The toolbar button is gated on
`vision_input` **and** `rationale_generation`, so:

| Endpoint | Critique available | Why |
|---|---|---|
| `openai_vision`, `anthropic_vision`, `ollama_vision` | ✅ | Sees images, writes rationales |
| Any OpenAI-compatible server via `base_url` (vLLM, SGLang, LM Studio) | ✅ | Same |
| `yolo` | ❌ | Finds boxes but cannot say why it disagrees, and a verdict with no reason is not reviewable |
| Text-only endpoints | ❌ | Cannot see the image |

Cropping needs **Pillow**. Without it the route answers with a stated reason
rather than failing opaquely.

## Configuration

Options live under the image schema's `ai_support`:

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: objects
    description: "Box every car, person and sign."
    tools: [bbox, polygon]
    labels:
      - {name: car, color: '#d6604d'}
      - {name: person, color: '#4575b4'}
      - {name: sign, color: '#5aa469'}

    ai_support:
      enabled: true
      features:
        critique: true          # the Review button; default true
      critique:
        context_ratio: 0.6
        min_confidence: 0.5
        max_regions: 24
        max_workers: 4
        check_missed: true
        coverage_ratio: 0.5
```

| Option | Default | Meaning |
|---|---|---|
| `context_ratio` | `0.6` | Context around each region, as a fraction of its longer side. Lower it only if regions are so dense that neighbours confuse the model. |
| `min_confidence` | `0.5` | Verdicts below this become "unclear" and stay out of the queue. |
| `max_regions` | `24` | Cost ceiling — one model call per region. The excess is reported as "not reviewed", never dropped silently. |
| `max_workers` | `4` | Concurrent calls. Keep it low against a single-GPU server. |
| `check_missed` | `true` | Also run the whole-image "what was missed?" pass. |
| `coverage_ratio` | `0.5` | How much of a reported missed object must lie inside an existing annotation to count as already covered. |

The endpoint itself is configured as usual under the top-level `ai_support`.
Judges return JSON with a rationale, so **`max_tokens` must be at least 512** —
below that the reply is truncated mid-object and every verdict parses as
"unclear".

## What the annotator sees

The panel leads with the count that needs attention and keeps confirmations
collapsed. A panel that opens on "9 of 12 correct!" trains people to close it.

Each finding shows the verdict, the model's one-sentence reason, and the
actions that apply to it:

| Verdict | Shown as | Actions |
|---|---|---|
| `wrong_label` | Label may be wrong | Show me · Relabel to *X* · Delete · Keep as is |
| `not_an_object` | May not be an object | Show me · Delete · Keep as is |
| `loose_boundary` | Boundary may not fit | Show me · Delete · Keep as is |
| `uncertain` | Unclear (collapsed) | Show me |
| `confirmed` | Confirmed (collapsed) | Show me |

**Nothing is applied automatically, and there is no "fix all".** Every change
happens because the annotator pressed a button with the reason on screen. A
model that is right most of the time, applied in bulk, produces a dataset that
is wrong in a *correlated* way — worse than the scattered mistakes it corrects.

Possibly-missed objects are shown separately, with a "show the area" button
that draws a temporary dashed outline. They cannot be accepted as annotations:
vision-language models localize poorly, and a guessed coordinate in a dataset
is worse than no coordinate.

## What keeps the queue honest

Several rules exist specifically to stop the feature manufacturing findings:

- An **unreadable or unrecognised response** is `uncertain`, never a flag.
- A **model error or timeout** is `uncertain`. An outage is not a finding.
- A **low-confidence disagreement** is downgraded to `uncertain`.
- A **suggested label outside the schema** is not actionable — the annotator
  cannot apply a label the task does not have — so it is downgraded and the
  reason is stated.
- A **self-contradiction** (`wrong_label` naming the label the region already
  has) is resolved in favour of the label it named.
- A **missed object that lies inside an existing annotation** is dropped,
  because that is the same mistake the per-region verdict already reported.

That last one uses *containment*, not IoU, and the difference is not academic.
An oversized box plainly contains the object inside it, but its IoU with that
object is low **precisely because the box is loose** — so an IoU test reports
"you missed this car" about a car that was annotated, on exactly the images
where the boundary was already flagged.

## Calibration, honestly

`min_confidence` does less work than it looks like it should. Instruction-tuned
open models are badly calibrated on this task: in testing against a Gemma-class
vision model, essentially every verdict came back at confidence 0.9–1.0,
including the ones that were wrong. The gate catches models that hedge; it does
not catch models that are confidently wrong.

Treat the flag rate, not the confidence, as the thing to watch. If a project's
critique flags a large fraction of a careful annotator's work, the prompt is
mismatched to the task — usually because the label names mean something
specific in the domain that the model reads generically.

## Relationship to the other quality signals

| Question | Instrument |
|---|---|
| Did two annotators draw the same shape? | [Geometry agreement](../advanced/geometry_agreement.md) |
| Is this annotation right at all? | **This page** |
| How was the annotation produced? | [Annotation telemetry](../advanced/annotation_telemetry.md) |
| Which annotator should be trusted where? | [MACE](../advanced/mace.md) |

They answer different questions and fail differently. Critique is the only one
of the four that works with a single annotator, and the only one that can catch
a shared misunderstanding.

Acting on a critique is recorded by [annotation telemetry](../advanced/annotation_telemetry.md)
as an AI suggestion accepted or rejected, with the same latency measurement
used for detection suggestions — rubber-stamping a critique is exactly as bad
as rubber-stamping a detection.

## API

`POST /api/critique_annotations`

```json
{"schema": "objects", "objects": [...], "instance_id": "img_1"}
```

`objects` is optional; when absent the server reads the user's stored
annotations for the instance. Supplying them is preferred, since the annotator
expects a review of what is on screen and the last edit may not have saved yet.

Response:

```json
{
  "instance_id": "img_1",
  "schema": "objects",
  "verdicts": [
    {"index": 1, "label": "car", "verdict": "wrong_label",
     "suggested_label": "sign", "boundary": "tight", "confidence": 0.9,
     "rationale": "The outlined region contains a traffic sign, not a car.",
     "flagged": true, "error": ""}
  ],
  "missed": [],
  "summary": {"reviewed": 3, "confirmed": 1, "flagged": 1, "uncertain": 1,
              "errors": 0, "missed": 0, "skipped": 0, "caveat": "..."},
  "model": "…", "image_width": 640, "image_height": 420, "cached": false
}
```

Results are cached per (instance, schema, annotation state), so re-opening an
unchanged image does not re-run the model, while editing a box invalidates its
critique.

The route never writes an annotation.

## Troubleshooting

**"No vision-capable AI endpoint is configured"** — the project's endpoint
cannot take an image. Set a vision endpoint; see the table above.

**Every verdict is "unclear"** — almost always `max_tokens` below 512, which
truncates the JSON. Check the server log for the raw reply.

**The button is missing** — `ai_support.enabled` is false for the schema, or
`features.critique` is false, or the schema is not `image_annotation`.

**Review is slow** — one model call per region. Raise `max_workers` if the
server can take it, or lower `max_regions`.

## Related

- [Visual AI Support](visual_ai_support.md) — detection and pre-annotation
- [Geometry agreement](../advanced/geometry_agreement.md)
- [Annotation telemetry](../advanced/annotation_telemetry.md)
- Example: `examples/image/annotation-critique/`
