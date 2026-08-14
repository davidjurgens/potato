"""
Cross-language check: the JavaScript builds the tensors, the real model runs them.

Every other test of the browser segmentation code either mocks the ONNX runtime
(so a wrong tensor shape passes) or checks the JS against my *reading* of the
contract (so a shared misreading passes). This closes that gap from both ends:
Node computes the prompt tensors with the actual shipped code, and Python feeds
those exact numbers to the actual MobileSAM weights.

If the JavaScript scales coordinates wrongly, the mask lands somewhere else and
this fails — which is precisely the failure that three plausible readings of the
contract produce, and that no mocked test can see.

Skipped when Node or the weights are absent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
rt = pytest.importorskip("onnxruntime")
PIL = pytest.importorskip("PIL")

from potato.models_cli import DEFAULT_MODEL_DIR  # noqa: E402

ENCODER = DEFAULT_MODEL_DIR / "mobile_sam" / "encoder.onnx"
DECODER = DEFAULT_MODEL_DIR / "mobile_sam" / "decoder.onnx"
PREPROCESS = Path("potato/static/segmentation/sam-preprocess.js").resolve()

pytestmark = pytest.mark.skipif(
    not (ENCODER.exists() and DECODER.exists() and shutil.which("node")),
    reason="needs MobileSAM weights and node")

WIDTH, HEIGHT = 480, 300
DISCS = [(90, 80), (240, 200), (390, 90)]
DISC_RADIUS = 45


def run_node(script: str) -> dict:
    """
    Execute a snippet against the real preprocessing module.

    Written to a temp FILE rather than passed with `node -e`: a full-resolution
    mask is 144,000 floats, and inlining that blows past ARG_MAX with an
    "Argument list too long" that looks like a node problem.
    """
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(script)
        result = subprocess.run(
            ["node", path], capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(path)
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr}")
    return json.loads(result.stdout)


def run_node_with_data(script_body: str, payload) -> dict:
    """Same, but the data goes through a JSON file instead of the source."""
    import os
    import tempfile

    fd, data_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh)
    try:
        return run_node(
            f"const DATA = require({data_path!r});\n" + script_body)
    finally:
        os.unlink(data_path)


@pytest.fixture(scope="module")
def scene():
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (WIDTH, HEIGHT), (40, 60, 90))
    draw = ImageDraw.Draw(image)
    for cx, cy in DISCS:
        draw.ellipse([cx - DISC_RADIUS, cy - DISC_RADIUS,
                      cx + DISC_RADIUS, cy + DISC_RADIUS],
                     fill=(220, 60, 60))
    return image


@pytest.fixture(scope="module")
def embedding(scene):
    """Encoded exactly as the JS says to: longest side resized to 1024."""
    from PIL import Image

    geometry = run_node(f"""
        const p = require({str(PREPROCESS)!r});
        console.log(JSON.stringify(p.resizeLongestSide({WIDTH}, {HEIGHT})));
    """)
    resized = np.array(
        scene.resize((geometry["width"], geometry["height"]), Image.BILINEAR),
        dtype=np.float32)
    encoder = rt.InferenceSession(str(ENCODER),
                                  providers=["CPUExecutionProvider"])
    return encoder.run(None, {"input_image": resized})[0], geometry


@pytest.fixture(scope="module")
def decoder():
    return rt.InferenceSession(str(DECODER),
                               providers=["CPUExecutionProvider"])


def js_prompt_tensors(points, box=None):
    """Whatever the shipped JavaScript decides to send."""
    box_js = json.dumps(box) if box else "null"
    return run_node(f"""
        const p = require({str(PREPROCESS)!r});
        const geometry = Object.assign(
            p.resizeLongestSide({WIDTH}, {HEIGHT}),
            {{ origWidth: {WIDTH}, origHeight: {HEIGHT} }});
        const t = p.buildPromptTensors(
            {{ points: {json.dumps(points)}, box: {box_js} }}, geometry);
        const out = {{}};
        Object.keys(t).forEach(k => {{
            out[k] = {{ data: Array.from(t[k].data), dims: t[k].dims }};
        }});
        console.log(JSON.stringify(out));
    """)


def decode_with(decoder, embedding, tensors):
    feeds = {"image_embeddings": embedding}
    for name, spec in tensors.items():
        feeds[name] = np.array(spec["data"], dtype=np.float32).reshape(
            spec["dims"])
    return decoder.run(None, feeds)


def mask_centroid(masks):
    binary = masks[0, 0] > 0
    if not binary.any():
        return None, 0
    ys, xs = np.nonzero(binary)
    return (xs.mean(), ys.mean()), binary.sum() / binary.size


class TestGeometryAgreement:
    def test_the_js_resize_matches_python(self):
        geometry = run_node(f"""
            const p = require({str(PREPROCESS)!r});
            console.log(JSON.stringify(p.resizeLongestSide({WIDTH}, {HEIGHT})));
        """)
        expected = 1024 / max(WIDTH, HEIGHT)
        assert geometry["scale"] == pytest.approx(expected)
        assert geometry["width"] == 1024, "the longest side becomes 1024"
        assert geometry["height"] == round(HEIGHT * expected)

    def test_a_portrait_image_scales_on_its_height(self):
        """The bug where someone 'simplifies' the scale to 1024/width."""
        geometry = run_node(f"""
            const p = require({str(PREPROCESS)!r});
            console.log(JSON.stringify(p.resizeLongestSide(300, 480)));
        """)
        assert geometry["height"] == 1024
        assert geometry["width"] == 640


class TestTheJavaScriptDrivesTheRealModel:
    def test_a_click_computed_by_js_lands_on_the_target(self, embedding,
                                                        decoder):
        """
        The end-to-end check. JS turns a click in ORIGINAL pixels into tensors;
        the real weights turn those into a mask; the mask must sit on the disc
        that was clicked.
        """
        emb, _geometry = embedding
        for cx, cy in DISCS:
            tensors = js_prompt_tensors([[cx, cy, 1]])
            masks, _iou, _low = decode_with(decoder, emb, tensors)
            centroid, coverage = mask_centroid(masks)
            assert centroid is not None, f"click {(cx, cy)} produced no mask"
            error = ((centroid[0] - cx) ** 2 + (centroid[1] - cy) ** 2) ** 0.5
            assert error < 10, (
                f"JS-computed click at {(cx, cy)} produced a mask centred at "
                f"{centroid} — {error:.1f}px away. The coordinate transform in "
                f"sam-preprocess.js does not match the model.")
            assert coverage < 0.15, (
                f"mask covers {coverage:.1%} — that is the background, not the "
                f"disc")

    def test_a_box_computed_by_js_segments_what_it_encloses(self, embedding,
                                                            decoder):
        emb, _geometry = embedding
        cx, cy = DISCS[1]
        tensors = js_prompt_tensors(
            [], box=[cx - DISC_RADIUS - 5, cy - DISC_RADIUS - 5,
                     2 * (DISC_RADIUS + 5), 2 * (DISC_RADIUS + 5)])
        masks, _iou, _low = decode_with(decoder, emb, tensors)
        centroid, _coverage = mask_centroid(masks)
        assert centroid is not None
        error = ((centroid[0] - cx) ** 2 + (centroid[1] - cy) ** 2) ** 0.5
        assert error < 15, f"box prompt centred at {centroid}, wanted {(cx, cy)}"

    def test_the_js_tensor_shapes_are_what_the_model_declares(self, decoder):
        tensors = js_prompt_tensors([[100, 100, 1]])
        declared = {i.name: i for i in decoder.get_inputs()}
        for name, spec in tensors.items():
            assert name in declared, f"JS sends {name}, which the model has not"
            expected_rank = len(declared[name].shape)
            assert len(spec["dims"]) == expected_rank, (
                f"{name}: JS sends rank {len(spec['dims'])}, model wants "
                f"{expected_rank}")

    def test_js_sends_every_input_the_model_requires(self, decoder):
        """The bug that shipped once: two of six inputs."""
        tensors = js_prompt_tensors([[100, 100, 1]])
        required = {i.name for i in decoder.get_inputs()}
        # image_embeddings is supplied by the session, not the prompt builder.
        assert required - {"image_embeddings"} == set(tensors)

    def test_orig_im_size_is_height_then_width(self, decoder):
        """Transposed rather than an error — invisible on a square image."""
        tensors = js_prompt_tensors([[100, 100, 1]])
        assert tensors["orig_im_size"]["data"] == [HEIGHT, WIDTH]


class TestMaskConversion:
    def test_js_rle_matches_the_python_decoder(self, embedding, decoder):
        """
        The mask the browser stores must be the mask the model produced. RLE
        that starts with a 1-run instead of a 0-run inverts the whole mask,
        which still renders as a plausible region.
        """
        from potato.export.cv_utils import decode_rle

        emb, _geometry = embedding
        cx, cy = DISCS[0]
        tensors = js_prompt_tensors([[cx, cy, 1]])
        masks, _iou, _low = decode_with(decoder, emb, tensors)

        logits = masks[0, 0].astype(np.float32).ravel().tolist()
        rle = run_node_with_data(f"""
            const p = require({str(PREPROCESS)!r});
            const logits = Float32Array.from(DATA);
            console.log(JSON.stringify(
                p.logitsToRle(logits, {WIDTH}, {HEIGHT})));
        """, logits)

        assert rle["size"] == [HEIGHT, WIDTH]
        restored = np.array(decode_rle(
            {"counts": rle["counts"], "size": rle["size"]}, WIDTH, HEIGHT))
        expected = (masks[0, 0] > 0).ravel().astype(int)
        assert restored.tolist() == expected.tolist(), (
            "the JS RLE does not round-trip to the model's own mask")
        assert rle["area"] == int(expected.sum())

    def test_js_bbox_matches_the_mask(self, embedding, decoder):
        emb, _geometry = embedding
        cx, cy = DISCS[2]
        tensors = js_prompt_tensors([[cx, cy, 1]])
        masks, _iou, _low = decode_with(decoder, emb, tensors)

        logits = masks[0, 0].astype(np.float32).ravel().tolist()
        bbox = run_node_with_data(f"""
            const p = require({str(PREPROCESS)!r});
            const logits = Float32Array.from(DATA);
            console.log(JSON.stringify(
                p.logitsToBbox(logits, {WIDTH}, {HEIGHT})));
        """, logits)
        binary = masks[0, 0] > 0
        ys, xs = np.nonzero(binary)
        assert bbox["x"] == int(xs.min())
        assert bbox["y"] == int(ys.min())
        assert bbox["width"] == int(xs.max() - xs.min() + 1)
        assert bbox["height"] == int(ys.max() - ys.min() + 1)
