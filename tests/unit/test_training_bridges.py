"""The inference bridges (openai-vlm-boxes, hf-inference, roboflow,
cvat-nuclio): a model somewhere else, scored and written back like a trained
one.

The services here are one stand-in served from a thread, answering in each
service's own shapes. Its "model" finds the red and blue squares in the
image it is sent, from the pixels, so a held-out score measures the
bridge's translation of coordinates and labels, not a model.
"""

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from tests.unit.test_training_trainers import (_context, _predictions, _run, _spec,
                                               sentiment_project)

pytest.importorskip("PIL")


def squares(raw):
    """``(label, x0, y0, x1, y1)`` in pixels for each red or blue square,
    and the image's size."""
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    width, height = img.size
    pixels = img.load()
    seen, found = set(), []
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            label = "red" if r > 150 and b < 100 else "blue" if b > 150 and r < 100 else None
            if label is None or (x, y) in seen:
                continue
            stack, xs, ys = [(x, y)], [], []
            while stack:
                px, py = stack.pop()
                if (px, py) in seen or not (0 <= px < width and 0 <= py < height):
                    continue
                pr, pg, pb = pixels[px, py]
                same = (pr > 150 and pb < 100) if label == "red" else (pb > 150 and pr < 100)
                if not same:
                    continue
                seen.add((px, py))
                xs.append(px)
                ys.append(py)
                stack.extend([(px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)])
            found.append((label, min(xs), min(ys), max(xs) + 1, max(ys) + 1))
    return found, width, height


class Fake(BaseHTTPRequestHandler):
    seen = []
    #: What the chat model's numbers are: fraction, per_mille or pixels.
    vlm_format = "fraction"
    #: The model's own names for the classes.
    names = {"red": "red", "blue": "blue"}

    def log_message(self, *args):
        pass

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "fake-vlm"}]})
        else:
            self._send(404, {})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        url = urlparse(self.path)
        Fake.seen.append({"path": url.path, "query": parse_qs(url.query),
                          "auth": self.headers.get("Authorization"),
                          "type": self.headers.get("Content-Type"), "body": raw})
        if url.path == "/v1/chat/completions":
            body = json.loads(raw)
            image = body["messages"][0]["content"][1]["image_url"]["url"].split(",", 1)[1]
            found, w, h = squares(base64.b64decode(image))
            fmt = "per_mille" if Fake.vlm_format == "gemma" else Fake.vlm_format
            scale = {"fraction": (1.0 / w, 1.0 / h), "per_mille": (1000.0 / w, 1000.0 / h),
                     "pixels": (1.0, 1.0)}[fmt]
            objects = [{"label": Fake.names[l], "box": [x0 * scale[0], y0 * scale[1],
                                                        x1 * scale[0], y1 * scale[1]]}
                       for l, x0, y0, x1, y1 in found]
            if Fake.vlm_format == "gemma":
                # Gemma's own convention, whatever the prompt asked for.
                for o in objects:
                    o["box"] = [o["box"][1], o["box"][0], o["box"][3], o["box"][2]]
            content = "```json\n%s\n```" % json.dumps({"objects": objects})
            self._send(200, {"choices": [{"message": {"content": content}}]})
        elif url.path == "/hf":
            if self.headers.get("Content-Type", "").startswith("image/"):
                found, _w, _h = squares(raw)
                self._send(200, [{"label": Fake.names[l], "score": 0.9,
                                  "box": {"xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1}}
                                 for l, x0, y0, x1, y1 in found])
                return
            body = json.loads(raw)
            if isinstance(body["inputs"], str):     # token classification
                text = body["inputs"]
                start = text.find("great")
                self._send(200, [] if start < 0 else [
                    {"entity_group": "PRAISE", "score": 0.8, "word": "great",
                     "start": start, "end": start + 5}])
                return
            out = []
            for text in body["inputs"]:
                negative = any(w in text for w in ("terrible", "awful", "bad", "poor",
                                                   "hated", "chore"))
                out.append([{"label": "NEGATIVE" if negative else "POSITIVE", "score": 0.9},
                            {"label": "POSITIVE" if negative else "NEGATIVE", "score": 0.1}])
            self._send(200, out)
        elif url.path == "/hard-hats/3":
            if parse_qs(url.query).get("api_key") != ["rf-secret"]:
                self._send(401, {"message": "bad key"})
                return
            found, w, h = squares(base64.b64decode(raw))
            self._send(200, {"image": {"width": w, "height": h}, "predictions": [
                {"x": (x0 + x1) / 2, "y": (y0 + y1) / 2, "width": x1 - x0,
                 "height": y1 - y0, "class": Fake.names[l], "confidence": 0.8}
                for l, x0, y0, x1, y1 in found]})
        elif url.path == "/nuclio":
            body = json.loads(raw)
            found, _w, _h = squares(base64.b64decode(body["image"]))
            shapes = [{"confidence": "0.85", "label": Fake.names[l],
                       "points": [x0, y0, x1, y1], "type": "rectangle"}
                      for l, x0, y0, x1, y1 in found]
            shapes.append({"confidence": "0.5", "label": "red", "type": "mask",
                           "mask": [0, 1, 0], "points": []})
            self._send(200, shapes)
        else:
            self._send(404, {})


@pytest.fixture
def service():
    Fake.seen = []
    Fake.vlm_format = "fraction"
    Fake.names = {"red": "red", "blue": "blue"}
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


def _boxes(tmp_path, n=20):
    from tests.unit.test_training_detection_audio_dpo import detection_project
    config, context, _ = detection_project(tmp_path, n=n)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["boxes"], split_seed=0)
    return config, bundle


def _bridge_run(tmp_path, config, bundle, trainer, schema, params):
    cls = registry.get_trainer_class(trainer)
    params = dict(params)
    params.update(cls.server_params(config, [schema], params))
    spec = _spec(tmp_path, config, bundle, trainer, schema, params)
    return spec, _run(spec)


def _check_boxes(spec, code, result, report, floor=0.9):
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert metrics["heldout_score"] >= floor, metrics
    from potato.server_utils.prelabel_values import client_shapes
    for record in _predictions(spec):
        shapes, dropped = client_shapes(record["payload"], ["red", "blue"])
        assert shapes and not dropped
    return metrics


# --------------------------------------------------------- openai-vlm-boxes

@pytest.mark.parametrize("fmt", ["fraction", "per_mille", "pixels"])
def test_a_vlm_s_boxes_are_read_whatever_its_coordinates(tmp_path, service, fmt):
    Fake.vlm_format = fmt
    config, bundle = _boxes(tmp_path)
    spec, (code, result, report) = _bridge_run(
        tmp_path, config, bundle, "openai-vlm-boxes", "boxes",
        {"url": service + "/v1", "coordinate_format": fmt if fmt != "fraction" else "auto"})
    _check_boxes(spec, code, result, report)
    sent = json.loads(Fake.seen[0]["body"])
    assert sent["model"] == "fake-vlm"
    assert sent["response_format"]["json_schema"]["schema"]["properties"]["objects"][
        "items"]["properties"]["label"]["enum"] == ["red", "blue"]
    assert "red, blue" in sent["messages"][0]["content"][0]["text"]


def test_gemma_s_y_first_per_mille_boxes_are_read_as_such(tmp_path, service):
    from potato.training.trainers.openai_vlm_boxes import conventions
    assert conventions("google/gemma-4-12B-it", "auto", "auto") == ("per_mille", "yxyx")
    assert conventions("Qwen/Qwen2.5-VL-7B", "auto", "auto") == ("auto", "xyxy")
    assert conventions("google/gemma-4-12B-it", "pixels", "xyxy") == ("pixels", "xyxy")
    Fake.vlm_format = "gemma"
    config, bundle = _boxes(tmp_path)
    spec, (code, result, report) = _bridge_run(
        tmp_path, config, bundle, "openai-vlm-boxes", "boxes",
        {"url": service + "/v1", "model": "google/gemma-4-12B-it"})
    _check_boxes(spec, code, result, report)
    # Read x first, the same answers miss.
    xyxy, (code, result, report) = _bridge_run(
        tmp_path / "xyxy", config, bundle, "openai-vlm-boxes", "boxes",
        {"url": service + "/v1", "model": "google/gemma-4-12B-it", "box_order": "xyxy"})
    assert code == EXIT_OK and result["metrics"]["heldout_score"] < 0.5


def test_a_vlm_s_other_names_are_mapped_and_unknown_ones_counted(tmp_path, service):
    Fake.names = {"red": "Red Square", "blue": "cube"}
    config, bundle = _boxes(tmp_path)
    spec, (code, result, report) = _bridge_run(
        tmp_path, config, bundle, "openai-vlm-boxes", "boxes",
        {"url": service + "/v1", "label_map": {"cube": "blue"}})
    assert code == EXIT_OK, report.of_type("error")
    labels = {o["label"] for r in _predictions(spec) for o in r["payload"]}
    # "Red Square" matches no label even ignoring case; "cube" is mapped.
    assert labels == {"blue"}
    assert any("under labels the scheme lacks" in e["msg"]
               for e in report.of_type("log"))


def test_a_vlm_endpoint_that_is_not_there_fails_the_run(tmp_path):
    config, bundle = _boxes(tmp_path, n=6)
    _spec_, (code, _result, report) = _bridge_run(
        tmp_path, config, bundle, "openai-vlm-boxes", "boxes",
        {"url": "http://127.0.0.1:9/v1"})
    assert code != EXIT_OK
    assert "127.0.0.1:9" in report.of_type("error")[0]["message"]


# ------------------------------------------------------------ hf-inference

def test_hf_inference_classifies_text_with_the_label_case_folded(tmp_path, service,
                                                                 monkeypatch):
    monkeypatch.setenv("HF_TEST_TOKEN", "hf-secret")
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["s"], split_seed=0)
    # The serverless URL, pointed at the stand-in.
    from potato.training.trainers import hf_inference
    monkeypatch.setattr(hf_inference.HFInferenceTrainer, "_url",
                        staticmethod(lambda params: service + "/hf"))
    spec, (code, result, report) = _bridge_run(
        tmp_path, config, bundle, "hf-inference", "s",
        {"model": "distilbert/sst2", "token_env": "HF_TEST_TOKEN"})
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["heldout_score"] == 1.0, result["metrics"]
    assert all(s["auth"] == "Bearer hf-secret" for s in Fake.seen)
    payload = _predictions(spec)[0]["payload"]
    assert payload["label"] in ("positive", "negative") and payload["confidence"] == 0.9


def test_hf_inference_tags_spans_and_detects_boxes(tmp_path, service, monkeypatch):
    from potato.training.trainers import hf_inference
    monkeypatch.setattr(hf_inference.HFInferenceTrainer, "_url",
                        staticmethod(lambda params: service + "/hf"))
    config, bundle = _boxes(tmp_path)
    spec, (code, result, report) = _bridge_run(
        tmp_path, config, bundle, "hf-inference", "boxes",
        {"model": "facebook/detr-resnet-50", "token_env": ""})
    _check_boxes(spec, code, result, report)
    assert Fake.seen[-1]["type"] in ("image/png", "image/jpeg")

    items, annotations = {}, []
    for n in range(12):
        text = "a great day %d" % n if n % 2 else "a dull day %d" % n
        items["t%d" % n] = {"id": "t%d" % n, "text": text}
        spans = [{"start": 2, "end": 7, "name": "praise"}] if n % 2 else []
        annotations.append({"instance_id": "t%d" % n, "user_id": "a",
                            "spans": {"e": spans} if spans else {}, "labels": {}})
    scheme = {"annotation_type": "span", "name": "e", "description": "",
              "labels": ["praise"]}
    cfg, ctx = _context(tmp_path / "spans", [scheme], items, annotations)
    span_bundle, _, _ = build_bundle(ctx, str(tmp_path / "sb"), ["e"], split_seed=0)
    spec, (code, result, report) = _bridge_run(
        tmp_path / "spans", cfg, span_bundle, "hf-inference", "e",
        {"model": "dslim/bert-base-NER", "token_env": "",
         "label_map": {"PRAISE": "praise"}})
    assert code == EXIT_OK, report.of_type("error")
    spans = [s for r in _predictions(spec) for s in r["payload"]]
    assert spans and all(s == {"start": 2, "end": 7, "label": "praise", "confidence": 0.8}
                         for s in spans)


@pytest.mark.parametrize("params,needle", [
    ({}, "endpoint_url"),
    ({"model": "a/b", "endpoint_url": "https://x"}, "not both"),
    ({"endpoint_url": "http://x"}, "https://"),
    ({"model": "a/b", "token_env": "SURELY_UNSET_HF_TOKEN"}, "not set"),
])
def test_hf_inference_validation(tmp_path, params, needle):
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["s"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "hf-inference", "s", params)
    problems = registry.get_trainer_class("hf-inference")().validate(spec, bundle)
    assert any(needle in p for p in problems), problems


# ---------------------------------------------------------------- roboflow

def test_roboflow_boxes_and_the_key_stays_out_of_messages(tmp_path, service, monkeypatch):
    monkeypatch.setenv("RF_TEST_KEY", "rf-secret")
    config, bundle = _boxes(tmp_path)
    spec, (code, result, report) = _bridge_run(
        tmp_path, config, bundle, "roboflow", "boxes",
        {"model_id": "hard-hats/3", "url": service, "api_key_env": "RF_TEST_KEY",
         "confidence": 0.5})
    _check_boxes(spec, code, result, report)
    assert Fake.seen[0]["query"]["confidence"] == ["50"]
    events = json.dumps([e for e in report.events])
    assert "rf-secret" not in events

    monkeypatch.setenv("RF_TEST_KEY", "wrong")
    _spec_, (code, _result, report) = _bridge_run(
        tmp_path, config, bundle, "roboflow", "boxes",
        {"model_id": "hard-hats/3", "url": service, "api_key_env": "RF_TEST_KEY"})
    assert code != EXIT_OK
    message = report.of_type("error")[0]["message"]
    assert "401" in message and "wrong" not in message and "api_key" not in message


def test_roboflow_needs_a_key_and_a_versioned_model(tmp_path):
    config, bundle = _boxes(tmp_path, n=6)
    spec = _spec(tmp_path, config, bundle, "roboflow", "boxes",
                 {"model_id": "hard-hats", "api_key_env": ""})
    problems = registry.get_trainer_class("roboflow")().validate(spec, bundle)
    assert any("project/version" in p for p in problems)
    assert any("api_key_env must name" in p for p in problems)


def test_roboflow_outlines_become_polygons_only_where_the_scheme_draws_them():
    from potato.training.trainers.roboflow_bridge import objects_of
    answer = {"predictions": [{"x": 20, "y": 20, "width": 10, "height": 10, "class": "red",
                               "confidence": 0.9, "points": [{"x": 15, "y": 15},
                                                             {"x": 25, "y": 15},
                                                             {"x": 20, "y": 25}]},
                              {"x": 5, "y": 5, "width": 4, "height": 4, "class": "green",
                               "confidence": 0.9}]}
    auto, dropped = objects_of(answer, ["red"], {}, 100, 50, "auto", "v")
    assert [o["type"] for o in auto] == ["polygon"] and dropped == 1
    boxes, _ = objects_of(answer, ["red"], {}, 100, 50, "box", "v")
    assert boxes[0]["coordinates"] == {"x": 0.15, "y": 0.3, "width": 0.1, "height": 0.2}


# ------------------------------------------------------------- cvat-nuclio

def test_cvat_nuclio_rectangles_are_kept_and_masks_counted(tmp_path, service):
    config, bundle = _boxes(tmp_path)
    spec, (code, result, report) = _bridge_run(
        tmp_path, config, bundle, "cvat-nuclio", "boxes",
        {"url": service + "/nuclio", "threshold": 0.3})
    _check_boxes(spec, code, result, report)
    sent = json.loads(Fake.seen[-1]["body"])
    assert sent["threshold"] == 0.3 and base64.b64decode(sent["image"])
    logged = " ".join(e["msg"] for e in report.of_type("log"))
    assert "masks" in logged


def test_a_nuclio_outline_on_a_box_scheme_is_its_bounding_box():
    from potato.training.trainers.cvat_nuclio import shapes_of
    answer = [{"type": "polygon", "label": "red", "confidence": "0.7",
               "points": [10, 10, 30, 10, 20, 40]}]
    as_box, _ = shapes_of(answer, ["red"], {}, 100, 100, "v", polygons=False)
    assert as_box[0]["type"] == "bbox"
    assert as_box[0]["coordinates"] == {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.3}
    as_polygon, _ = shapes_of(answer, ["red"], {}, 100, 100, "v")
    assert as_polygon[0]["type"] == "polygon" and as_polygon[0]["confidence"] == 0.7


def test_the_bridges_train_nothing_and_run_where_their_secret_is():
    for name in ("openai-vlm-boxes", "hf-inference", "roboflow", "cvat-nuclio"):
        cls = registry.get_trainer_class(name)
        assert cls.predict_only, name
        schema = cls.params_schema()
        assert schema["additionalProperties"] is False
        # A secret is only ever named, never given.
        assert not {"api_key", "token", "key"} & set(schema["properties"]), name
    assert registry.get_trainer_class("roboflow").local_only
    assert registry.get_trainer_class("hf-inference").local_only
