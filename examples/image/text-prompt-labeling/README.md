# Text-prompt labelling

Type what you are looking for. The detector boxes every match and offers each
one as a suggestion you accept or reject.

No GPU, no server-side model, and no network call once the model is on disk —
it runs in the annotator's browser through ONNX Runtime Web.

## Running it

```bash
# 1. Fetch the model (~145 MB) and the runtime (~13 MB), once per install
potato download-models grounding_dino_tiny
potato download-models onnxruntime

# 2. Fetch the three photographs (or --synthetic if you are offline)
python examples/image/text-prompt-labeling/fetch_images.py

# 3. Run it
python potato/flask_server.py start \
    examples/image/text-prompt-labeling/config.yaml -p 8000
```

Then open <http://localhost:8000>, type `cat` in the **Find** box and press
Enter.

## What to try

| Image | Prompt | What you should see |
|---|---|---|
| cats | `cat` | Both cats boxed, around 0.70 confidence |
| bus | `bus` | The bus at 0.80, plus two weaker boxes on reflections |
| stop sign | `stop sign` | The sign at 0.66 |
| any | `unicorn` | Nothing, said out loud rather than a wrong box |

Try several phrases at once with commas: `bus, person, window`.

## The parts worth understanding

**Suggestions, not annotations.** Nothing the model returns is stored until you
accept it. That is deliberate. A dataset assembled from unreviewed model output
agrees with the model rather than with reality, and the usual quality measures
— inter-annotator agreement included — get *better* when that happens, because
the geometry is identical to careful work. The only signal that separates
review from rubber-stamping is timing, which Potato records when you accept.

**Two models, composed.** Grounding DINO turns text into boxes. The SAM decoder
already in Potato turns a box into a mask. Set `text_prompt.segment: true` in
the config and an accepted box arrives as a mask instead. Both models are
Apache-2.0 and small enough to run locally, which is the whole reason to use
two rather than one large licence-gated model that does both.

**The thresholds mean different things.** `box_threshold` decides whether a box
is offered at all. `text_threshold` decides which of your phrases it gets
labelled with. Lower the first to see more objects; lower the second when a
multi-word phrase is being attributed to the wrong thing.

**It will be wrong sometimes.** The tiny model misses small objects and can
attach a plausible label to the wrong region. That is what the accept/reject
step is for.

## Images

The photographs come from COCO val2017 and are downloaded on request rather
than committed, so they stay under their own terms. `fetch_images.py
--synthetic` draws plain scenes instead if you have no network.

## See also

- [Segmentation](../../../docs/annotation-types/multimedia/segmentation.md) —
  click-to-segment with the same runtime
- [Image annotation](../../../docs/annotation-types/multimedia/image_annotation.md)
  — every tool and keyboard shortcut
