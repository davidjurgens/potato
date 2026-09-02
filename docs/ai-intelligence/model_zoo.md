# The model zoo

Potato runs several vision models. None of them ships with the package, and
none is fetched behind your back. This page lists what is available, what each
one costs to install, what licence applies, and where it runs.

```bash
potato download-models --list
```

## What is available

| Model | Job | Runs | Size | Licence |
|---|---|---|---|---|
| `mobile_sam` | Click or box → mask | Browser | 45 MB | MIT export, Apache-2.0 upstream |
| `grounding_dino_tiny` | Text → boxes | Browser | 145 MB | Apache-2.0 |
| `sam2_video_tiny` | Prompt one frame → track through the rest | Server | 181 MB | Apache-2.0 |
| `edge_sam` | Click → mask, fastest on weak hardware | Browser | — | **Non-commercial only** |
| `sam3` | Text → boxes and masks, one model | Server | ~3.5 GB | Meta SAM License |
| `edgetam` | On-device tracking, 22× faster than SAM 2 | — | — | Apache-2.0 |
| `onnxruntime` | The inference runtime the others need | Browser | 13.5 MB | MIT |

Two entries have no download. `edge_sam` permits non-commercial use only, so
we leave the URL out; making it one command away would invite people to install
it without reading the licence. `edgetam` has no published ONNX export at all
(upstream ships CoreML), so there is nothing to fetch yet. Its entry exists
because the video session is written against a task, so the day an export
appears, filling in the URL is the whole job.

## Installing

```bash
# Click-to-segment: the default, and the smallest useful thing
potato download-models mobile_sam
potato download-models onnxruntime

# Text prompting
potato download-models grounding_dino_tiny

# Video tracking
potato download-models sam2_video_tiny
```

Every file is verified against a pinned SHA-256, and a failed check deletes
the file. That matters more than it sounds: an unverified model produces wrong
masks instead of an error, and wrong masks are much harder to notice.

For an air-gapped install, run the downloads on a connected machine and copy
`potato/models/` across. That directory is the whole dependency.

## Where each model runs, and why

**Interactive segmentation and text prompting run in the browser.** One image,
one prompt, a result in well under a second. Once the files are on disk you need
no GPU and no network. Measured: 132 ms per SAM click after the image is
encoded.

**Video tracking runs on the server.** SAM 2's video path is five graphs, and
you pay that cost once per frame instead of once per prompt. A hundred frames in
WebAssembly is minutes of a frozen tab; the same loop server-side is seconds on
a GPU and a bearable wait on a CPU. The frames are already on the server anyway,
so nothing has to be uploaded.

**SAM 3 runs on the server, or on an inference server you operate.** Three
graphs totalling about 3.5 GB is not a browser download at any quantization.

## Licences

Read the licence for any model before using it in a study. Two need attention:

`edge_sam` is under the NTU S-Lab License 1.0, which permits non-commercial use
only. `potato download-models --list` prints `<-- NON-COMMERCIAL` next to it.

`sam3` is under Meta's SAM License, which is not Apache-2.0. Commercial use is
permitted and you own your derivative works, but acceptable-use restrictions
apply and redistribution must carry the same licence. Potato redistributes no
SAM 3 files and refuses to fetch it without `--accept-licence`.

## Choosing between text prompting and SAM 3

Both answer "find every traffic cone". The trade is licence and size against
quality:

| | `grounding_dino_tiny` + SAM | `sam3` |
|---|---|---|
| Licence | Apache-2.0 throughout | Meta SAM License |
| Install | 190 MB, one command | ~3.5 GB, weights you supply |
| Hardware | Any laptop | A GPU, realistically |
| Air-gapped | Yes | Yes, once you have the weights |
| Quality | Good on common objects | Better, especially on unusual phrases |

The Apache-2.0 pair is the default because it works everywhere. SAM 3 exists
for teams that want the better model and have read the licence.

## Adding a model

A model is one entry in `potato/model_zoo.py` and one session class. The entry
carries the download URLs and hashes, the licence, the task it performs, and the
parameters the browser needs. Keeping those together is what makes swapping a
model one edit instead of a hunt through JavaScript.

```python
ModelSpec(
    key="my_detector",
    task=ModelTask.TEXT_DETECTION,
    description="What it does",
    licence="Apache-2.0",
    requires=("onnxruntime",),
    client={"session": "MyDetectorSession", "model": "model.onnx"},
    files=[ModelFile(name="model.onnx", url="...", sha256="...", size_mb=12.3)],
)
```

Whatever you add, test its input contract against the real weights. Misreading
a vision model's preprocessing gives you a confident answer that is wrong, which
is the worst kind. Three plausible readings of SAM's contract produced centroid
errors of 70 to 148 pixels, and every one of them returned a mask that looked
perfectly reasonable. `tests/unit/test_sam_model_pipeline.py` and
`tests/unit/test_gdino_js_python_bridge.py` are the pattern to copy.

## Related

- [Segmentation](../annotation-types/multimedia/segmentation.md) — click-to-segment
- [Text prompting](../annotation-types/multimedia/text_prompting.md) — find objects by name
- [Video annotation](../annotation-types/multimedia/video_annotation.md) — tracking and propagation
- [Air-gapped deployment](../deployment/air_gap.md)
