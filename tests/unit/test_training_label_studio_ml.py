"""The label-studio-ml trainer: an existing Label Studio ML backend's
predictions, scored and written back like a trained model's.

The backend here is a stand-in served from a thread: ``/health`` and
``/predict`` in the shapes the label-studio-ml package uses. It answers from
the text (a review with "awful" or "hated" in it is negative), so the held-out score
measures the translation, not a model.
"""

import json
import os
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from potato.training.trainers.label_studio_ml import (label_config,
                                                      predictions_of)
from tests.unit.test_training_trainers import (_context, _predictions, _run,
                                               _spec, sentiment_project)


class FakeBackend(BaseHTTPRequestHandler):
    seen = []
    #: ``override(body, n)`` -> ``(status, bytes)`` to answer the n-th
    #: /predict call (from 0) differently, or None to answer normally.
    override = None

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
        if self.path == "/health":
            self._send(200, {"status": "UP", "model_class": "FakeModel"})
        else:
            self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeBackend.seen.append({"auth": self.headers.get("Authorization"),
                                 "body": body})
        answer = FakeBackend.override and FakeBackend.override(
            body, len(FakeBackend.seen) - 1)
        if answer:
            status, data = answer
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        config = ET.fromstring(body["label_config"])
        control = next(n for n in config.iter()
                       if n.get("toName"))
        results = []
        for task in body["tasks"]:
            text = task["data"].get("text", "")
            if control.tag == "Choices":
                negative = any(w in text for w in (
                    "terrible", "awful", "bad", "poor", "hated", "chore"))
                value = {"choices": ["negative" if negative else "positive"]}
                kind = "choices"
            elif control.tag == "Labels":
                # Label Studio counts offsets in UTF-16 code units.
                start = text.find("great")
                start = len(text[:start].encode("utf-16-le")) // 2
                value = {"start": start, "end": start + 5, "text": "great",
                         "labels": ["praise"]} if "great" in text else None
                kind = "labels"
            else:
                value = {"x": 10, "y": 20, "width": 30, "height": 40,
                         "rectanglelabels": ["red"]}
                kind = "rectanglelabels"
            region = ([{"from_name": control.get("name"),
                        "to_name": control.get("toName"), "type": kind,
                        "value": value}] if value else [])
            results.append({"result": region, "score": 0.75,
                            "model_version": "fake-1"})
        self._send(200, {"results": results})


@pytest.fixture
def backend():
    FakeBackend.seen = []
    FakeBackend.override = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


# --------------------------------------------------------------- pieces

def test_label_configs_are_valid_and_carry_the_labels():
    for scheme, kind, tag in [
            ({"name": "s", "labels": ["pos", {"name": "neg"}]}, "nominal", "Choices"),
            ({"name": "s", "labels": ["a", "b"]}, "multilabel", "Choices"),
            ({"name": "s", "labels": ["PER"]}, "span", "Labels"),
            ({"name": "s", "labels": ["car"], "tools": ["bbox"]}, "geometry",
             "RectangleLabels"),
            ({"name": "s", "labels": ["car"], "tools": ["polygon"]}, "geometry",
             "PolygonLabels")]:
        root = ET.fromstring(label_config(scheme, kind))
        control = root.find(tag)
        assert control is not None and control.get("name") == "s"
        values = [n.get("value") for n in control]
        assert values == [l if isinstance(l, str) else l["name"]
                          for l in scheme["labels"]]
    multiple = ET.fromstring(label_config({"name": "s", "labels": ["a"]},
                                          "multilabel")).find("Choices")
    assert multiple.get("choice") == "multiple"


def test_a_label_with_quotes_does_not_break_the_xml():
    ET.fromstring(label_config({"name": 'odd "name"',
                                "labels": ['say "hi" & <go>']}, "nominal"))


@pytest.mark.parametrize("response, n", [
    ({"results": [{"result": [], "score": 1}]}, 1),
    ([{"result": []}, {"result": []}], 2),        # older bare list
    ({"results": [[{"result": [], "score": 1}]]}, 1),  # a list per task
    ({}, 0),
])
def test_response_shapes(response, n):
    assert len(predictions_of(response)) == n


# ------------------------------------------------------------- end to end

def _ls_spec(tmp_path, config, bundle, schema, url, **params):
    return _spec(tmp_path, config, bundle, "label-studio-ml", schema,
                 dict({"url": url, "batch_size": 7}, **params))


def test_choices_are_scored_and_published(tmp_path, backend, monkeypatch):
    monkeypatch.setenv("LS_TOKEN", "sekrit")
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    spec = _ls_spec(tmp_path, config, bundle, "s", backend,
                    api_key_env="LS_TOKEN")
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    # The stand-in is right on every item, so the translation is exact.
    assert result["metrics"]["heldout_score"] == 1.0
    record = _predictions(spec)[0]
    assert record["payload"]["label"] in ("positive", "negative")
    assert record["payload"]["confidence"] == 0.75 == record["confidence"]
    assert {r["auth"] for r in FakeBackend.seen} == {"Token sekrit"}
    # Batches of batch_size, never the train split.
    sizes = [len(r["body"]["tasks"]) for r in FakeBackend.seen]
    assert max(sizes) <= 7
    assert sum(sizes) == bundle.split_size("val") + bundle.split_size("test")


def test_spans_come_back_in_code_points(tmp_path, backend):
    scheme = {"annotation_type": "span", "name": "praise", "description": "",
              "labels": ["praise"]}
    items, annotations = {}, []
    for n in range(20):
        text = "café 😀 this was great %d" % n
        start = text.find("great")
        items["i%02d" % n] = {"id": "i%02d" % n, "text": text}
        annotations.append({"instance_id": "i%02d" % n, "user_id": "u",
                            "labels": {}, "spans": {"praise": [
                                {"start": start, "end": start + 5,
                                 "name": "praise"}]}})
    config, context = _context(tmp_path, [scheme], items, annotations)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["praise"])
    spec = _ls_spec(tmp_path, config, bundle, "praise", backend)
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["heldout_score"] == 1.0
    span = _predictions(spec)[0]["payload"][0]
    assert span["label"] == "praise" and span["source"] == "model"


def test_an_unreachable_backend_fails_the_run_with_its_address(tmp_path):
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    spec = _ls_spec(tmp_path, config, bundle, "s", "http://127.0.0.1:9")
    code, _, report = _run(spec)
    assert code != EXIT_OK
    assert any("127.0.0.1:9" in str(e) for e in report.of_type("error"))


@pytest.mark.parametrize("params, needle", [
    ({"url": ""}, "params.url"),
    ({"url": "http://x", "api_key_env": "SURELY_UNSET_VAR"}, "SURELY_UNSET_VAR"),
])
def test_validation(tmp_path, params, needle):
    from potato.training.trainers.label_studio_ml import LabelStudioMLTrainer
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    spec = _spec(tmp_path, config, bundle, "label-studio-ml", "s", params)
    problems = LabelStudioMLTrainer().validate(spec, bundle)
    assert any(needle in p for p in problems), problems


# ------------------------------------------------------- failures (audit 99)

def _answer_all(result_for):
    """An override answering every task with ``result_for(task)``."""
    def override(body, n):
        return 200, json.dumps({"results": [
            {"result": result_for(t), "score": 0.9}
            for t in body["tasks"]]}).encode()
    return override


def _choice(label, score=None, kind="choices", name="s"):
    res = {"from_name": name, "to_name": "text", "type": kind,
           "value": {kind: [label]} if kind != "textarea" else {"text": [label]}}
    if score is not None:
        res["score"] = score
    return res


@pytest.mark.parametrize("answer", [(500, b"boom"), (200, b"<html>no</html>")])
def test_a_failed_predict_fails_the_run(tmp_path, backend, answer):
    # fit() only checked /health, so without the predictions there is no
    # run: it must not end "success" with nothing scored.
    FakeBackend.override = lambda body, n: answer
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    code, result, report = _run(_ls_spec(tmp_path, config, bundle, "s", backend))
    assert code != EXIT_OK and result is None
    assert [e["code"] for e in report.of_type("error")] == ["predict_failed"]


def test_a_later_batch_failing_keeps_the_earlier_predictions(tmp_path, backend):
    FakeBackend.override = lambda body, n: (500, b"boom") if n == 1 else None
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    spec = _ls_spec(tmp_path, config, bundle, "s", backend)
    code, _, report = _run(spec)
    assert code != EXIT_OK
    assert "after 7 prediction(s)" in report.of_type("error")[0]["message"]
    assert len(_predictions(spec)) == 7


def test_results_that_do_not_answer_the_scheme_are_not_used(tmp_path, backend):
    # A textarea on a radio scheme, a choice the scheme lacks and an unknown
    # control: none of them is a prediction, and the run says why.
    FakeBackend.override = _answer_all(lambda t: [
        _choice("hi", kind="textarea"), _choice("neutral"),
        _choice("positive", name="other")])
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    code, _, report = _run(_ls_spec(tmp_path, config, bundle, "s", backend))
    assert code != EXIT_OK
    message = report.of_type("error")[0]["message"]
    assert "no usable prediction" in message
    for reason in ("type 'textarea'", "labels outside the scheme",
                   "from_name 'other'"):
        assert reason in message, message


def test_the_highest_scored_choice_wins_and_others_are_counted(tmp_path, backend):
    FakeBackend.override = _answer_all(lambda t: [
        _choice("negative", 0.2), _choice("positive", 0.95), _choice("neutral")])
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    spec = _ls_spec(tmp_path, config, bundle, "s", backend)
    code, _, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    payloads = [r["payload"] for r in _predictions(spec)]
    assert {p["label"] for p in payloads} == {"positive"}
    assert {p["confidence"] for p in payloads} == {0.95}
    logged = " ".join(e["msg"] for e in report.of_type("log"))
    assert "extra single-choice results" in logged
    assert "labels outside the scheme" in logged


def test_each_region_keeps_its_own_score(tmp_path, backend):
    def regions(task):
        text = task["data"]["text"]
        start = text.find("great")
        if start < 0:
            return []
        return [{"from_name": "praise", "to_name": "text", "type": "labels",
                 "score": score, "value": {"start": s, "end": s + 5,
                                           "labels": ["praise"]}}
                for s, score in ((start, 0.8), (0, 0.95))]
    FakeBackend.override = _answer_all(regions)
    scheme = {"annotation_type": "span", "name": "praise", "description": "",
              "labels": ["praise"]}
    items, annotations = {}, []
    for n in range(20):
        text = "a great day %d" % n
        items["i%02d" % n] = {"id": "i%02d" % n, "text": text}
        annotations.append({"instance_id": "i%02d" % n, "user_id": "u",
                            "labels": {}, "spans": {"praise": [
                                {"start": 2, "end": 7, "name": "praise"}]}})
    config, context = _context(tmp_path, [scheme], items, annotations)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["praise"])
    spec = _ls_spec(tmp_path, config, bundle, "praise", backend)
    code, _, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    record = _predictions(spec)[0]
    assert sorted(r["confidence"] for r in record["payload"]) == [0.8, 0.95]
    # The prediction-level score (0.9) is the record's.
    assert record["confidence"] == 0.9


# ------------------------------------- a stock backend (audit 99 addendum)

def test_basic_auth_is_sent_for_a_stock_backend(tmp_path, backend, monkeypatch):
    # label-studio-ml's only auth is BASIC_AUTH_USER / BASIC_AUTH_PASS.
    monkeypatch.setenv("LS_USER", "u")
    monkeypatch.setenv("LS_PASS", "sekret")
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    spec = _ls_spec(tmp_path, config, bundle, "s", backend,
                    basic_auth_user_env="LS_USER", basic_auth_pass_env="LS_PASS")
    code, _, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert {r["auth"] for r in FakeBackend.seen} == {"Basic dTpzZWtyZXQ="}


@pytest.mark.parametrize("params, needle", [
    ({"basic_auth_user_env": "LS_USER"}, "go together"),
    ({"api_key_env": "LS_USER", "basic_auth_user_env": "LS_USER",
      "basic_auth_pass_env": "LS_USER"}, "not both"),
])
def test_auth_validation(tmp_path, monkeypatch, params, needle):
    from potato.training.trainers.label_studio_ml import LabelStudioMLTrainer
    monkeypatch.setenv("LS_USER", "u")
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    spec = _spec(tmp_path, config, bundle, "label-studio-ml", "s",
                 dict({"url": "http://x"}, **params))
    problems = LabelStudioMLTrainer().validate(spec, bundle)
    assert any(needle in p for p in problems), problems


def test_a_token_refused_by_the_backend_points_at_basic_auth(tmp_path,
                                                            monkeypatch):
    # The SDK answers a non-Basic Authorization header with a 500.
    class Refusing(FakeBackend):
        def do_GET(self):
            self._send(500, {"error": "TypeError"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Refusing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LS_TOKEN", "t")
    try:
        config, context = sentiment_project(tmp_path)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
        code, _, report = _run(_ls_spec(
            tmp_path, config, bundle, "s",
            "http://127.0.0.1:%d" % server.server_address[1],
            api_key_env="LS_TOKEN"))
    finally:
        server.shutdown()
    assert code != EXIT_OK
    assert "basic_auth_user_env" in report.of_type("error")[0]["message"]


def test_images_with_the_same_name_get_different_urls(tmp_path, backend):
    import shutil
    from tests.unit.test_training_detection_audio_dpo import detection_project
    config, context, _ = detection_project(tmp_path, n=20)
    # Half the items point at a copy with the same file name in another
    # folder: other/img000.png beside img/img000.png.
    os.makedirs(tmp_path / "other")
    for n in range(10, 20):
        name = "img%03d.png" % (n - 10)
        shutil.copy(tmp_path / "img" / ("img%03d.png" % n), tmp_path / "other" / name)
        context.items["i%03d" % n]["image"] = "other/" + name
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["boxes"])
    spec = _ls_spec(tmp_path, config, bundle, "boxes", backend,
                    media_url_prefix="/data/local-files/?d=")
    code, _, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    sent = [t["data"]["image"] for r in FakeBackend.seen for t in r["body"]["tasks"]]
    assert len(set(sent)) == len(sent)
    assert all(s.startswith(("/data/local-files/?d=img/img",
                             "/data/local-files/?d=other/img")) for s in sent), sent


def test_the_task_carries_the_files_own_path():
    from potato.training.base import PredictItem
    from potato.training.trainers.label_studio_ml import LabelStudioMLTrainer
    task = LabelStudioMLTrainer()._task
    a = PredictItem("a", media="/b/media/3f/img1.png",
                    data={"media_source": "cats/img1.png"})
    b = PredictItem("b", media="/b/media/9c/img1.png",
                    data={"media_source": "dogs/img1.png"})
    for prefix, want in [("/data/local-files/?d=", "/data/local-files/?d=cats/img1.png"),
                         ("http://h/files", "http://h/files/cats/img1.png"),
                         ("http://h/files/", "http://h/files/cats/img1.png")]:
        params = {"media_url_prefix": prefix}
        assert task(0, a, "geometry", params)["data"]["image"] == want
        assert task(0, b, "geometry", params)["data"]["image"] != want
    # No prefix: the local path, for a backend that opens it itself.
    assert task(0, a, "geometry", {})["data"]["image"] == "/b/media/3f/img1.png"


def test_the_bundle_records_where_each_image_came_from(tmp_path):
    from tests.unit.test_training_detection_audio_dpo import detection_project
    _, context, _ = detection_project(tmp_path, n=6)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["boxes"])
    rows = [r for s in ("train", "val", "test") for r in bundle.read_split(s)]
    assert sorted(r["media_source"] for r in rows) == [
        "img/img%03d.png" % i for i in range(6)]


def test_wrong_basic_auth_credentials_are_named(tmp_path, monkeypatch):
    class Checking(FakeBackend):
        def do_GET(self):
            self._send(401, {"error": "Unauthorized"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Checking)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LS_USER", "u")
    monkeypatch.setenv("LS_PASS", "wrong")
    try:
        config, context = sentiment_project(tmp_path)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
        code, _, report = _run(_ls_spec(
            tmp_path, config, bundle, "s",
            "http://127.0.0.1:%d" % server.server_address[1],
            basic_auth_user_env="LS_USER", basic_auth_pass_env="LS_PASS"))
    finally:
        server.shutdown()
    assert code != EXIT_OK
    message = report.of_type("error")[0]["message"]
    assert "refused the credentials in LS_USER and LS_PASS" in message
    assert "set basic_auth_user_env" not in message


def test_an_image_outside_the_task_directory_is_left_out(tmp_path, backend):
    import shutil
    from tests.unit.test_training_detection_audio_dpo import detection_project
    config, context, _ = detection_project(tmp_path, n=20)
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    # Every other image moves out; the rest still get predictions.
    for n in range(0, 20, 2):
        name = "img%03d.png" % n
        shutil.copy(tmp_path / "img" / name, outside / name)
        context.items["i%03d" % n]["image"] = str(outside / name)
    try:
        bundle, stats, _ = build_bundle(context, str(tmp_path / "bundle"), ["boxes"])
        spec = _ls_spec(tmp_path, config, bundle, "boxes", backend,
                        media_url_prefix="/data/local-files/?d=")
        _, _, report = _run(spec)
    finally:
        shutil.rmtree(outside)
    # The bundle leaves them out (audit 102), so they never reach the trainer.
    assert stats.n_media_outside == 10
    assert any("outside the task directory" in w for w in stats.warnings)
    logged = " ".join(e["msg"] for e in report.of_type("log"))
    assert "have no image file" in logged and "not sent" in logged
    sent = [t["data"]["image"] for r in FakeBackend.seen for t in r["body"]["tasks"]]
    assert sent and all(s.startswith("/data/local-files/?d=img/") for s in sent)
    assert _predictions(spec)


# ----------------------------------------------------- key handling (audit 108)

def test_a_pasted_token_in_place_of_a_variable_name_is_not_echoed(tmp_path):
    from potato.training.trainers.label_studio_ml import LabelStudioMLTrainer
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"])
    token = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    spec = _spec(tmp_path, config, bundle, "label-studio-ml", "s",
                 {"url": "http://x", "api_key_env": token})
    problems = LabelStudioMLTrainer().validate(spec, bundle)
    assert any("name of an environment variable" in p for p in problems), problems
    assert not any(token in p for p in problems), problems


def test_an_error_body_echoing_the_key_is_scrubbed(monkeypatch):
    import requests

    from potato.training.base import TrainerError
    from potato.training.trainers.label_studio_ml import _post_json

    class Echo:
        status_code = 400
        text = "bad request; Authorization: Token sekrit-value-123 was sent"

    monkeypatch.setattr(requests, "post", lambda *a, **k: Echo())
    with pytest.raises(TrainerError) as caught:
        _post_json("http://x/predict", {}, {}, 5, secrets=["sekrit-value-123"])
    assert "sekrit-value-123" not in str(caught.value)
    assert "400" in str(caught.value)
