# Text prompting: find objects by name

Type `traffic cone` and every traffic cone in the image comes back boxed, as a
suggestion to accept or reject. The model runs in the annotator's browser, so
once it is installed there is no GPU to provision and no network round trip.

## Setup

```bash
potato download-models grounding_dino_tiny   # 145 MB, once per install
potato download-models onnxruntime           # 13.5 MB, shared with segmentation
```

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: objects
    description: "Find and label the objects"
    tools: [bbox, polygon, sam]
    labels: [cat, bus, stop sign]

    text_prompt:
      phrases: [cat, bus, stop sign]   # what the box starts with
      box_threshold: 0.3               # how sure before a box is offered
      text_threshold: 0.25             # how a box gets its label
      segment: false                   # true turns accepted boxes into masks
```

Run the [example](https://github.com/davidjurgens/potato/tree/master/examples/image/text-prompt-labeling)
to see it working:

```bash
python examples/image/text-prompt-labeling/fetch_images.py
python potato/flask_server.py start \
    examples/image/text-prompt-labeling/config.yaml -p 8000
```

## The model behind it

The model is Grounding DINO, an open-vocabulary detector: it takes an image and
a caption, and scores 900 candidate boxes against every word of that caption.
Potato assembles the caption from your phrases, runs the model through ONNX
Runtime Web, and turns the output into suggestions.

Boxes become masks by a second step: each accepted box is handed to the SAM
decoder that already powers click-to-segment. Two small permissively licensed
models compose into what one large licence-gated model does alone. Set
`segment: true` and include `sam` in `tools`.

## The two thresholds

They answer different questions, which is why there are two.

`box_threshold` decides whether a box is offered **at all**. Lower it to see
more objects, including worse ones.

`text_threshold` decides **which of your phrases** a box is labelled with. A box
carries a score against every token of the caption, and the phrase is recovered
from which tokens scored highest. Lower this when a multi-word phrase like
`traffic light` is being attributed to the wrong object.

## Suggestions, not annotations

Nothing the model returns is stored until an annotator accepts it. The extra
click is the point.

A dataset assembled from unreviewed model output agrees with the model, not
with the world. Worse, every quality measure Potato has gets *better* when that
happens, inter-annotator agreement included, because the geometry is identical
to careful work. Timing is the one signal that separates review from
rubber-stamping, so
[annotation telemetry](../../advanced/behavioral_tracking.md) records it when a
suggestion is accepted.

## What to expect

The bundled model is the tiny variant, quantized to fit a browser download.
On the example images it finds two cats at 0.72 and 0.69, a bus at 0.80, and a
stop sign at 0.66. It misses small objects, and it will occasionally attach a
plausible label to the wrong region. That is what the accept/reject step is
for.

Measured against the full-precision export, the quantized model Potato ships
holds box IoU of 0.97; an int8 build of the same model manages 0.87 while being
50 MB larger, which is why `q4f16` is the default.

Type a phrase the model does not know and you get nothing back, with a message
saying so. A detector that invents a box to look useful would be worse than one
that admits defeat.

## First use is slow

The model downloads on the first press of **Find**: 145 MB, once per browser
session. The button says `Finding…` while that happens. Everything after that
runs from cache.

## Comparison with SAM 3

SAM 3 does detection and segmentation from text in one model, and does it
better. It is also about 3.5 GB across three graphs, and its licence is Meta's
own rather than Apache-2.0, so it runs as a
[server endpoint](../../ai-intelligence/model_zoo.md#choosing-between-text-prompting-and-sam-3)
with weights you supply. The browser path is the default because it works on any
machine, in any network, under one permissive licence.

## Related

- [The model zoo](../../ai-intelligence/model_zoo.md)
- [Segmentation](segmentation.md) — click-to-segment with the same runtime
- [Image annotation](image_annotation.md) — every tool and shortcut
- [Annotation telemetry](../../advanced/behavioral_tracking.md) — how acceptance is recorded
