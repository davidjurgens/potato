"""
Cross-language check: the JavaScript tokenizes and decodes, the real model runs.

Every other test of the text-prompt path either mocks the ONNX runtime (so a
wrong tensor shape passes) or checks the JS against my *reading* of the
contract (so a shared misreading passes). This closes the gap from both ends:
Node produces the token ids with the shipped tokenizer, Python feeds them to
the actual Grounding DINO weights, and Node's postprocessing is then compared
against Python's on the model's real output.

The failure this exists to catch has no downstream symptom. A box carries no
label — it carries a score per token — so a tokenization or attribution error
returns boxes in the right places wearing the wrong labels. Nothing later can
notice.

Skipped when Node or the weights are absent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
rt = pytest.importorskip("onnxruntime")
pytest.importorskip("PIL")

from potato.model_zoo import MODELS  # noqa: E402
from potato.models_cli import DEFAULT_MODEL_DIR  # noqa: E402

MODEL_DIR = DEFAULT_MODEL_DIR / "grounding_dino_tiny"
MODEL = MODEL_DIR / "model.onnx"
VOCAB = MODEL_DIR / "vocab.txt"
SEGMENTATION = Path("potato/static/segmentation").resolve()

pytestmark = pytest.mark.skipif(
    not (MODEL.exists() and VOCAB.exists() and shutil.which("node")),
    reason="needs grounding_dino_tiny weights and node")

WIDTH, HEIGHT = 700, 520
#: A single orange disc on a pale ground. Grounding DINO calls it a ball, which
#: is all this test needs: the point is that BOTH implementations agree on the
#: same box, not that a synthetic scene is photographic.
DISC = (450, 90, 590, 230)
PHRASES = ["ball", "person"]

CLIENT = MODELS["grounding_dino_tiny"].client


def run_node(script: str):
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(script)
        result = subprocess.run(["node", path], capture_output=True,
                                text=True, timeout=300)
    finally:
        os.unlink(path)
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr[:3000]}")
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (WIDTH, HEIGHT), (238, 238, 234))
    draw = ImageDraw.Draw(image)
    draw.ellipse(list(DISC), fill=(224, 123, 57))
    path = tmp_path_factory.mktemp("gdino") / "scene.png"
    image.save(path)
    return image, path


@pytest.fixture(scope="module")
def js_tokens():
    """Token ids straight out of the shipped tokenizer."""
    return run_node(f"""
        const fs = require('fs');
        const {{ WordPieceTokenizer }} =
            require({str(SEGMENTATION / 'wordpiece.js')!r});
        const {{ buildCaption }} =
            require({str(SEGMENTATION / 'gdino-session.js')!r});
        const tok = WordPieceTokenizer.fromVocabText(
            fs.readFileSync({str(VOCAB)!r}, 'utf8'));
        const caption = buildCaption({json.dumps(PHRASES)});
        const encoded = tok.encode(caption);
        process.stdout.write(JSON.stringify({{
            caption, tokens: encoded.tokens, ids: encoded.ids,
            attention: encoded.attentionMask, types: encoded.tokenTypeIds,
        }}));
    """)


@pytest.fixture(scope="module")
def model_output(scene, js_tokens):
    """Run the real weights on the JS-produced tokens."""
    from PIL import Image

    image, _ = scene
    size = CLIENT["input_size"]
    resized = image.resize((size, size), Image.BILINEAR)
    arr = np.asarray(resized, dtype=np.float32) / 255.0
    arr = (arr - np.array(CLIENT["image_mean"], dtype=np.float32)) \
        / np.array(CLIENT["image_std"], dtype=np.float32)
    pixel_values = arr.transpose(2, 0, 1)[None].astype(np.float32)

    options = rt.SessionOptions()
    if CLIENT.get("graph_optimization") == "disabled":
        options.graph_optimization_level = rt.GraphOptimizationLevel.ORT_DISABLE_ALL
    session = rt.InferenceSession(str(MODEL), sess_options=options,
                                  providers=["CPUExecutionProvider"])
    ids = np.array([js_tokens["ids"]], dtype=np.int64)
    logits, boxes = session.run(None, {
        "pixel_values": pixel_values,
        "pixel_mask": np.ones((1, size, size), dtype=np.int64),
        "input_ids": ids,
        "token_type_ids": np.array([js_tokens["types"]], dtype=np.int64),
        "attention_mask": np.array([js_tokens["attention"]], dtype=np.int64),
    })
    return logits, boxes


def python_postprocess(logits, boxes, tokens, phrases,
                       box_threshold, text_threshold):
    """The same arithmetic the JS does, written independently in numpy."""
    # Clipped before exp: the export emits very large negative
    # logits, and numpy warns on the overflow even though the
    # result (0.0) is correct.
    probs = 1.0 / (1.0 + np.exp(-np.clip(logits[0], -60, 60)))
    phrase_of_token = {}
    phrase = 0
    for index, token in enumerate(tokens):
        if token in ("[CLS]", "[SEP]"):
            continue
        if token == ".":
            phrase += 1
            continue
        phrase_of_token[index] = phrase

    out = []
    for query in range(probs.shape[0]):
        row = probs[query]
        best = float(row.max())
        if best <= box_threshold:
            continue
        weights = {}
        for position, index in phrase_of_token.items():
            if position < row.shape[0] and row[position] > text_threshold:
                weights[index] = weights.get(index, 0.0) + float(row[position])
        if not weights:
            continue
        chosen = max(weights, key=weights.get)
        if chosen >= len(phrases):
            continue
        cx, cy, bw, bh = (float(v) for v in boxes[0][query])
        x = max(0.0, cx - bw / 2)
        y = max(0.0, cy - bh / 2)
        out.append({
            "label": phrases[chosen],
            "confidence": best,
            "bbox": {"x": x, "y": y,
                     "width": min(1 - x, bw), "height": min(1 - y, bh)},
        })
    out.sort(key=lambda d: -d["confidence"])
    return out


@pytest.fixture(scope="module")
def js_detections(model_output, js_tokens):
    """Feed the real model output back through the shipped JS postprocessing."""
    logits, boxes = model_output
    # The quantized export emits -inf for tokens it rules out entirely, and
    # JSON has no way to write that. Both implementations take sigmoid of it
    # and get 0, so a large finite stand-in changes no result — but it has to
    # be substituted here or `node` refuses to parse the payload at all.
    logits = np.nan_to_num(logits, neginf=-1e4, posinf=1e4)
    payload = {
        "logits": {"data": logits.reshape(-1).tolist(), "dims": list(logits.shape)},
        "pred_boxes": {"data": boxes.reshape(-1).tolist(), "dims": list(boxes.shape)},
        "tokens": js_tokens["tokens"],
    }
    fd, data_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh)
    try:
        return run_node(f"""
            const DATA = require({data_path!r});
            const {{ GroundingDinoSession }} =
                require({str(SEGMENTATION / 'gdino-session.js')!r});
            const s = new GroundingDinoSession({{ tokenizer: {{}} }});
            const output = {{
                logits: {{ data: Float32Array.from(DATA.logits.data),
                          dims: DATA.logits.dims }},
                pred_boxes: {{ data: Float32Array.from(DATA.pred_boxes.data),
                              dims: DATA.pred_boxes.dims }},
            }};
            const dets = s.postprocess(output, DATA.tokens,
                                       {json.dumps(PHRASES)},
                                       {WIDTH}, {HEIGHT});
            process.stdout.write(JSON.stringify(dets));
        """)
    finally:
        os.unlink(data_path)


class TestConstantsMatchTheExport:
    """Our client config must match what the model was exported to expect."""

    def test_input_size_and_normalisation_come_from_the_export(self):
        config_path = MODEL_DIR / "preprocessor_config.json"
        if not config_path.exists():
            pytest.skip("preprocessor_config.json is not installed")
        published = json.loads(config_path.read_text())
        assert CLIENT["input_size"] == published["size"]["width"]
        assert CLIENT["input_size"] == published["size"]["height"]
        assert CLIENT["image_mean"] == pytest.approx(published["image_mean"])
        assert CLIENT["image_std"] == pytest.approx(published["image_std"])


class TestCrossLanguageAgreement:
    def test_the_caption_uses_the_separator_the_model_expects(self, js_tokens):
        assert js_tokens["caption"] == "ball . person ."
        assert js_tokens["tokens"][0] == "[CLS]"
        assert js_tokens["tokens"].count(".") == len(PHRASES)

    def test_js_and_python_postprocessing_agree(self, js_detections,
                                                model_output, js_tokens):
        logits, boxes = model_output
        logits = np.nan_to_num(logits, neginf=-1e4, posinf=1e4)
        expected = python_postprocess(
            logits, boxes, js_tokens["tokens"], PHRASES,
            CLIENT["box_threshold"], CLIENT["text_threshold"])
        assert len(js_detections) == len(expected), (
            f"JS found {len(js_detections)}, python found {len(expected)}")
        for ours, theirs in zip(js_detections, expected):
            assert ours["label"] == theirs["label"]
            assert ours["confidence"] == pytest.approx(theirs["confidence"],
                                                       abs=1e-5)
            for key in ("x", "y", "width", "height"):
                assert ours["bbox"][key] == pytest.approx(
                    theirs["bbox"][key], abs=1e-5), key

    def test_the_detection_lands_on_the_object(self, js_detections):
        """The whole pipeline, judged against where the disc actually is."""
        assert js_detections, "the model found nothing at all"
        best = js_detections[0]
        x = best["bbox"]["x"] * WIDTH
        y = best["bbox"]["y"] * HEIGHT
        w = best["bbox"]["width"] * WIDTH
        h = best["bbox"]["height"] * HEIGHT

        dx1, dy1, dx2, dy2 = DISC
        ix1, iy1 = max(x, dx1), max(y, dy1)
        ix2, iy2 = min(x + w, dx2), min(y + h, dy2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        union = w * h + (dx2 - dx1) * (dy2 - dy1) - inter
        iou = inter / union if union else 0
        assert iou > 0.6, (
            f"detected box {[round(v) for v in (x, y, w, h)]} does not cover "
            f"the disc at {DISC} (IoU {iou:.2f}) — a scale or format error in "
            f"the box conversion looks exactly like this"
        )

    def test_the_label_is_the_phrase_that_matches(self, js_detections):
        """Attribution, which is the part with no other detector."""
        assert js_detections[0]["label"] == "ball", (
            "the disc came back attributed to the wrong phrase, which is what "
            "an off-by-one in token positions produces"
        )


class TestControls:
    """Wrong readings of the contract must measurably fail."""

    def test_a_square_resize_is_required_by_this_export(self, scene, js_tokens):
        """Aspect-preserving resize is the upstream convention and is WRONG here.

        Grounding DINO's own preprocessor resizes the shortest edge to 800 and
        caps the longest at 1333. This export takes a fixed square, so the
        upstream convention produces a differently-shaped tensor that the graph
        refuses outright.
        """
        from PIL import Image

        image, _ = scene
        options = rt.SessionOptions()
        if CLIENT.get("graph_optimization") == "disabled":
            options.graph_optimization_level = \
                rt.GraphOptimizationLevel.ORT_DISABLE_ALL
        session = rt.InferenceSession(str(MODEL), sess_options=options,
                                      providers=["CPUExecutionProvider"])
        scale = 800 / min(WIDTH, HEIGHT)
        resized = image.resize((int(WIDTH * scale), int(HEIGHT * scale)),
                               Image.BILINEAR)
        arr = np.asarray(resized, dtype=np.float32) / 255.0
        arr = (arr - np.array(CLIENT["image_mean"], dtype=np.float32)) \
            / np.array(CLIENT["image_std"], dtype=np.float32)
        with pytest.raises(Exception):
            session.run(None, {
                "pixel_values": arr.transpose(2, 0, 1)[None].astype(np.float32),
                "pixel_mask": np.ones((1, resized.height, resized.width),
                                      dtype=np.int64),
                "input_ids": np.array([js_tokens["ids"]], dtype=np.int64),
                "token_type_ids": np.array([js_tokens["types"]], dtype=np.int64),
                "attention_mask": np.array([js_tokens["attention"]],
                                           dtype=np.int64),
            })

    def test_dropping_normalisation_degrades_the_detection(self, scene,
                                                           js_tokens):
        """Rescaling without ImageNet normalisation still returns boxes.

        It just returns worse ones — which is the point. A pipeline error here
        does not raise; it quietly lowers quality, so the test asserts the
        difference rather than trusting the happy path.
        """
        from PIL import Image

        image, _ = scene
        size = CLIENT["input_size"]
        arr = np.asarray(image.resize((size, size), Image.BILINEAR),
                         dtype=np.float32) / 255.0
        options = rt.SessionOptions()
        if CLIENT.get("graph_optimization") == "disabled":
            options.graph_optimization_level = \
                rt.GraphOptimizationLevel.ORT_DISABLE_ALL
        session = rt.InferenceSession(str(MODEL), sess_options=options,
                                      providers=["CPUExecutionProvider"])
        logits, boxes = session.run(None, {
            "pixel_values": arr.transpose(2, 0, 1)[None].astype(np.float32),
            "pixel_mask": np.ones((1, size, size), dtype=np.int64),
            "input_ids": np.array([js_tokens["ids"]], dtype=np.int64),
            "token_type_ids": np.array([js_tokens["types"]], dtype=np.int64),
            "attention_mask": np.array([js_tokens["attention"]], dtype=np.int64),
        })
        unnormalised = python_postprocess(
            logits, boxes, js_tokens["tokens"], PHRASES,
            CLIENT["box_threshold"], CLIENT["text_threshold"])
        best = max((d["confidence"] for d in unnormalised), default=0.0)
        assert best < 0.9, (
            "skipping normalisation produced a confident detection, so this "
            "control proves nothing"
        )
