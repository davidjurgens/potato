"""
SAM 3: text prompt in, detections and masks out. Server-side, user-supplied.

**Never imported at boot.** Registered through
``AIEndpointFactory.register_lazy_endpoint`` and imported only when a config
asks for ``endpoint_type: sam3``. A guarded module-level ``try: import
onnxruntime`` would still load the stack for everyone who happens to have it.

WHY THIS IS A SERVER ENDPOINT WHEN TEXT PROMPTING IS ALREADY IN THE BROWSER
---------------------------------------------------------------------------
Potato's default text-prompt path is Grounding DINO in the browser: 145 MB,
Apache-2.0, no GPU, works air-gapped, and its boxes feed the SAM decoder we
already ship. SAM 3 does the same job in one model and does it better, but:

* it is roughly **3.5 GB** across three graphs (image encoder 1.8, language
  encoder 1.6, decoder 0.1), which is not a browser download at any
  quantization;
* it is **not Apache-2.0**. Meta's SAM License permits commercial use and
  leaves you owning your derivatives, but it carries acceptable-use
  restrictions and a same-licence redistribution term.

So this exists for labs that want the better model, have somewhere to run it,
and have read the licence. Potato redistributes nothing: the config points at
weights the user already holds, or at an inference server they run.

WHAT "USER-SUPPLIED" MEANS EXACTLY
----------------------------------
Two shapes are supported and both put the licence decision with the user:

``mode: onnx``
    Three local ONNX graphs, run through onnxruntime on whatever device the
    config names.

``mode: server``
    An HTTP endpoint the user operates, given as ``base_url``. Anything
    speaking the small JSON contract below works, including a wrapper around
    the official PyTorch implementation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from potato.ai.ai_endpoint import BaseAIEndpoint, ModelCapabilities

logger = logging.getLogger(__name__)

#: Printed wherever this endpoint refuses to run for licence reasons. Short on
#: purpose: the full text is Meta's, and paraphrasing a licence is how people
#: end up believing something it does not say.
LICENCE_NOTE = (
    "SAM 3 is distributed under Meta's SAM License (2025-11-19), not Apache "
    "2.0. Commercial use is permitted and you own your derivative works, but "
    "acceptable-use restrictions apply and redistribution must carry the same "
    "licence. Read it at "
    "https://github.com/facebookresearch/sam3/blob/main/LICENSE"
)


class SAM3Endpoint(BaseAIEndpoint):
    """Open-vocabulary detection and segmentation from a text prompt."""

    #: Graph file names inside `model_dir`, in the order they run.
    GRAPHS = ("sam3_image_encoder.onnx", "sam3_language_encoder.onnx",
              "sam3_decoder.onnx")

    def __init__(self, config: Optional[Dict[str, Any]] = None, **kwargs):
        cfg = config or {}
        # Assigned BEFORE super().__init__, which calls _get_default_model()
        # during construction.
        self.mode = (cfg.get("mode") or "onnx").lower()
        self.model_dir = cfg.get("model_dir") or cfg.get("model_path")
        self.base_url = (cfg.get("base_url") or "").rstrip("/")
        self.device = cfg.get("device", "cpu")
        self.box_threshold = float(cfg.get("box_threshold", 0.3))
        self.text_threshold = float(cfg.get("text_threshold", 0.25))
        self._sessions: Dict[str, Any] = {}

        super().__init__(cfg, **kwargs)

        if self.mode == "onnx" and not self.model_dir:
            raise ValueError(
                "The sam3 endpoint in `onnx` mode needs `model_dir` pointing "
                "at the three SAM 3 graphs. Potato does not bundle or download "
                f"them.\n{LICENCE_NOTE}"
            )
        if self.mode == "server" and not self.base_url:
            raise ValueError(
                "The sam3 endpoint in `server` mode needs `base_url` for the "
                "inference server you run."
            )
        if self.mode not in ("onnx", "server"):
            raise ValueError(
                f"Unknown sam3 mode {self.mode!r}. Use 'onnx' for local graphs "
                f"or 'server' for an endpoint you operate.")

    def _initialize_client(self) -> None:
        """Nothing to connect to; graphs load on first real use."""
        return None

    def _get_default_model(self) -> str:
        return "sam3"

    def query(self, prompt: str, output_format=None):
        """
        Not a text-generation endpoint.

        SAM 3 takes a phrase and returns geometry, so the generic text path
        does not apply. Raising beats returning an empty result that reads as
        "the model found nothing".
        """
        raise NotImplementedError(
            "SAM 3 returns geometry, not text; call detect() with a phrase.")

    def get_capabilities(self) -> ModelCapabilities:
        """Both boxes and masks, from a phrase — the reason to run it at all."""
        return ModelCapabilities(
            vision_input=True,
            bounding_box_output=True,
            mask_output=True,
            interactive_segmentation=True,
            text_prompt_segmentation=True,
        )

    # ------------------------------------------------------------- loading

    def _load_onnx(self):
        from pathlib import Path

        if self._sessions:
            return self._sessions
        try:
            import onnxruntime  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError(
                "The sam3 endpoint needs onnxruntime:  pip install onnxruntime"
            ) from exc

        root = Path(self.model_dir)
        missing = [name for name in self.GRAPHS if not (root / name).exists()]
        if missing:
            raise RuntimeError(
                f"SAM 3 graphs missing from {root}: {', '.join(missing)}. "
                f"Export or download them yourself — Potato redistributes no "
                f"SAM 3 files.\n{LICENCE_NOTE}")

        providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                     if self.device.startswith("cuda")
                     else ["CPUExecutionProvider"])
        for name in self.GRAPHS:
            key = name.replace("sam3_", "").replace(".onnx", "")
            self._sessions[key] = onnxruntime.InferenceSession(
                str(root / name), providers=providers)
        return self._sessions

    # ------------------------------------------------------------ inference

    def detect(self, image, phrases: List[str], **options) -> List[Dict[str, Any]]:
        """
        Find everything matching `phrases`.

        Returns detections in Potato's client contract — normalized boxes and,
        where the model produced one, an RLE mask:

            [{"label": "traffic cone", "confidence": 0.71,
              "bbox": {"x": .., "y": .., "width": .., "height": ..},
              "rle": {"counts": [...], "size": [h, w]}}]
        """
        if not phrases:
            return []
        if self.mode == "server":
            return self._detect_remote(image, phrases, **options)
        return self._detect_onnx(image, phrases, **options)

    def _detect_remote(self, image, phrases, **options):
        """Ask the user's own inference server.

        The contract is deliberately small — an image, some phrases, two
        thresholds — so that wrapping the official PyTorch implementation is an
        afternoon rather than a project.
        """
        import base64
        import io

        import requests  # noqa: PLC0415

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        payload = {
            "image": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "phrases": list(phrases),
            "box_threshold": options.get("box_threshold", self.box_threshold),
            "text_threshold": options.get("text_threshold", self.text_threshold),
        }
        response = requests.post(f"{self.base_url}/detect", json=payload,
                                 timeout=options.get("timeout", 120))
        response.raise_for_status()
        data = response.json()
        detections = data.get("detections", data if isinstance(data, list) else [])
        return [d for d in detections if isinstance(d, dict)]

    def _detect_onnx(self, image, phrases, **options):
        """Run the three local graphs.

        Left unimplemented rather than guessed. The published SAM 3 exports do
        not share one input contract, and a wrong reading of a segmentation
        model's contract returns a confident, plausible, WRONG mask — measured
        at 70-148 px of centroid error when the same mistake was made with
        SAM 1. Implementing this needs the weights in hand and a parity test
        against the PyTorch reference, exactly as `tests/unit/
        test_sam_model_pipeline.py` does for MobileSAM.
        """
        self._load_onnx()
        raise NotImplementedError(
            "Local SAM 3 ONNX inference is not implemented. The graphs load "
            "and the plumbing is tested, but the tensor contract has to be "
            "verified against real weights before it can be trusted — a wrong "
            "reading returns plausible, wrong masks. Use `mode: server` with "
            "an inference server you run, or the browser text-prompt path "
            "(Grounding DINO), which is verified end to end."
        )
