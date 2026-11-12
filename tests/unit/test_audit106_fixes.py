"""Audit 106: training group 6 (science trainers, inference bridges, DP-SGD).

One test per finding fixed; each fails on the code the audit ran (r121)."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from tests.unit.test_training_trainers import _context, _predictions, _run, _spec

HAVE = __import__("importlib").util.find_spec
needs_torch = pytest.mark.skipif(not all(HAVE(m) for m in ("torch", "numpy")),
                                 reason="torch/numpy absent")
needs_rdkit = pytest.mark.skipif(not all(HAVE(m) for m in ("rdkit", "sklearn", "numpy")),
                                 reason="rdkit absent")
needs_numpy = pytest.mark.skipif(not HAVE("numpy"), reason="numpy absent")


# ------------------------------------------------------------- A1 (P1)

@needs_torch
def test_a1_display_channels_in_the_name_and_colour_form_are_read(tmp_path):
    from tests.unit.test_training_science import signal_project
    config, context = signal_project(tmp_path, "epoch", n=8)
    config["instance_display"]["fields"][0]["display_options"]["channels"] = [
        {"name": "Fz", "color": "#f00"}, {"name": "Cz", "color": "#00f"}]
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["stage"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "signal-cnn", "stage",
                 {"epochs": 2, "batch_size": 16, "rate": 50.0, "width": 4, "depth": 3,
                  "min_instances": 3})
    code, _result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    with open(os.path.join(spec.workdir, "model_card.json")) as fh:
        assert json.load(fh)["channel_names"] == ["Fz", "Cz"]


# ------------------------------------------------------------- A2 (P1)

@needs_rdkit
def test_a2_a_slider_prediction_is_a_label_the_page_prefills(tmp_path):
    from potato.flask_server import _prelabel_names
    from potato.training.trainers.rdkit_property import RDKitPropertyTrainer
    from tests.unit.test_training_science import molecule_project
    config, context, _ = molecule_project(tmp_path, question="slider")
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["carbons"], split_seed=0)
    params = {"min_instances": 5, "model": "ridge", "alpha": 0.1}
    params.update(RDKitPropertyTrainer.server_params(config, ["carbons"], params))
    spec = _spec(tmp_path, config, bundle, "rdkit-property", "carbons", params)
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    payload = _predictions(spec)[0]["payload"]
    assert isinstance(payload["label"], str) and payload["label"].isdigit()
    # The render path's reader: a float label was dropped and the slider sat at 0.
    assert _prelabel_names(payload) == [payload["label"]]
    assert result["metrics"]["heldout_score"] >= 0.0


# --------------------------------------------------------- B1, B2 (P2)

class _Echo(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _go(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.dumps({"you_called": self.path,
                           "headers": dict(self.headers)}).encode()
        self.send_response(401)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _go


@pytest.fixture
def echo():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


KEY = "SECRETKEY-abc123"


@pytest.mark.parametrize("trainer,params", [
    ("roboflow", {"model_id": "a/1", "api_key_env": "AUDIT106_KEY"}),
    ("openai-vlm-boxes", {"api_key_env": "AUDIT106_KEY"}),
    ("cvat-nuclio", {}),
])
def test_b1_a_key_echoed_by_the_service_does_not_reach_the_run(tmp_path, echo, monkeypatch,
                                                               trainer, params):
    from tests.unit.test_training_bridges import _boxes, _bridge_run
    monkeypatch.setenv("AUDIT106_KEY", KEY)
    url = {"openai-vlm-boxes": echo + "/v1", "cvat-nuclio": echo + "/fn"}.get(trainer, echo)
    config, bundle = _boxes(tmp_path, n=6)
    spec, (code, _result, report) = _bridge_run(tmp_path, config, bundle, trainer, "boxes",
                                                dict(params, url=url, timeout_s=5))
    assert code != EXIT_OK
    blob = json.dumps(report.events)
    for root, _dirs, files in os.walk(spec.workdir):
        for name in files:
            with open(os.path.join(root, name), errors="ignore") as fh:
                blob += fh.read()
    assert KEY not in blob and "SECRETKEY" not in blob
    assert "401" in report.of_type("error")[0]["message"]


def test_b1_scrub_covers_the_key_and_key_shaped_strings():
    from potato.training.trainers._bridge_common import scrub
    text = 'GET /m/1?api_key=%s&x=1 "Authorization": "Bearer %s" token=zzz' % (KEY, KEY)
    out = scrub(text, [KEY])
    assert KEY not in out and "zzz" not in out
    assert "api_key=[redacted]" in out and "Bearer [redacted]" in out


class _LongEcho(BaseHTTPRequestHandler):
    body, status = "", 401

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        data = _LongEcho.body.encode()
        self.send_response(_LongEcho.status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.mark.parametrize("status,body", [
    (401, "x" * 290 + KEY),               # an error body: the key across the 300 cut
    (200, "<html>" + "x" * 188 + KEY),    # not JSON: the key across the 200 cut
])
def test_c1_a_key_cut_in_half_by_the_error_length_is_still_scrubbed(status, body):
    """Audit 106 re-check C1: the body was cut before it was scrubbed, so a
    key straddling the cut no longer matched and most of it was shown."""
    from potato.training.base import TrainerError
    from potato.training.trainers._bridge_common import post
    _LongEcho.body, _LongEcho.status = body, status
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LongEcho)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(TrainerError) as raised:
            post("http://127.0.0.1:%d/m" % server.server_address[1], timeout=5,
                 json_body={}, secrets=[KEY])
    finally:
        server.shutdown()
    assert KEY[:6] not in str(raised.value)


def test_b2_a_key_pasted_where_its_variable_name_goes_is_not_echoed(tmp_path):
    from tests.unit.test_training_bridges import _boxes
    config, bundle = _boxes(tmp_path, n=6)
    spec = _spec(tmp_path, config, bundle, "roboflow", "boxes",
                 {"model_id": "a/1", "api_key_env": "rf_live-" + KEY})
    problems = registry.get_trainer_class("roboflow")().validate(spec, bundle)
    assert problems and not any(KEY in p for p in problems)
    assert any("name of an environment variable" in p for p in problems)


# --------------------------------------------------------- B3, B8 (P2/P3)

def _hf_card(kind, labels):
    return {"labels": labels, "kind": kind, "schema": "s", "task": "x", "url": "u"}


class _Report:
    def __init__(self):
        self.logs = []

    def log(self, level, msg):
        self.logs.append(msg)

    def progress(self, *a, **k):
        pass

    def should_stop(self):
        return False


def test_b3_the_top_label_outside_the_scheme_is_no_prediction(monkeypatch):
    from potato.training.base import PredictItem
    from potato.training.trainers.hf_inference import HFInferenceTrainer
    trainer = HFInferenceTrainer()
    monkeypatch.setattr(trainer, "_call", lambda params, **k: [[
        {"label": "LABEL_0", "score": 0.9}, {"label": "positive", "score": 0.1}]])
    left = {}
    records = list(trainer._classify([PredictItem("i1", "t")], _hf_card(
        "nominal", ["positive", "negative"]), {"threshold": 0.5, "label_map": {}}, left))
    assert records == []
    assert left == {"top answers under a label the scheme lacks": 1}


def test_b8_entity_tags_lose_their_bio_prefix_and_drops_are_counted(monkeypatch):
    from potato.training.base import PredictItem
    from potato.training.trainers.hf_inference import HFInferenceTrainer
    trainer = HFInferenceTrainer()
    monkeypatch.setattr(trainer, "_call", lambda params, **k: [
        {"entity": "B-PER", "score": 0.9, "start": 0, "end": 3},
        {"entity": "B-LOC", "score": 0.9, "start": 4, "end": 7}])
    left = {}
    record = trainer._spans(PredictItem("i1", "Ann met"), _hf_card("span", ["PER"]),
                            {"aggregation_strategy": "none", "label_map": {}}, left)
    assert record.payload == [{"start": 0, "end": 3, "label": "PER", "confidence": 0.9}]
    assert left == {"entities under a label the scheme lacks": 1}


# --------------------------------------------------------- B4, B10 (P2/P3)

@pytest.mark.parametrize("dp,needle", [
    ({}, "dp needs epsilon"),
    ({"epsilon": float("nan")}, "finite number above 0"),
    ({"epsilon": float("inf")}, "finite number above 0"),
    ({"epsilon": 3, "max_grad_norm": float("inf")}, "max_grad_norm must be a finite"),
])
def test_b4_an_empty_or_non_finite_dp_is_refused_not_turned_off(dp, needle):
    from potato.training.trainers import _dp
    problems = _dp.problems({"dp": dp}, 100)
    assert any(needle in p for p in problems), problems


def test_b10_validation_counts_the_rows_the_scheme_trains_on(tmp_path):
    """A run over two schemes has train rows with no target for the one
    trained; delta is checked against the rows that train, as the run's
    default delta is computed from them."""
    from tests.unit.test_training_trainers import sentiment_project
    config, context = sentiment_project(tmp_path)
    other = {"annotation_type": "radio", "name": "t", "description": "", "labels": ["x", "y"]}
    config["annotation_schemes"].append(other)
    for n, record in enumerate(context.annotations):
        if n % 3 == 0:
            record["labels"]["t"] = {"x" if n % 2 else "y": True}
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["t", "s"], split_seed=1)
    rows = sum(1 for r in bundle.read_split("train") if (r.get("targets") or {}).get("t"))
    assert rows < bundle.split_size("train")
    spec = _spec(tmp_path, config, bundle, "hf-text-classification", "t",
                 {"dp": {"epsilon": 3, "delta": 1.0 / rows}})
    problems = registry.get_trainer_class("hf-text-classification")().validate(spec, bundle)
    assert any("1 / %d train items" % rows in p for p in problems), problems


# ------------------------------------------------------------- A3 (P2)

@needs_numpy
def test_a3_two_picks_that_snap_to_one_apex_are_one_peak():
    import numpy
    from potato.training.trainers.peak_cnn import pick
    values = numpy.zeros(40)
    values[13] = 1.0
    probabilities = numpy.zeros(40)
    probabilities[10], probabilities[15] = 0.8, 0.7
    assert pick(probabilities, values, 0.5, 4, 3, 10) == [(13, 0.8)]


# ------------------------------------------------------------- A4 (P2)

def test_a4_a_wfdb_sample_file_linked_from_elsewhere_in_the_project_is_bundled(tmp_path):
    import copy
    from tests.unit.test_training_science import SIGNAL_DISPLAY, _blob, signal_scheme
    media, store = tmp_path / "media", tmp_path / "store"
    media.mkdir()
    store.mkdir()
    (media / "rec0.hea").write_text("rec0 1 100 10\n")
    (store / "rec0.dat").write_text("x")
    os.symlink(store / "rec0.dat", media / "rec0.dat")
    outside = tmp_path.parent / ("outside_%s.atr" % tmp_path.name)
    outside.write_text("x")
    os.symlink(outside, media / "rec0.atr")
    answer = {"intervals": [{"start": 0, "end": 2, "label": "slow"}], "events": []}
    config, context = _context(tmp_path, [signal_scheme("epoch")],
                               {"w": {"id": "w", "signal": "media/rec0.hea"}},
                               [{"instance_id": "w", "user_id": "a",
                                 "labels": {"stage": _blob("stage", answer)}}])
    config.update(copy.deepcopy(SIGNAL_DISPLAY))
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["stage"],
                                split_spec={"train": 1.0})
    row = next(bundle.read_split("train"))
    folder = os.path.dirname(os.path.join(bundle.root, "media", row["media"]))
    # Inside the project through a link: bundled. Outside it: left out.
    assert sorted(os.listdir(folder)) == ["rec0.dat", "rec0.hea"]


# ------------------------------------------------------------- A5 (P2)

def test_a5_a_question_about_drawn_structures_is_a_molecule_bundle_when_some_are_drawn(
        tmp_path):
    from potato.training.dataset import guess_modality
    chem = {"annotation_type": "chemical_structure", "name": "drawn", "description": ""}
    radio = {"annotation_type": "radio", "name": "q", "description": "", "labels": ["a", "b"]}
    items, annotations = {}, []
    for n in range(20):
        iid = "i%02d" % n
        items[iid] = {"id": iid, "text": "t%d" % n}
        labels = {"q": {"a" if n % 2 else "b": True}}
        if n < 15:
            labels["drawn"] = {"drawn": json.dumps({"smiles": "C" * (n + 1)})}
        annotations.append({"instance_id": iid, "user_id": "u", "labels": labels})
    config, context = _context(tmp_path, [chem, radio], items, annotations)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["q"],
                                    split_spec={"train": 1.0})
    assert guess_modality(config, radio, list(items.values())) == "molecule"
    assert bundle.manifest["modality"] == "molecule"
    assert any("5 item(s) have no structure" in w for w in stats.warnings)


# ------------------------------------------------------------- A6 (P3)

def test_a6_a_folder_named_with_a_trailing_slash_is_linked_by_its_name(tmp_path):
    from potato.training.dataset import BundleStats, _link_media
    (tmp_path / "media" / "lerobot" / "meta").mkdir(parents=True)
    stats = BundleStats()
    linked = _link_media("media/lerobot/", str(tmp_path), str(tmp_path / "b"), stats)
    assert linked.endswith("/lerobot")
    assert os.path.isdir(os.path.join(tmp_path, "b", linked, "meta"))


# ------------------------------------------------------------- A7 (P3)

def test_a7_the_slider_s_default_step_and_an_off_grid_maximum():
    from potato.training.trainers.rdkit_property import scale_of, slider_label, snap
    scale = scale_of({"min_value": 0, "max_value": 10})
    assert scale["step"] == 1.0 and snap(3.4, scale) == 3.0
    off_grid = scale_of({"min_value": 0, "max_value": 12, "step": 5})
    assert snap(11.9, off_grid) == 10.0 and snap(30, off_grid) == 10.0
    assert slider_label(7.0) == "7" and slider_label(2.5) == "2.5"


# ------------------------------------------------------------- A8 (P3)

@needs_numpy
def test_a8_max_peaks_keeps_the_most_confident_model_peaks():
    from potato.science.spectra import Spectrum
    from potato.server_utils.displays.spectrum_display import suggestions_for
    spectrum = Spectrum(x=list(range(10)), y=[1.0] * 10)
    peaks = [{"x": 1.0, "confidence": 0.2}, {"x": 5.0, "confidence": 0.9},
             {"x": 8.0, "confidence": 0.8}]
    shown, method = suggestions_for(spectrum, None, {"prepick": {"method": "model",
                                                                 "max_peaks": 2}},
                                    "max", peaks)
    assert method == "model" and [p["x"] for p in shown] == [5.0, 8.0]


# ------------------------------------------------------------- B5, B7, B9 (P3)

def test_b5_a_fraction_reply_with_a_box_past_the_edge_is_read_as_fractions():
    from potato.training.trainers.openai_vlm_boxes import reply_format
    assert reply_format([[0.1, 0.1, 0.5, 0.5], [0.6, 0.6, 1.02, 0.9]], 100, 80) == "fraction"
    assert reply_format([[10, 10, 50, 50]], 100, 80) == "pixels"
    assert reply_format([[100, 100, 900, 950]], 100, 80) == "per_mille"


def test_b7_a_score_that_is_not_a_number_is_no_confidence_not_a_crash():
    from potato.training.trainers._bridge_common import box, number
    assert number("high") is None and number(float("nan")) is None and number("0.5") == 0.5
    obj = box("red", 0, 0, 10, 10, 100, 100, "high", "v")
    assert obj is not None and "confidence" not in obj
    from potato.training.trainers.roboflow_bridge import objects_of
    out, dropped = objects_of({"predictions": [{"x": 5, "y": 5, "width": 4, "height": 4,
                                                "class": "red", "confidence": "high"}]},
                              ["red"], {}, 100, 100, "box", "v")
    assert len(out) == 1 and dropped == 0


def test_b9_a_nuclio_answer_that_is_not_a_list_is_counted():
    from potato.training.trainers.cvat_nuclio import shapes_of
    out, left = shapes_of({"error": "model not loaded"}, ["red"], {}, 100, 100, "v")
    assert out == [] and left == {"answers that were not a list of shapes": 1}


# ------------------------------------------------- manager: write-back failure

def test_a_write_back_failure_is_in_the_run_status(monkeypatch):
    from types import SimpleNamespace
    from potato.training import writeback
    from potato.training.manager import TrainingManager
    manager = TrainingManager.__new__(TrainingManager)
    seen = {}
    manager._set = lambda **fields: seen.update(fields)
    manager.logger = SimpleNamespace(exception=lambda *a, **k: None, debug=lambda *a, **k: None)
    manager.run_dir = lambda run_id: "/nonexistent"
    manager.config, manager.retain_runs = {}, 5

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(writeback, "ingest_predictions", boom)
    monkeypatch.setattr("potato.training.store.prune_runs", lambda *a, **k: None)
    recorded = []
    monkeypatch.setattr("potato.training.store.record_run",
                        lambda config, run: recorded.append((run.error, run.error_code)))
    run = SimpleNamespace(run_id="r9", error="", error_code="")
    manager._after_success(run, {"predictions_file": "p.jsonl"})
    assert seen["writeback"]["error"] == "Write-back failed: disk full"
    assert seen["writeback"]["run_id"] == "r9"
    # On the recorded run too (re-check C2): the live status is gone after a
    # restart, and the success announcement cleared its errors.
    assert recorded == [("Write-back failed: disk full", "writeback_failed")]
