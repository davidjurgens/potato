# Interactive Segmentation

!!! success "Status: working end to end"

    Click-to-segment runs in the browser. Verified in a real browser against
    the real weights: a click at (150, 120) produced a mask whose centroid was
    (150, 120) — 0px error — covering 11,397 pixels where the target's true
    area is 11,310, in **132 ms** per click after a one-off encode.

    Two commands and it works:

    ```bash
    potato download-models onnxruntime     # 13.5 MB, once per install
    potato download-models mobile_sam      # 45 MB
    ```

    Then add `sam` to a schema's `tools`. The brush, eraser and colour-aware
    fill tools remain available for manual mask work.

## Why the browser is the default

`pip install potato` should give you working segmentation with no GPU, no new
Python dependency, and no outbound network at annotation time. That last point
is not a nicety: several research groups deploy Potato air-gapped, where a
model fetched at click time is a missing feature rather than a slow one.

So the planned default is **ONNX Runtime Web** running a distilled SAM-class
model in the annotator's browser. A server endpoint exists for labs that have a
GPU and want a larger model, but it is the exception.

| | Browser (default) | Server endpoint |
|---|---|---|
| Setup | `potato download-models` | `pip install 'potato[vision]'` + weights |
| GPU | Not required | Recommended |
| Air-gapped | Yes, once models are downloaded | Yes |
| Model size | Distilled (~30 MB) | Whatever you supply |

## Encoder and decoder are separate on purpose

The encoder is expensive and runs **once per image**. The decoder is cheap and
runs **once per click**. Keeping them apart, and caching the embedding per image
URL, is the entire reason click-to-segment feels interactive rather than like a
network request.

The embedding cache is bounded and evicts least-recently-**used**, so an
annotator flipping between two images does not re-encode the one they keep
returning to.

## Instance masks are a prerequisite

A segmentation model returns one mask **per object**. Potato's default mask
storage is semantic — every stroke of a class merges into one region — which
would merge those masks the moment they arrived. Set:

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: objects
    tools: [sam, brush, eraser, fill]
    mask_mode: instance      # required for interactive segmentation
    labels: [cat, dog]
```

See [Image Annotation](image_annotation.md#semantic-vs-instance-masks).

## Downloading models

Weights are **not** bundled and are **never** downloaded implicitly.

```bash
potato download-models --list          # what exists, what is installed
potato download-models mobile_sam      # fetch one
potato download-models --all
```

Two reasons for the explicit step:

- **Licensing.** SAM-family releases do not share one licence and some are not
  permissive. An explicit command means whoever runs it has seen the licence
  line printed beside the model.
- **Size.** A quantized encoder is tens of megabytes. Fetching that during an
  annotator's first click would look like a hang.

Every file is verified against a pinned SHA-256, and a mismatched download is
**deleted** rather than kept — an unverified model does not raise, it silently
produces wrong masks, which is far harder to notice than a crash.

| Model | Licence | Commercial use | Notes |
|---|---|---|---|
| `mobile_sam` | MIT (ONNX export) ¹ | Yes | **Default, and the only one with weights configured.** SAM's ViT-H encoder distilled into TinyViT: 9.66M parameters total (5M encoder) against the original SAM's 611M. Encoder 28.2 MB + decoder 16.5 MB. |
| `edge_sam` | NTU S-Lab License 1.0 | **No** | Fastest on low-end hardware. The licence permits use "for non-commercial purpose" only; commercial use requires contacting the authors. |
| `sam2_hiera_tiny` | Apache-2.0 | Yes | The only option supporting **video mask propagation**. Smallest of SAM 2's four Hiera backbones (tiny / small / base+ / large). |

¹ Upstream MobileSAM is Apache-2.0; the [ONNX export we download](https://huggingface.co/Acly/MobileSAM)
is published under MIT. Both are permissive, but they are not the same licence,
so the one recorded is the one that applies to the bytes you actually get.

### The decoder's input contract

Verified against the real export rather than assumed — the decoder declares
**six** required inputs and throws if any is missing:

| Input | Shape | Note |
|---|---|---|
| `image_embeddings` | `[1, 256, 64, 64]` | from the encoder, cached per image |
| `point_coords` | `[1, N, 2]` | absolute pixels |
| `point_labels` | `[1, N]` | **float**, not int. 1 = foreground, 0 = background, 2/3 = box corners |
| `mask_input` | `[1, 1, 256, 256]` | the previous low-res mask — this is how a second click *refines* rather than restarts |
| `has_mask_input` | `[1]` | 0 on the first click |
| `orig_im_size` | `[2]` | **height first**. The wrong order returns a silently transposed mask, not an error. |

The encoder takes raw `[H, W, 3]` pixel values: this export resizes and
normalizes internally, which is why the browser can hand it canvas pixels
directly.

!!! warning "EdgeSAM is non-commercial"

    EdgeSAM is the fastest of the three, and it is the one you most need to
    check before using. The [NTU S-Lab License 1.0](https://github.com/chongzhou96/EdgeSAM/blob/master/LICENSE)
    permits "redistribution and use for non-commercial purpose" only. That
    restriction plausibly reaches a dataset annotated with its help, so decide
    before you annotate, not after. `download-models --list` flags it.

## Optional server endpoint

For a GPU and a larger model:

```yaml
ai_endpoint:
  type: sam
  checkpoint: /path/to/sam_vit_h.pth   # a checkpoint you already hold
  model_type: vit_h
  device: cuda
```

Potato does not download these weights either. The endpoint is registered
lazily, so a server with `torch` installed but segmentation unused does not pay
the import cost at start-up.

`SAMEndpoint.segment()` currently raises `NotImplementedError`; the class exists
so the capability plumbing is in place and tested.

## Failure states

Each failure names a next action, because "segmentation unavailable" tells an
annotator nothing they can use:

| State | What the annotator sees |
|---|---|
| Runtime unavailable | The browser has WebAssembly disabled; use the brush tool |
| Model missing | The exact `potato download-models <name>` command to run |
| Encode failed | This image could not be prepared; brush and polygon still work |
| Decode failed | That click did not produce a mask; try another point |

Every message points at a tool that still works, so a segmentation problem never
blocks the annotation.

## Capability gating

Segmentation is gated on a `mask_output` capability that is **independent of**
`bounding_box_output`. A detector asked for pixels returns nothing usable, so a
box model must not advertise the segment assistant.

```python
ModelCapabilities(vision_input=True, bounding_box_output=True)   # detect only
ModelCapabilities(vision_input=True, mask_output=True)           # can segment
```

## Related

- [Image Annotation](image_annotation.md)
- [Visual AI Support](../../ai-intelligence/visual_ai_support.md)
- [Air-gapped deployment](../../deployment/air_gap.md)


## Using it

Add `sam` to the schema's `tools`, then press **`w`** (or click the wand).

| Action | Result |
|---|---|
| Click | Segment the object under the cursor |
| Click again | **Refine** the same mask, not start a new one |
| Shift-click | Subtract — remove a region the model wrongly included |
| Drag a box | Constrain the mask to that region |
| `Enter` | Accept the mask as an annotation |
| `Escape` | Discard it |

A click produces a **preview**, not an annotation. This matters more than it
sounds: a first click rarely lands the mask perfectly, and a tool that only
ever commits is one people abandon — they get a nearly-right mask, delete it,
and reach for the brush. Refinement is the difference between a demo and
something usable on a real corpus.

Each accepted mask becomes its own instance (`label#0`, `label#1`, …) and
exports to COCO as a separate RLE annotation with `iscrowd: 0`.

### Configuration

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: objects
    tools: [sam, brush, eraser]
    mask_mode: instance
    segmentation:
      model: mobile_sam       # mobile_sam | edge_sam | sam2_hiera_tiny
      embedding_limit: 4      # images kept encoded; ~4 MB each
    labels: [cat, dog]
```

## Installing the runtime

ONNX Runtime Web is **fetched, not vendored** — the wasm binary alone is
13.5 MB, more than the rest of Potato's source combined. Since segmentation
already requires downloading weights, it rides in the same step:

```bash
potato download-models onnxruntime
```

An air-gapped install therefore copies exactly one directory (`potato/models/`)
and everything works offline. Nothing is fetched at annotation time.

Threading is deliberately left **off**: multi-threaded wasm needs
`SharedArrayBuffer`, which needs COOP/COEP response headers Potato does not
set. The threaded binary runs correctly single-threaded; the non-threaded build
is simply not published separately.

## When something is missing

Each failure names the command that fixes it, and the two are kept distinct
because they have different fixes:

| Situation | What you see |
|---|---|
| Runtime not installed | *"…install it with: `potato download-models onnxruntime`"* |
| Weights not installed | *"The mobile_sam model is not installed… `potato download-models mobile_sam`"* |
| WebAssembly disabled | Same runtime message, which also names the brush tool |
| Click found nothing | *"Nothing found at that point. Try clicking the centre of the object."* |

That last one is not an error. A click on featureless background legitimately
produces no mask, and saying so beats adding an empty annotation the annotator
then has to find and delete.

!!! note "A misleading message, found by running it"

    An early version classified any "failed to fetch" as a missing *model*. A
    missing runtime glue module therefore reported *"the mobile_sam model is
    not installed"* — false, and unfixable by the command it suggested. The
    runtime's own failures are now checked first. No mocked test could see
    this; it took a real browser.

## Performance

Measured on CPU with MobileSAM, a 520×340 image:

| Step | Cost |
|---|---|
| Runtime load | once per session, 13.5 MB |
| Model load | once per session, 45 MB |
| Encode | ~1 s per image, cached |
| **Decode (per click)** | **~130 ms** |

Only the decode is in the interaction loop.

### Mask memory on large images

A mask is one bit per pixel, held in 64×64 tiles allocated only where something
is painted (`potato/static/mask-buffer.js`), and every mask composites into a
single offscreen canvas. This matters because segmentation is done zoomed in on
large images, where a mask used to cost four bytes per image pixel per class
whether or not anything was painted.

Ten classes, one 40×40 brush dab each:

| Image | Mask data | Canvas (all classes) | Render per mousemove |
|---|---|---|---|
| 1 MP | 38.1 MB → 16.0 KB | 3.8 MB | 0.017 ms |
| 3 MP | 114.4 MB → 16.0 KB | 11.4 MB | 0.018 ms |
| 12 MP | 457.8 MB → 16.0 KB | 45.8 MB | 0.013 ms |

Two independent changes:

- **Mask data** no longer scales with image area — only with what was painted.
- **Canvas** no longer scales with the class count. Previously a full-size
  temporary canvas was allocated *per class, per pointer move*, and discarded.

The canvas is an irreducible cost of drawing at natural resolution, so the
honest summary is that resident cost went from roughly 458 MB to 46 MB for ten
classes on a 12 MP photo, and per-frame allocation churn went away.

What did *not* change is bulk work: painting a stroke and encoding a whole mask
to RLE still cost one step per pixel and are within noise of the old code.

Label colours are read as hex — `#rgb`, `#rrggbb`, or `#rrggbbaa` (alpha
dropped; use `mask_opacity` for the overlay). Anything else paints red and logs
a console warning naming the value.

## How the contract was established

The tensor contract is the part that cannot be guessed, so it was **measured**
rather than assumed. The encoder takes HWC pixels at native size, but the image
must first be resized so its **longest side is 1024**, and click coordinates
must be scaled by that same factor while `orig_im_size` stays the original
`(height, width)`.

Three plausible alternative readings were tested against the real weights, on a
non-square image with three separated targets:

| Reading | Mean centroid error |
|---|---|
| Raw original pixels | 148 px |
| Scale by 1024/width and 1024/height separately | 70 px |
| Unresized image into the encoder | 70 px |
| **The contract above** | **0.1 px** |

Every wrong reading still returns a confident, plausible-looking mask. That is
why `tests/unit/test_sam_model_pipeline.py` runs the real weights and includes
controls asserting the wrong readings *are* wrong, and
`test_sam_js_python_bridge.py` has Node build the tensors and Python feed them
to the model — so a divergence between the browser code and the weights fails
the build rather than shipping.

## Related

- [Image annotation](image_annotation.md)
- [Geometry types](geometry_types.md)
- [Format matrix](../../data-export/format_matrix.md)
