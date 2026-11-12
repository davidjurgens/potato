"""
Segmentation capability plumbing (Wave 2 foundation).

Two things are pinned here, and the second matters more than it looks:

1. **A detector is not a segmenter.** ``bounding_box_output`` must not imply
   ``mask_output``. Without a separate flag the segment button would appear for
   every YOLO-style endpoint and then return nothing usable.

2. **Registering the SAM endpoint must not weigh down boot.** A guarded
   module-level ``try: import torch`` still loads the whole ML stack whenever
   torch is present. Potato has been bitten by exactly this before, which is
   why every ML dependency goes through ``register_lazy_endpoint`` and is
   probed with ``has_endpoint()``, never ``in _endpoints``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from potato.ai.ai_endpoint import AIEndpointFactory, ModelCapabilities


class TestCapabilityGating:
    def test_a_box_detector_does_not_offer_segmentation(self):
        detector = ModelCapabilities(vision_input=True, bounding_box_output=True)
        assert detector.supports_assistant("detection", True) is True
        assert detector.supports_assistant("segment", True) is False

    def test_a_segmenter_offers_segmentation(self):
        seg = ModelCapabilities(vision_input=True, mask_output=True)
        assert seg.supports_assistant("segment", True) is True

    def test_segmentation_requires_vision(self):
        """A text model with mask_output set is a config error, not a segmenter."""
        odd = ModelCapabilities(mask_output=True, vision_input=False)
        assert odd.supports_assistant("segment", True) is False

    def test_both_spellings_are_accepted(self):
        seg = ModelCapabilities(vision_input=True, mask_output=True)
        assert seg.supports_assistant("segmentation", True) is True

    def test_defaults_are_off(self):
        blank = ModelCapabilities()
        assert blank.mask_output is False
        assert blank.text_prompt_segmentation is False
        assert blank.interactive_segmentation is False

    def test_existing_assistants_are_unaffected(self):
        """The regression risk: new flags must not change old gating."""
        text = ModelCapabilities(text_generation=True, keyword_extraction=True)
        assert text.supports_assistant("hint", False) is True
        assert text.supports_assistant("keyword", False) is True
        assert text.supports_assistant("detection", True) is False


class TestLazyRegistration:
    def test_sam_is_a_known_endpoint_type(self):
        assert AIEndpointFactory.has_endpoint("sam")

    def test_importing_potato_does_not_import_torch(self):
        """
        Run in a FRESH interpreter: this process may already have torch loaded
        via some other test, which would make an in-process check vacuous.
        """
        code = (
            "import sys; import potato.ai.ai_endpoint as e; "
            "assert e.AIEndpointFactory.has_endpoint('sam'); "
            "print(int('torch' in sys.modules), "
            "int('potato.ai.sam_endpoint' in sys.modules))"
        )
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr
        torch_loaded, module_loaded = out.stdout.split()
        assert torch_loaded == "0", "torch was imported at boot"
        assert module_loaded == "0", "sam_endpoint was imported at boot"

    def test_the_endpoint_module_itself_has_no_ml_imports_at_module_level(self):
        import ast
        import pathlib

        src = pathlib.Path("potato/ai/sam_endpoint.py").read_text()
        tree = ast.parse(src)
        banned = {"torch", "torchvision", "segment_anything", "numpy", "cv2"}
        for node in tree.body:  # module level only
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                name = (getattr(node, "module", None) or "").split(".")[0]
                names = {name} | {a.name.split(".")[0]
                                  for a in getattr(node, "names", [])}
                assert not (names & banned), (
                    f"{names & banned} imported at module level in sam_endpoint")


class TestEndpointContract:
    def test_missing_checkpoint_is_an_explicit_error(self):
        """Never silently download weights whose licence we have not checked."""
        from potato.ai.sam_endpoint import SAMEndpoint

        with pytest.raises(ValueError, match="checkpoint"):
            SAMEndpoint({})

    def test_declares_masks_but_not_boxes(self):
        """SAM segments what it is pointed at; it does not enumerate objects."""
        from potato.ai.sam_endpoint import SAMEndpoint

        caps = SAMEndpoint({"checkpoint": "/nonexistent.pth"}).get_capabilities()
        assert caps.mask_output is True
        assert caps.interactive_segmentation is True
        assert caps.bounding_box_output is False
        assert caps.supports_assistant("segment", True) is True
        assert caps.supports_assistant("detection", True) is False


class TestOutputFormat:
    def test_segmentation_format_is_registered(self):
        from potato.ai.prompt.models_module import CLASS_REGISTRY

        assert "visual_segmentation" in CLASS_REGISTRY

    def test_masks_use_the_rle_contract_the_exporters_read(self):
        """
        Not base64 PNG, not a polygon: the same {counts, size:[h, w]} shape
        `cv_utils.normalize_annotation_object` already reads, so an accepted
        mask reaches every exporter with no conversion step to get wrong.
        """
        from potato.ai.prompt.models_module import VisualSegmentationFormat
        from potato.export.cv_utils import normalize_annotation_object

        parsed = VisualSegmentationFormat(masks=[{
            "label": "road",
            "rle": {"counts": [0, 5, 95], "size": [10, 10]},
            "confidence": 0.9,
        }])
        mask = parsed.masks[0]

        canonical = normalize_annotation_object(
            {"type": "mask", "label": mask.label, "rle": mask.rle}, 10, 10)
        assert canonical is not None, "exporters cannot read the model's output"
        assert canonical["rle"] == mask.rle

    def test_confidence_is_optional(self):
        from potato.ai.prompt.models_module import VisualSegmentationFormat

        parsed = VisualSegmentationFormat(masks=[{
            "label": "road", "rle": {"counts": [0, 1], "size": [1, 1]},
        }])
        assert parsed.masks[0].confidence is None
