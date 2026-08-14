"""
Segment-Anything-class interactive segmentation, as an optional server endpoint.

**This module is never imported at boot.** It is registered through
``AIEndpointFactory.register_lazy_endpoint`` and imported only when a config
actually asks for ``type: sam``. That is not a style preference: a guarded
module-level ``try: import torch`` still loads the whole ML stack whenever torch
happens to be installed, which has previously added seconds to every Potato
start-up on machines that were never going to use it.

**Posture.** The default segmentation path in Potato is browser-side (ONNX
Runtime Web), so ``pip install potato`` gives working segmentation with no GPU
and no new Python dependency, and keeps working air-gapped. This endpoint exists
for labs that have a GPU and want a larger model than a browser can carry.

**Weights are user-supplied.** Nothing here downloads or bundles model weights.
SAM-family licensing varies by release and is not uniformly permissive, so the
config points at a checkpoint the user already has, and a missing one is an
explicit error rather than a silent download.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from potato.ai.ai_endpoint import BaseAIEndpoint, ModelCapabilities

logger = logging.getLogger(__name__)


class SAMEndpoint(BaseAIEndpoint):
    """Interactive segmentation from click, box, or (model permitting) text prompts."""

    #: Smallest SAM backbone; the sane default for a CPU box.
    DEFAULT_MODEL_TYPE = "vit_b"

    def __init__(self, config: Optional[Dict[str, Any]] = None, **kwargs):
        cfg = config or {}
        # Assigned BEFORE super().__init__, which calls _get_default_model()
        # during construction — reading self.model_type there would otherwise
        # raise AttributeError before this line ever ran.
        self.checkpoint = cfg.get("checkpoint") or cfg.get("model_path")
        self.model_type = cfg.get("model_type", self.DEFAULT_MODEL_TYPE)
        self.device = cfg.get("device", "cpu")
        self._predictor = None

        super().__init__(cfg, **kwargs)

        if not self.checkpoint:
            raise ValueError(
                "SAM endpoint requires a `checkpoint` path to a model file. "
                "Potato does not bundle or download SAM weights: licensing "
                "varies by release, so the checkpoint must be one you already "
                "hold. Set ai_endpoint.checkpoint in your config."
            )

    def _initialize_client(self) -> None:
        """Nothing to connect to. The model loads lazily in :meth:`_load`."""
        return None

    def _get_default_model(self) -> str:
        return self.model_type

    def query(self, prompt: str, output_format=None):
        """
        Not a prompt-driven endpoint.

        SAM takes geometric prompts (clicks, boxes), not text, so the generic
        text query path does not apply. Raising here is better than returning
        an empty result that reads as "the model found nothing".
        """
        raise NotImplementedError(
            "SAM is a segmentation endpoint; use segment() with point or box "
            "prompts rather than the text query path."
        )

    def get_capabilities(self) -> ModelCapabilities:
        """
        Masks yes, boxes no.

        ``bounding_box_output`` stays False on purpose. SAM segments what it is
        pointed at; it does not enumerate objects, so exposing the *detection*
        assistant would offer a button that returns nothing.
        """
        return ModelCapabilities(
            vision_input=True,
            mask_output=True,
            interactive_segmentation=True,
            text_prompt_segmentation=False,
        )

    def _load(self):
        """Import torch and build the predictor. Called on first real use only."""
        if self._predictor is not None:
            return self._predictor
        try:
            from segment_anything import SamPredictor, sam_model_registry
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "The SAM endpoint needs the optional vision extra: "
                "pip install 'potato[vision]'"
            ) from exc

        model = sam_model_registry[self.model_type](checkpoint=self.checkpoint)
        model.to(device=self.device)
        self._predictor = SamPredictor(model)
        return self._predictor

    def segment(self, image, prompts: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Return masks for the given prompts, in the client's RLE contract.

        ``prompts`` accepts ``points`` ([[x, y, label], ...] where label 1 is
        foreground and 0 background) and ``box`` ([x, y, w, h]), both in
        ABSOLUTE pixels.
        """
        raise NotImplementedError(
            "Server-side SAM inference is not implemented yet. The supported "
            "path today is browser-side segmentation; this class exists so the "
            "capability plumbing and lazy registration are in place and tested."
        )
