"""
The real ONNX model's input/output contract.

Everything else in the SAM tests mocks the runtime, and a mock accepts anything.
That is exactly how ``_promptTensors`` came to emit only ``point_coords`` and
``point_labels`` while the real decoder declares **six** required inputs — code
that passed a full test suite and would have thrown on the very first click.

These tests run against the actual downloaded weights when present and skip
otherwise, so CI without a 45MB download stays green, while a machine that has
run ``potato download-models`` gets the contract checked for real.

The recorded signature below is the load-bearing part: it fails if a future
model swap changes the interface, and it documents what the browser session has
to send.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from potato import models_cli

SESSION_JS = Path("potato/static/segmentation/sam-session.js")
#: The tensor contract moved OUT of sam-session.js into its own module, so
#: that the part which cannot be guessed lives in one file with its own
#: tests. The guard follows it rather than asserting on the orchestration.
PREPROCESS_JS = Path("potato/static/segmentation/sam-preprocess.js")

#: Verified against Acly/MobileSAM @ 0d3b4033 with onnxruntime 1.27.
EXPECTED_ENCODER_INPUTS = {"input_image"}
EXPECTED_ENCODER_OUTPUTS = {"image_embeddings"}
EXPECTED_DECODER_INPUTS = {
    "image_embeddings", "point_coords", "point_labels",
    "mask_input", "has_mask_input", "orig_im_size",
}
EXPECTED_DECODER_OUTPUTS = {"masks", "iou_predictions", "low_res_masks"}


def model_path(name):
    return models_cli.model_dir() / "mobile_sam" / name


requires_model = pytest.mark.skipif(
    not model_path("encoder.onnx").exists()
    or not model_path("decoder.onnx").exists(),
    reason="run `potato download-models mobile_sam` to check the real contract",
)


@pytest.fixture(scope="module")
def sessions():
    ort = pytest.importorskip("onnxruntime")
    return (
        ort.InferenceSession(str(model_path("encoder.onnx")),
                             providers=["CPUExecutionProvider"]),
        ort.InferenceSession(str(model_path("decoder.onnx")),
                             providers=["CPUExecutionProvider"]),
    )


class TestRegistryPointsAtRealFiles:
    def test_the_default_model_has_a_configured_download(self):
        assert models_cli.available("mobile_sam")

    def test_it_ships_a_separate_encoder_and_decoder(self):
        """The split is what makes clicking feel instant rather than like a request."""
        names = {f.name for f in models_cli.MODELS["mobile_sam"].files}
        assert names == {"encoder.onnx", "decoder.onnx"}

    def test_urls_are_pinned_to_a_commit_not_a_branch(self):
        """A moving branch turns a verified download into an unexplained failure."""
        for f in models_cli.MODELS["mobile_sam"].files:
            assert "/resolve/main/" not in f.url, f"{f.name} is pinned to a branch"
            assert re.search(r"/resolve/[0-9a-f]{40}/", f.url), f.url

    def test_every_file_declares_a_full_sha256(self):
        for f in models_cli.MODELS["mobile_sam"].files:
            assert re.fullmatch(r"[0-9a-f]{64}", f.sha256), f.name


@requires_model
class TestRealModelSignature:
    def test_encoder_signature(self, sessions):
        encoder, _ = sessions
        assert {i.name for i in encoder.get_inputs()} == EXPECTED_ENCODER_INPUTS
        assert {o.name for o in encoder.get_outputs()} == EXPECTED_ENCODER_OUTPUTS

    def test_decoder_requires_six_inputs(self, sessions):
        """The finding the mocks hid."""
        _, decoder = sessions
        assert {i.name for i in decoder.get_inputs()} == EXPECTED_DECODER_INPUTS

    def test_decoder_outputs(self, sessions):
        _, decoder = sessions
        assert {o.name for o in decoder.get_outputs()} == EXPECTED_DECODER_OUTPUTS

    def test_the_encoder_takes_raw_hwc_pixels(self, sessions):
        """
        Not NCHW and not pre-normalized: this export resizes and normalizes
        internally, which is why the browser can hand it canvas pixels directly.
        """
        encoder, _ = sessions
        shape = encoder.get_inputs()[0].shape
        assert len(shape) == 3 and shape[-1] == 3, shape

    def test_embedding_shape_is_what_the_decoder_expects(self, sessions):
        encoder, decoder = sessions
        produced = encoder.get_outputs()[0].shape
        consumed = next(i for i in decoder.get_inputs()
                        if i.name == "image_embeddings").shape
        assert produced == consumed == [1, 256, 64, 64]


@requires_model
class TestRealInference:
    def test_a_single_click_produces_a_mask(self, sessions):
        numpy = pytest.importorskip("numpy")
        Image = pytest.importorskip("PIL.Image")

        encoder, decoder = sessions
        img = Image.open("examples/image/coco-import/media/street.jpg").convert("RGB")
        w, h = img.size

        embedding = encoder.run(
            None, {"input_image": numpy.array(img).astype(numpy.float32)})[0]
        masks, iou, low_res = decoder.run(None, {
            "image_embeddings": embedding,
            "point_coords": numpy.array([[[w * 0.4, h * 0.5]]], dtype=numpy.float32),
            "point_labels": numpy.array([[1]], dtype=numpy.float32),
            "mask_input": numpy.zeros((1, 1, 256, 256), dtype=numpy.float32),
            "has_mask_input": numpy.zeros(1, dtype=numpy.float32),
            "orig_im_size": numpy.array([h, w], dtype=numpy.float32),
        })

        assert masks.shape[-2:] == (h, w), "mask is not the image's size"
        positive = int((masks[0, 0] > 0).sum())
        # A real object, not the whole frame and not nothing.
        assert 0 < positive < masks[0, 0].size
        assert low_res.shape[-2:] == (256, 256), "refinement input shape changed"

    def test_orig_im_size_is_height_first(self, sessions):
        """
        Swapping it yields a silently TRANSPOSED mask rather than an error,
        which is why the browser session has an explicit test for the order.
        """
        numpy = pytest.importorskip("numpy")
        Image = pytest.importorskip("PIL.Image")

        encoder, decoder = sessions
        img = Image.open("examples/image/coco-import/media/street.jpg").convert("RGB")
        w, h = img.size
        assert w != h, "fixture must be non-square for this to prove anything"

        embedding = encoder.run(
            None, {"input_image": numpy.array(img).astype(numpy.float32)})[0]

        def run(size):
            return decoder.run(None, {
                "image_embeddings": embedding,
                "point_coords": numpy.array([[[w / 2, h / 2]]], dtype=numpy.float32),
                "point_labels": numpy.array([[1]], dtype=numpy.float32),
                "mask_input": numpy.zeros((1, 1, 256, 256), dtype=numpy.float32),
                "has_mask_input": numpy.zeros(1, dtype=numpy.float32),
                "orig_im_size": numpy.array(size, dtype=numpy.float32),
            })[0]

        assert run([h, w]).shape[-2:] == (h, w)
        assert run([w, h]).shape[-2:] == (w, h), "the wrong order is silently accepted"


class TestBrowserSessionMatchesTheContract:
    """The JS must send what the model declares; the mocks cannot check this."""

    @pytest.fixture(scope="class")
    def js(self):
        # Both files: the session orchestrates, the preprocessor builds the
        # tensors, and the contract must be satisfied by the pair.
        return SESSION_JS.read_text() + "\n" + PREPROCESS_JS.read_text()

    @pytest.mark.parametrize("name", sorted(EXPECTED_DECODER_INPUTS - {"image_embeddings"}))
    def test_the_session_emits_each_required_decoder_input(self, js, name):
        assert name in js, (
            f"the segmentation client never mentions '{name}', which the real "
            f"decoder requires; a decode would throw on the first click")

    def test_the_session_documents_the_height_first_order(self, js):
        assert "HEIGHT FIRST" in js or "height, width" in js
