"""
The SAM ONNX contract, pinned against the real weights.

Every Jest test of the browser code mocks the runtime, and a mock accepts
anything — which is exactly how an earlier version of `sam-session.js` came to
emit two of the decoder's six required inputs and pass its whole suite. These
tests run the actual MobileSAM graphs, so the contract the JavaScript encodes
is checked against the model rather than against my reading of it.

**The measured contract** (three plausible alternatives are all wrong):

1. Resize the image so its LONGEST SIDE is 1024, preserving aspect ratio, and
   feed *that* to the encoder as HWC float in 0..255. The export normalizes and
   pads internally; it does not resize.
2. Multiply click coordinates by that same scale factor.
3. Pass `orig_im_size` as the ORIGINAL (height, width). Output masks come back
   at original resolution.

Measured errors for the wrong readings, on a non-square image with three
separated targets:

    raw original pixels                    148 px
    scale by 1024/W and 1024/H separately   70 px
    unresized image into the encoder        70 px
    THE ABOVE CONTRACT                     0.1 px

Each wrong reading still returns a confident, plausible-looking mask, which is
why this is a test and not a comment.

Skipped when the weights are absent — they are a 45 MB download, not a
checked-in fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
rt = pytest.importorskip("onnxruntime")
PIL = pytest.importorskip("PIL")

from potato.models_cli import DEFAULT_MODEL_DIR  # noqa: E402

ENCODER = DEFAULT_MODEL_DIR / "mobile_sam" / "encoder.onnx"
DECODER = DEFAULT_MODEL_DIR / "mobile_sam" / "decoder.onnx"

pytestmark = pytest.mark.skipif(
    not (ENCODER.exists() and DECODER.exists()),
    reason="MobileSAM weights not installed (potato download-models mobile_sam)")

SAM_INPUT_SIZE = 1024

#: A non-square canvas with three well-separated discs. Non-square matters:
#: on a square image, scaling by 1024/max(H,W) and by 1024/W are identical, so
#: the two hypotheses cannot be told apart.
WIDTH, HEIGHT = 480, 300
DISCS = [((90, 80), (220, 60, 60)),
         ((240, 200), (60, 200, 90)),
         ((390, 90), (230, 200, 50))]
DISC_RADIUS = 45


@pytest.fixture(scope="module")
def sessions():
    return (
        rt.InferenceSession(str(ENCODER), providers=["CPUExecutionProvider"]),
        rt.InferenceSession(str(DECODER), providers=["CPUExecutionProvider"]),
    )


@pytest.fixture(scope="module")
def scene():
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (WIDTH, HEIGHT), (40, 60, 90))
    draw = ImageDraw.Draw(image)
    for (cx, cy), colour in DISCS:
        draw.ellipse([cx - DISC_RADIUS, cy - DISC_RADIUS,
                      cx + DISC_RADIUS, cy + DISC_RADIUS], fill=colour)
    return image


def resize_longest_side(width, height):
    scale = SAM_INPUT_SIZE / max(width, height)
    return scale, int(round(width * scale)), int(round(height * scale))


@pytest.fixture(scope="module")
def embedding(sessions, scene):
    from PIL import Image

    encoder, _decoder = sessions
    scale, new_w, new_h = resize_longest_side(WIDTH, HEIGHT)
    resized = np.array(scene.resize((new_w, new_h), Image.BILINEAR),
                       dtype=np.float32)
    return encoder.run(None, {"input_image": resized})[0]


def decode(decoder, embedding, points, labels, orig_size=None):
    height, width = orig_size or (HEIGHT, WIDTH)
    return decoder.run(None, {
        "image_embeddings": embedding,
        "point_coords": np.array([points], dtype=np.float32),
        "point_labels": np.array([labels], dtype=np.float32),
        "mask_input": np.zeros((1, 1, 256, 256), dtype=np.float32),
        "has_mask_input": np.zeros(1, dtype=np.float32),
        "orig_im_size": np.array([height, width], dtype=np.float32),
    })


def mask_stats(masks):
    binary = masks[0, 0] > 0
    if not binary.any():
        return None
    ys, xs = np.nonzero(binary)
    return {
        "centroid": (xs.mean(), ys.mean()),
        "coverage": binary.sum() / binary.size,
        "pixels": int(binary.sum()),
    }


class TestModelSignature:
    def test_the_encoder_takes_hwc_with_no_batch_dimension(self, sessions):
        """
        The classic SAM encoder takes [1, 3, 1024, 1024]. This export does not,
        and building the classic tensor throws a rank error.
        """
        encoder, _ = sessions
        inputs = encoder.get_inputs()
        assert len(inputs) == 1
        assert inputs[0].name == "input_image"
        assert len(inputs[0].shape) == 3, "HWC, no batch dimension"
        assert inputs[0].shape[2] == 3

    def test_the_decoder_declares_all_six_inputs(self, sessions):
        """Omitting any of them throws; an earlier draft emitted two."""
        _, decoder = sessions
        names = {i.name for i in decoder.get_inputs()}
        assert names == {
            "image_embeddings", "point_coords", "point_labels",
            "mask_input", "has_mask_input", "orig_im_size",
        }

    def test_point_labels_are_float_not_int(self, sessions):
        """An Int32 tensor here is a type error, not a silent coercion."""
        _, decoder = sessions
        labels = next(i for i in decoder.get_inputs() if i.name == "point_labels")
        assert labels.type == "tensor(float)"

    def test_has_mask_input_and_orig_im_size_are_float_too(self, sessions):
        _, decoder = sessions
        by_name = {i.name: i.type for i in decoder.get_inputs()}
        assert by_name["has_mask_input"] == "tensor(float)"
        assert by_name["orig_im_size"] == "tensor(float)"

    def test_the_embedding_is_the_expected_shape(self, embedding):
        assert embedding.shape == (1, 256, 64, 64)


class TestTheCorrectPipeline:
    def test_a_click_lands_on_the_thing_that_was_clicked(self, sessions,
                                                          embedding):
        """
        The whole contract in one assertion. A disc is 90px across, so an error
        under ~10px means the mask is genuinely on the target rather than
        coincidentally overlapping it.
        """
        _, decoder = sessions
        scale, _, _ = resize_longest_side(WIDTH, HEIGHT)

        for (cx, cy), _colour in DISCS:
            masks, _iou, _low = decode(
                decoder, embedding, [[cx * scale, cy * scale]], [1.0])
            stats = mask_stats(masks)
            assert stats is not None, f"click at {(cx, cy)} produced no mask"
            error = ((stats["centroid"][0] - cx) ** 2
                     + (stats["centroid"][1] - cy) ** 2) ** 0.5
            assert error < 10, (
                f"click at {(cx, cy)} produced a mask centred at "
                f"{stats['centroid']} — {error:.1f}px away")

    def test_the_mask_is_the_size_of_the_target(self, sessions, embedding):
        """
        Catches the failure where the model returns the background instead:
        that scores a good centroid but covers 78% of the frame.
        """
        _, decoder = sessions
        scale, _, _ = resize_longest_side(WIDTH, HEIGHT)
        expected = (3.14159 * DISC_RADIUS ** 2) / (WIDTH * HEIGHT)

        (cx, cy), _ = DISCS[0]
        masks, _iou, _low = decode(
            decoder, embedding, [[cx * scale, cy * scale]], [1.0])
        coverage = mask_stats(masks)["coverage"]
        assert abs(coverage - expected) < 0.02, (
            f"mask covers {coverage:.1%}, disc is {expected:.1%}")

    def test_masks_come_back_at_original_resolution(self, sessions, embedding):
        _, decoder = sessions
        scale, _, _ = resize_longest_side(WIDTH, HEIGHT)
        masks, _iou, _low = decode(decoder, embedding, [[100 * scale, 100 * scale]], [1.0])
        assert masks.shape[-2:] == (HEIGHT, WIDTH)

    def test_the_low_res_mask_is_256_square_for_refinement(self, sessions,
                                                           embedding):
        _, decoder = sessions
        scale, _, _ = resize_longest_side(WIDTH, HEIGHT)
        _masks, _iou, low = decode(decoder, embedding,
                                   [[100 * scale, 100 * scale]], [1.0])
        assert low.shape == (1, 1, 256, 256)


class TestTheWrongReadingsAreActuallyWrong:
    """
    Controls. Without these, the test above could pass for the wrong reason and
    nobody would know the alternatives had been ruled out by measurement.
    """

    def test_raw_original_pixels_miss_the_target(self, sessions, embedding):
        _, decoder = sessions
        (cx, cy), _ = DISCS[2]
        masks, _iou, _low = decode(decoder, embedding, [[cx, cy]], [1.0])
        stats = mask_stats(masks)
        if stats is None:
            return  # an empty mask is also "wrong", and unambiguously so
        error = ((stats["centroid"][0] - cx) ** 2
                 + (stats["centroid"][1] - cy) ** 2) ** 0.5
        assert error > 50, (
            "unscaled coordinates should be badly wrong; if this now passes, "
            "the export changed and the whole contract needs re-measuring")

    def test_an_unresized_encoder_input_misses_the_target(self, sessions, scene):
        """The encoder does not resize; feeding it the original is wrong."""
        encoder, decoder = sessions
        raw = np.array(scene, dtype=np.float32)
        bad_embedding = encoder.run(None, {"input_image": raw})[0]

        scale, _, _ = resize_longest_side(WIDTH, HEIGHT)
        (cx, cy), _ = DISCS[2]
        masks, _iou, _low = decode(decoder, bad_embedding,
                                   [[cx * scale, cy * scale]], [1.0])
        stats = mask_stats(masks)
        if stats is None:
            return
        error = ((stats["centroid"][0] - cx) ** 2
                 + (stats["centroid"][1] - cy) ** 2) ** 0.5
        assert error > 30, (
            "an unresized encoder input should be wrong; if it is not, the "
            "export now resizes internally and the JS can be simplified")


class TestRefinement:
    def test_a_negative_click_excludes_what_it_lands_on(self, sessions,
                                                        embedding):
        """
        Negative points are what make click-to-segment correctable rather than
        take-it-or-leave-it.

        Tested on two SEPARATE discs, not on one disc's edge: a negative point
        just inside a boundary is genuinely ambiguous to the model, and an
        earlier version of this test asserted on that ambiguity and failed by
        six pixels — measuring noise, not behaviour.
        """
        _, decoder = sessions
        scale, _, _ = resize_longest_side(WIDTH, HEIGHT)
        (ax, ay), _ = DISCS[0]
        (bx, by), _ = DISCS[1]

        both, _iou, _low = decode(
            decoder, embedding,
            [[ax * scale, ay * scale], [bx * scale, by * scale]], [1.0, 1.0])
        both_stats = mask_stats(both)
        assert both_stats is not None

        excluded, _iou2, _low2 = decode(
            decoder, embedding,
            [[ax * scale, ay * scale], [bx * scale, by * scale]], [1.0, 0.0])
        after = mask_stats(excluded)
        assert after is not None

        # With B excluded, the mask must sit on A rather than between them.
        distance_to_a = ((after["centroid"][0] - ax) ** 2
                         + (after["centroid"][1] - ay) ** 2) ** 0.5
        distance_to_b = ((after["centroid"][0] - bx) ** 2
                         + (after["centroid"][1] - by) ** 2) ** 0.5
        assert distance_to_a < distance_to_b, (
            f"negative point on disc B left the mask nearer B "
            f"({distance_to_b:.0f}px) than A ({distance_to_a:.0f}px)")

    def test_feeding_back_the_low_res_mask_is_accepted(self, sessions,
                                                        embedding):
        """The iterative-refinement path the decoder's mask_input exists for."""
        _, decoder = sessions
        scale, _, _ = resize_longest_side(WIDTH, HEIGHT)
        (cx, cy), _ = DISCS[1]

        _masks, _iou, low = decode(
            decoder, embedding, [[cx * scale, cy * scale]], [1.0])

        refined = decoder.run(None, {
            "image_embeddings": embedding,
            "point_coords": np.array([[[cx * scale, cy * scale]]], dtype=np.float32),
            "point_labels": np.array([[1.0]], dtype=np.float32),
            "mask_input": low.astype(np.float32),
            "has_mask_input": np.ones(1, dtype=np.float32),
            "orig_im_size": np.array([HEIGHT, WIDTH], dtype=np.float32),
        })
        stats = mask_stats(refined[0])
        assert stats is not None
        error = ((stats["centroid"][0] - cx) ** 2
                 + (stats["centroid"][1] - cy) ** 2) ** 0.5
        assert error < 15, "refinement should keep the mask on the target"


class TestBoxPrompts:
    def test_a_box_prompt_segments_what_it_encloses(self, sessions, embedding):
        """Labels 2 and 3 are SAM's box-corner sentinels, not extra points."""
        _, decoder = sessions
        scale, _, _ = resize_longest_side(WIDTH, HEIGHT)
        (cx, cy), _ = DISCS[1]
        x0, y0 = cx - DISC_RADIUS - 5, cy - DISC_RADIUS - 5
        x1, y1 = cx + DISC_RADIUS + 5, cy + DISC_RADIUS + 5

        masks, _iou, _low = decode(
            decoder, embedding,
            [[x0 * scale, y0 * scale], [x1 * scale, y1 * scale]],
            [2.0, 3.0])
        stats = mask_stats(masks)
        assert stats is not None
        error = ((stats["centroid"][0] - cx) ** 2
                 + (stats["centroid"][1] - cy) ** 2) ** 0.5
        assert error < 15, f"box prompt centred at {stats['centroid']}"


class TestJavaScriptAgreement:
    """
    The JS preprocessing must compute the same geometry as the Python above.
    Reading the constants out of the file is crude but catches the case that
    matters: someone 'simplifying' the scale factor to 1024/width.
    """

    @pytest.fixture(scope="class")
    def js(self):
        return Path("potato/static/segmentation/sam-preprocess.js").read_text()

    def test_it_scales_by_the_longest_side(self, js):
        assert "Math.max(width, height)" in js
        assert "SAM_INPUT_SIZE / longest" in js

    def test_it_declares_the_same_input_size(self, js):
        assert "SAM_INPUT_SIZE = 1024" in js

    def test_it_sends_height_first(self, js):
        assert "geometry.origHeight, geometry.origWidth" in js

    def test_it_builds_float_labels(self, js):
        assert "Float32Array.from(labels)" in js

    def test_it_emits_hwc_without_a_batch_dimension(self, js):
        assert "[target.height, target.width, 3]" in js
