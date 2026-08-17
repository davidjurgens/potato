"""
The model zoo: every downloadable model Potato can run, in one registry.

WHY THIS EXISTS SEPARATELY FROM THE CLI
---------------------------------------
``models_cli`` began as a downloader for one segmentation model and its
registry lived inside the command. That worked while there was one model. It
stops working the moment a second kind of model arrives, because three other
places need to answer questions about models that have nothing to do with
downloading them:

* the **schema generator** needs the client-side configuration for whichever
  model a project selected, so it can hand it to the browser;
* the **config validator** needs to reject a model key that cannot do the job
  the config asks of it — a detector cannot segment;
* the **admin UI and CLI** need to say what is installed and what it permits.

So the registry lives here, and the CLI is one consumer of it.

WHAT A MODEL ENTRY HAS TO CARRY
-------------------------------
Adding a model is meant to be one entry plus one client session class. For that
to hold, an entry carries more than a download URL:

* ``task`` — what it does. This is what makes "is this model usable here?" a
  lookup rather than a hardcoded list of keys in three files.
* ``licence`` / ``commercial_use`` / ``licence_ack`` — models in this space do
  not share a licence, and one of them (SAM 3) needs the user to accept terms
  before we fetch anything. A licence recorded as prose nobody reads is not a
  control; a flag is.
* ``client`` — the parameters the browser needs (input resolution, thresholds,
  which session class drives it). Keeping these next to the download means a
  model swap is one edit rather than a hunt through JavaScript.
* ``requires`` — the runtime, or a companion model. Declared rather than
  assumed, so ``potato download-models x`` can fetch what x actually needs.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
Weights. Potato downloads them on request and verifies them; it never bundles
them and never fetches them implicitly. See ``models_cli`` for why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ModelTask(str, Enum):
    """What a model is for.

    A string enum so a value can be compared against config text without
    conversion, and so it serialises into the client config unchanged.
    """

    #: Click or box in, one mask out. SAM 1-class.
    INTERACTIVE_SEGMENTATION = "interactive_segmentation"
    #: Free text in, boxes out. Grounding DINO-class open-vocabulary detection.
    TEXT_DETECTION = "text_detection"
    #: Free text in, masks out. SAM 3-class.
    TEXT_SEGMENTATION = "text_segmentation"
    #: A prompt on one frame, masks on every later frame. SAM 2-class.
    VIDEO_TRACKING = "video_tracking"
    #: Not a model: the inference runtime the others need.
    RUNTIME = "runtime"


#: Tasks whose models run in the annotator's browser. A model tagged with a
#: task outside this set needs a server endpoint, and the schema layer must not
#: offer it as a browser option.
BROWSER_TASKS = frozenset({
    ModelTask.INTERACTIVE_SEGMENTATION,
    ModelTask.TEXT_DETECTION,
    ModelTask.VIDEO_TRACKING,
    ModelTask.RUNTIME,
})


@dataclass
class ModelFile:
    """One downloadable artifact belonging to a model."""

    name: str
    url: str
    sha256: str
    size_mb: float


@dataclass
class ModelSpec:
    """A model: what it does, what it costs, what it permits, how to drive it."""

    key: str
    description: str
    licence: str
    task: ModelTask = ModelTask.INTERACTIVE_SEGMENTATION
    #: False when the licence forbids commercial use without permission. Kept
    #: as a flag rather than left inside the licence string because it is the
    #: one property that can make a model unusable for a given project, and
    #: nobody reads a licence name in a list.
    commercial_use: bool = True
    #: True when the licence requires the user to accept terms before we fetch
    #: anything. `--accept-licence` on the CLI, and no silent download path.
    licence_ack: bool = False
    licence_url: str = ""
    #: Encoder and decoder ship separately: the encoder runs once per image and
    #: the decoder once per click, so caching them apart is what makes
    #: interactive segmentation feel instant.
    files: List[ModelFile] = field(default_factory=list)
    #: Other zoo keys this model needs in order to run at all.
    requires: Tuple[str, ...] = ()
    #: Parameters the browser session needs. Lives here so swapping a model is
    #: one edit rather than a hunt through JavaScript.
    client: Dict[str, Any] = field(default_factory=dict)
    #: Where the model runs: "browser", "server", or "either".
    runs_on: str = "browser"
    notes: str = ""

    @property
    def total_mb(self) -> float:
        return round(sum(f.size_mb for f in self.files), 1)

    @property
    def downloadable(self) -> bool:
        """True when this entry has files that can actually be fetched.

        An entry with no files is a documented placeholder, not a broken
        download: it names a model we know about and have not pinned.
        """
        return bool(self.files)


#: Pinned revisions. A commit, never `main`: a moving branch turns a verified
#: download into a checksum failure with no explanation the user can act on.
_MOBILE_SAM_REV = "0d3b403339b4674a82493d5e97964dd78089ddc8"
_GDINO_REV = "ff690b0a8050566c290287545bd059350f3e9096"
_SAM2_VIDEO_REV = "3b2984dd865f6e9d2cc6aed0be6a5a5c2eb352ce"

_HF = "https://huggingface.co"


def _mobile_sam() -> ModelSpec:
    return ModelSpec(
        key="mobile_sam",
        task=ModelTask.INTERACTIVE_SEGMENTATION,
        description="MobileSAM — SAM's ViT-H encoder distilled into TinyViT",
        # Upstream MobileSAM is Apache-2.0; this particular ONNX export is
        # published under MIT. Both are permissive, but they are not the same
        # licence, so the one that actually applies to the bytes we download is
        # the one recorded here.
        licence="MIT (ONNX export); upstream MobileSAM is Apache-2.0",
        commercial_use=True,
        requires=("onnxruntime",),
        client={
            "session": "SAMSession",
            "encoder": "encoder.onnx",
            "decoder": "decoder.onnx",
            "input_size": 1024,
        },
        files=[
            ModelFile(
                name="encoder.onnx",
                url=(f"{_HF}/Acly/MobileSAM/resolve/"
                     f"{_MOBILE_SAM_REV}/mobile_sam_image_encoder.onnx"),
                sha256="580f5fb648ea1062c0aabc26217aed56921985f03f0cbbd852bba81d760cc749",
                size_mb=28.2,
            ),
            ModelFile(
                name="decoder.onnx",
                url=(f"{_HF}/Acly/MobileSAM/resolve/"
                     f"{_MOBILE_SAM_REV}/sam_mask_decoder_single.onnx"),
                sha256="93915fc7c993ab9d59ab8c9ccd3bce37f7509c81ab4150a74abd4d2abbd8570d",
                size_mb=16.5,
            ),
        ],
        notes="The default. 9.66M parameters total (5M encoder) against the "
              "original SAM's 611M, at comparable mask quality. Verified: a "
              "single click produces a mask in ~1s on CPU.",
    )


def _edge_sam() -> ModelSpec:
    return ModelSpec(
        key="edge_sam",
        task=ModelTask.INTERACTIVE_SEGMENTATION,
        description="EdgeSAM — prompt-in-the-loop distillation, fastest on-device",
        licence="NTU S-Lab License 1.0 — NON-COMMERCIAL use only",
        commercial_use=False,
        requires=("onnxruntime",),
        files=[],
        notes="Fastest of the three on low-end hardware, but the licence permits "
              "redistribution and use 'for non-commercial purpose' only; "
              "commercial use requires contacting the authors. Check this "
              "against your project before annotating a dataset you intend "
              "to publish or sell.",
    )


def _sam2_hiera_tiny() -> ModelSpec:
    return ModelSpec(
        key="sam2_hiera_tiny",
        task=ModelTask.INTERACTIVE_SEGMENTATION,
        description="SAM 2 (Hiera tiny) — single-image path only",
        licence="Apache-2.0",
        commercial_use=True,
        requires=("onnxruntime",),
        files=[],
        notes="The single-image half of SAM 2. For tracking across frames use "
              "sam2_video_tiny, which is the export that also carries the "
              "memory modules.",
    )


def _sam2_video_tiny() -> ModelSpec:
    """SAM 2.1 tiny WITH the memory modules — real video tracking.

    Every earlier survey of SAM 2 ONNX exports (onnx-community, SharpAI,
    okaris, Suhas-G) found only `vision_encoder` + `prompt_encoder_mask_decoder`
    — SAM 2's single-image path. Without `memory_encoder` and
    `memory_attention` there is no memory bank, and without a memory bank there
    is no tracking, only re-prompting. This export carries all five graphs.
    """
    base = (f"{_HF}/square-zero-labs/sam2.1-tiny-video-onnx/resolve/"
            f"{_SAM2_VIDEO_REV}")
    return ModelSpec(
        key="sam2_video_tiny",
        task=ModelTask.VIDEO_TRACKING,
        description="SAM 2.1 tiny (video) — memory-based mask tracking",
        licence="Apache-2.0",
        commercial_use=True,
        requires=("onnxruntime",),
        client={
            "session": "SAM2VideoSession",
            "vision_encoder": "vision_encoder.onnx",
            "mask_decoder": "mask_decoder.onnx",
            "memory_encoder": "memory_encoder.onnx",
            "memory_attention": "memory_attention.onnx",
            "pointer_tpos": "pointer_tpos.onnx",
            "constants": "constants.json",
            "input_size": 1024,
            # How many past frames the memory bank keeps. SAM 2's own default
            # is 7 (6 recent + the conditioning frame); larger costs linearly
            # in memory-attention time per frame.
            "memory_frames": 7,
        },
        files=[
            ModelFile(name="vision_encoder.onnx",
                      url=f"{base}/onnx/vision_encoder.onnx",
                      sha256="aa7a8542942f042e235a993a1ab0ccf5f049918500577802a7f10ec1b39bb873",
                      size_mb=128.1),
            ModelFile(name="mask_decoder.onnx",
                      url=f"{base}/onnx/mask_decoder.onnx",
                      sha256="0461896de3db00936fe1643506f129d71cb6d5d2ae15754811756b7ea1b070c6",
                      size_mb=17.0),
            ModelFile(name="memory_encoder.onnx",
                      url=f"{base}/onnx/memory_encoder.onnx",
                      sha256="580d246c109de88838f600ba7c1c0d03d1fe267f7641b06f8c88c5f0dc5834cd",
                      size_mb=5.4),
            ModelFile(name="memory_attention.onnx",
                      url=f"{base}/onnx/memory_attention.onnx",
                      sha256="791e648ce8f5ef91ad00ba06e83066ff261ae5a645f0b042b4f46a89fd054baf",
                      size_mb=30.8),
            ModelFile(name="pointer_tpos.onnx",
                      url=f"{base}/onnx/pointer_tpos.onnx",
                      sha256="7e71df1d75dba09bc18dd4ae745c2a2cceebdd14d84eadea2fe65d0205f101fc",
                      size_mb=0.1),
            ModelFile(name="constants.json",
                      url=f"{base}/constants.json",
                      sha256="172edc70e892aab0aef6caedf97b8e4091fbf6c5d26dac5fd9ea69d093d927d3",
                      size_mb=0.01),
        ],
        notes="Prompt one frame, track through the rest. Occlusion is handled "
              "in-graph: frames where the object is hidden come back marked "
              "rather than guessed.",
    )


def _grounding_dino_tiny() -> ModelSpec:
    """Text in, boxes out. The permissively-licensed route to text prompting.

    SAM 3 does text-to-mask in one model, but it is ~3.5 GB and carries Meta's
    custom licence. Grounding DINO is Apache-2.0 and small enough to run in the
    browser, and its boxes feed the SAM decoder we already ship — which is what
    turns "text in, boxes out" into "text in, masks out" with no new weights.
    """
    base = f"{_HF}/onnx-community/grounding-dino-tiny-ONNX/resolve/{_GDINO_REV}"
    return ModelSpec(
        key="grounding_dino_tiny",
        task=ModelTask.TEXT_DETECTION,
        description="Grounding DINO tiny — open-vocabulary detection from text",
        licence="Apache-2.0",
        commercial_use=True,
        requires=("onnxruntime",),
        client={
            "session": "GroundingDinoSession",
            "model": "model.onnx",
            "vocab": "vocab.txt",
            # THIS export takes a fixed 800x800, which is NOT how Grounding
            # DINO's own preprocessor works upstream (shortest edge 800, longest
            # capped at 1333). Taken from the export's own
            # preprocessor_config.json and pinned by a test, because assuming
            # the upstream convention here returns boxes at the wrong scale for
            # every non-square image.
            "input_size": 800,
            "image_mean": [0.485, 0.456, 0.406],
            "image_std": [0.229, 0.224, 0.225],
            "box_threshold": 0.3,
            "text_threshold": 0.25,
            "max_text_len": 256,
            # ORT 1.27 fails to load this graph with default optimisation:
            # a fusion pass looks for a cast node it has already folded away
            # ("Attempting to get index by a name which does not exist:
            # InsertedPrecisionFreeCast_..."). Disabling optimisation loads it
            # and runs correctly.
            "graph_optimization": "disabled",
        },
        files=[
            ModelFile(name="model.onnx",
                      url=f"{base}/onnx/model_q4f16.onnx",
                      sha256="48435b57e5a5ca01792596b9c64277260b734c10aed320109505c8e71238d6ac",
                      size_mb=144.1),
            ModelFile(name="vocab.txt",
                      url=f"{base}/vocab.txt",
                      sha256="07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
                      size_mb=0.22),
            # Not loaded by the client — kept so the tokenizer test can compare
            # our WordPiece implementation against the canonical one.
            ModelFile(name="tokenizer.json",
                      url=f"{base}/tokenizer.json",
                      sha256="d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
                      size_mb=0.68),
            ModelFile(name="preprocessor_config.json",
                      url=f"{base}/preprocessor_config.json",
                      sha256="ffc8a8a93bb1782cc6f84a37b83babb0660bb19146e52600c122335a798b503f",
                      size_mb=0.01),
        ],
        notes="Type a phrase, get every matching object boxed. q4f16 rather "
              "than int8, measured: against the 686 MB full-precision export "
              "q4f16 holds box IoU 0.97 and int8 only 0.87, at 50 MB less.",
    )


def _sam3() -> ModelSpec:
    """Text-to-mask in one model. Server-side only, and licence-gated.

    Not a browser option at any quantization: the image encoder alone is 1.8 GB
    and the language encoder another 1.6 GB. Meta's SAM License permits
    commercial use and leaves you owning your derivatives, but it carries
    acceptable-use restrictions and a same-licence redistribution term, so the
    user accepts it explicitly and we redistribute nothing.
    """
    return ModelSpec(
        key="sam3",
        task=ModelTask.TEXT_SEGMENTATION,
        description="SAM 3 — text-prompt detection and segmentation",
        licence="SAM License (Meta, 2025-11-19) — commercial use permitted, "
                "acceptable-use restrictions apply",
        licence_url="https://github.com/facebookresearch/sam3/blob/main/LICENSE",
        commercial_use=True,
        licence_ack=True,
        runs_on="server",
        files=[],
        notes="Runs as a server endpoint (`endpoint_type: sam3`), never in the "
              "browser: ~3.5 GB across three graphs. Point it at weights you "
              "already hold, or at an inference server you run. Potato "
              "redistributes no SAM 3 files.",
    )


def _edgetam() -> ModelSpec:
    """SAM 2 quality at phone speed — pending an ONNX export.

    Meta publish EdgeTAM under Apache-2.0 with a documented CoreML export and
    no ONNX one. It is listed here rather than omitted because the video
    session speaks to a task, not to a model key: when an ONNX export appears
    (or `scripts/export_onnx.py` produces one), this entry gains files and
    nothing else has to change.
    """
    return ModelSpec(
        key="edgetam",
        task=ModelTask.VIDEO_TRACKING,
        description="EdgeTAM — on-device SAM 2 variant, 22x faster",
        licence="Apache-2.0",
        commercial_use=True,
        requires=("onnxruntime",),
        client={
            "session": "SAM2VideoSession",
            "input_size": 1024,
            "memory_frames": 7,
        },
        files=[],
        notes="CVPR 2025. 22x faster than SAM 2, 16 FPS on an iPhone 15 Pro "
              "Max, by compressing the memory bank through a spatial "
              "perceiver. Upstream ships a CoreML export; no ONNX export is "
              "published yet, so there is nothing to download.",
    )


#: ONNX Runtime Web version. Pinned, and matched to the `onnxruntime` Python
#: package used to verify the model contract, so the browser and the reference
#: implementation cannot silently diverge.
ORT_VERSION = "1.27.0"


def _onnxruntime() -> ModelSpec:
    """The runtime is fetched, not vendored.

    Every other frontend dependency lives in `potato/static/vendor/` and is
    committed. This one cannot: the wasm binary alone is 13.5 MB, and
    committing it would add more to the repository than the entire rest of the
    source. Since running any model ALREADY requires downloading weights,
    putting the runtime in that same step means one command makes inference
    work and an air-gapped install copies exactly one directory.

    `ort.wasm.min.js` is the wasm-only build. The full `ort.min.js` also
    carries WebGL and WebGPU backends we do not use, at 7x the size.
    """
    cdn = f"https://cdn.jsdelivr.net/npm/onnxruntime-web@{ORT_VERSION}/dist"
    return ModelSpec(
        key="onnxruntime",
        task=ModelTask.RUNTIME,
        description=f"ONNX Runtime Web {ORT_VERSION} (wasm backend)",
        licence="MIT",
        commercial_use=True,
        files=[
            ModelFile(name="ort.wasm.min.js",
                      url=f"{cdn}/ort.wasm.min.js",
                      sha256="ea3a767b15df7dbe3d695ec9c182ca0f15b2ce7750156c6b70276e11c28997f0",
                      size_mb=0.05),
            # The wasm GLUE module. Easy to miss and fatal without it: ORT >=
            # 1.20 dynamically imports this .mjs alongside the binary, and its
            # absence surfaces as "no available backend found", which reads
            # like a browser capability problem rather than a missing file.
            ModelFile(name="ort-wasm-simd-threaded.mjs",
                      url=f"{cdn}/ort-wasm-simd-threaded.mjs",
                      sha256="0a1e718d99c41b22c21f2520ff4f9e883a6b5533856e398d21816ee8eb8185d3",
                      size_mb=0.024),
            ModelFile(name="ort-wasm-simd-threaded.wasm",
                      url=f"{cdn}/ort-wasm-simd-threaded.wasm",
                      sha256="d1ab1b94b16a65b29d710d0b587b29e7bed336827577623913479b8afe8113e6",
                      size_mb=13.48),
        ],
        notes="Threading is left OFF at runtime: multi-threaded wasm needs "
              "SharedArrayBuffer, which needs COOP/COEP headers that Potato "
              "does not set. The threaded binary runs fine single-threaded; "
              "the non-threaded build is simply not published separately.",
    )


#: The zoo. Adding a model means adding it here and writing its session class.
MODELS: Dict[str, ModelSpec] = {
    spec.key: spec
    for spec in (
        _mobile_sam(),
        _edge_sam(),
        _sam2_hiera_tiny(),
        _sam2_video_tiny(),
        _grounding_dino_tiny(),
        _sam3(),
        _edgetam(),
    )
}

#: The runtime is fetched exactly like a model but is not one, so it stays out
#: of `MODELS` — otherwise every "which model should I use?" listing has to
#: special-case it.
ORT_RUNTIME: ModelSpec = _onnxruntime()

DEFAULT_MODEL = "mobile_sam"

#: Per task, the model used when a config asks for the task rather than a
#: specific key. Every default here must be permissively licensed: a project
#: that never chose a model must never end up bound by a restrictive one.
DEFAULT_BY_TASK: Dict[ModelTask, str] = {
    ModelTask.INTERACTIVE_SEGMENTATION: "mobile_sam",
    ModelTask.TEXT_DETECTION: "grounding_dino_tiny",
    ModelTask.VIDEO_TRACKING: "sam2_video_tiny",
    ModelTask.TEXT_SEGMENTATION: "sam3",
}


def get(key: str) -> Optional[ModelSpec]:
    """One model by key, including the runtime, which is fetched the same way."""
    if key == ORT_RUNTIME.key:
        return ORT_RUNTIME
    return MODELS.get(key)


def by_task(task: ModelTask) -> List[ModelSpec]:
    """Every model that performs this task, in key order."""
    return [MODELS[k] for k in sorted(MODELS) if MODELS[k].task == task]


def default_for(task: ModelTask) -> Optional[ModelSpec]:
    key = DEFAULT_BY_TASK.get(task)
    return MODELS.get(key) if key else None


def client_config(key: str, base_url: str = "/models") -> Dict[str, Any]:
    """
    What the browser needs to run this model, ready to serialise into a page.

    Resolves file names to URLs here rather than in JavaScript, so the client
    never builds a path and the serving layout can change without touching it.
    """
    spec = get(key)
    if spec is None:
        return {}
    root = f"{base_url.rstrip('/')}/{spec.key}"
    urls = {f.name: f"{root}/{f.name}" for f in spec.files}
    config = dict(spec.client)
    # Client entries name files; swap each for the URL that serves it. A name
    # with no matching file is left alone: it is a parameter, not a path.
    for field_name, value in list(config.items()):
        if isinstance(value, str) and value in urls:
            config[field_name] = urls[value]
    config["key"] = spec.key
    config["task"] = spec.task.value
    config["baseUrl"] = root
    return config
