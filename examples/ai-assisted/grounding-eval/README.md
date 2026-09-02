# Grounding evaluation

Which region of an image a piece of language refers to — and, just as
importantly, when it refers to nothing at all.

```bash
# from the repository root
python examples/ai-assisted/grounding-eval/generate_images.py   # needs Pillow
python potato/flask_server.py start \
    examples/ai-assisted/grounding-eval/config.yaml -p 8000
```

## What is in the data

Two scenes of coloured rectangles — deliberately not photographs, because a
referring expression has to have an unambiguous answer or the example measures
the annotator's guess rather than the interface.

Each scene carries one phrase with **no referent**:

| Scene | Phrases | The trap |
|---|---|---|
| `scene_a` | red / blue / green squares, "the yellow circle" | there is no yellow circle |
| `scene_b` | purple / orange rectangles, "the person standing between them" | there is no person |

Those are the point. The hardest thing to measure about a vision-language model
is what it does when asked about something that is not there, and you can only
measure it if the annotator can say so.

## What to look at

- **Three states, not two.** Each phrase is *located*, *not present*, or *not
  answered*. The list shows which, and the progress line names what is left.
  Leaving a phrase blank is not the same as judging that nothing matches it —
  they support opposite conclusions about a model that also produced nothing.
- **One phrase at a time.** The canvas holds only the selected phrase's region.
  Switch phrases and it swaps. You cannot see all the regions at once, which is
  a real cost, taken deliberately: seeing them all is a display problem,
  mis-attributing one is a data problem.
- **Draw, switch away, switch back.** The region comes back. Draw for a second
  phrase and each keeps its own.
- **Say "not present" for the yellow circle**, then try to draw a region for it
  anyway — the absent claim is withdrawn, because both at once would make the
  stored answer contradict itself.

## Pointing evaluation

Molmo-style models emit points, not boxes. Same schema, one line different:

```yaml
  - annotation_type: grounding_eval
    region_type: point        # the annotator places a landmark
```

Points are scored differently, in `potato/grounding/metrics.py`:
a point has no area, so IoU against it is always 0 and the measure is
**point-in-region** — a hit rate, not an overlap. `pointing_accuracy()` reports
that, plus the mean distance from the region's centre over the misses only
(averaged over hits too, it would mostly measure how big the objects are).

## Hallucination localization

When the phrases are not known in advance — because they are whatever a model
happened to say — select them out of the caption instead:

```yaml
  - annotation_type: grounding_eval
    expression_source: spans
    caption_field: caption      # the model's generated caption on the item
```

The caption is shown, the annotator selects a phrase, and grounds it or marks
it ungrounded. Output includes per-caption grounded/ungrounded character rates.

Offsets, not tokens: tokenization is the model's business and two tokenizers
disagree, while character offsets are what the annotator actually selected. A
consumer that wants tokens can map them from the offsets; the reverse is not
possible.

## Scoring a model against this

```python
from potato.grounding import grounding_accuracy, pointing_accuracy

report = grounding_accuracy([
    {"truth": human_region, "prediction": model_region},
    {"truth": None, "truth_absent": True, "prediction_absent": True},
])
```

Accuracy is reported at several IoU thresholds (0.25 / 0.5 / 0.75 / 0.9), not
one. A single threshold cannot distinguish "nearly right" from "nowhere near",
and a model tuned to clear 0.5 exactly looks identical to one that is genuinely
tight. The absent cases are counted separately — correctly declined,
hallucinated a location, missed a present referent — because none of those is
an IoU.

An expression the annotator never answered is **excluded** from the denominator
rather than counted as a miss. Counting it would make a model look worse the
more phrases were skipped, which is a statement about the annotator.

## Related

- [VLM grounding & pointing](../../../docs/agent-evaluation/vlm_grounding.md)
- [Image annotation](../../../docs/annotation-types/multimedia/image_annotation.md)
