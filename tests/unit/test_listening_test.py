"""listening_test: trial plans, low-pass anchors, config validation, export."""

import csv
import json
import os
import wave

import numpy as np
import pytest

from potato.export.base import ExportContext
from potato.export.listening_exporter import ListeningTestExporter
from potato.listening.anchors import anchor_path
from potato.listening.plan import HIDDEN_REFERENCE, build_plan, client_view
from potato.server_utils.config_module import ConfigValidationError, _validate_listening_test
from tests.helpers.test_utils import create_test_directory

ITEM = {"id": "t1", "reference": "media/ref.wav",
        "stimuli": {"codec_a": "media/a.wav", "codec_b": "media/b.wav"}}
MUSHRA = {"name": "q", "annotation_type": "listening_test", "description": "d",
          "method": "mushra", "anchors": [3500, 7000]}


def test_mushra_plan_has_hidden_reference_anchors_and_is_stable():
    plan = build_plan(MUSHRA, ITEM, "alice", "t1")
    conditions = sorted(s["condition"] for s in plan["slots"])
    assert conditions == sorted(["codec_a", "codec_b", HIDDEN_REFERENCE,
                                 "anchor_lp3500", "anchor_lp7000"])
    assert [s["slot"] for s in plan["slots"]] == ["s1", "s2", "s3", "s4", "s5"]
    assert build_plan(MUSHRA, ITEM, "alice", "t1") == plan
    orders = {tuple(s["condition"] for s in build_plan(MUSHRA, ITEM, u, "t1")["slots"])
              for u in ("alice", "bob", "carol", "dave", "erin")}
    assert len(orders) > 1, "every participant got the same order"


def test_client_view_names_no_condition():
    plan = build_plan(MUSHRA, ITEM, "alice", "t1")
    view = client_view(plan, MUSHRA, lambda slot: f"/audio/{slot}")
    text = json.dumps(view)
    for secret in ("codec_a", "codec_b", HIDDEN_REFERENCE, "anchor", "a.wav", "ref.wav"):
        assert secret not in text
    assert view["reference"] == "/audio/ref" and view["require_one_at_100"] is True


def test_abx_and_ccr_plans():
    abx = {"name": "x", "method": "abx"}
    item = {"stimuli": {"orig": "o.wav", "enc": "e.wav"}}
    plan = build_plan(abx, item, "u", "i")
    a, b, x = plan["slots"]
    assert (a["slot"], b["slot"], x["slot"]) == ("A", "B", "X")
    assert x["source"] == (a if plan["x_is"] == "A" else b)["source"]
    ccr = build_plan({"name": "c", "method": "ccr"}, item, "u", "i")
    assert sorted(s["condition"] for s in ccr["slots"]) == ["enc", "orig"]


def _tone_wav(path, rate=16000, secs=1.0):
    t = np.arange(int(rate * secs)) / rate
    sig = 0.3 * np.sin(2 * np.pi * 1000 * t) + 0.3 * np.sin(2 * np.pi * 6000 * t)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((sig * 32767).astype("<i2").tobytes())


def _band_energy(path, lo, hi):
    with wave.open(path) as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float)
    spec = np.abs(np.fft.rfft(data))
    freqs = np.fft.rfftfreq(len(data), 1 / rate)
    return spec[(freqs >= lo) & (freqs <= hi)].sum()


def test_anchor_removes_content_above_the_cutoff():
    d = create_test_directory("listening_anchor")
    ref = os.path.join(d, "ref.wav")
    _tone_wav(ref)
    out = anchor_path(d, ref, 3500)
    assert out == anchor_path(d, ref, 3500), "anchor was not cached"
    assert _band_energy(out, 5900, 6100) < 0.01 * _band_energy(ref, 5900, 6100)
    assert _band_energy(out, 900, 1100) > 0.9 * _band_energy(ref, 900, 1100)
    with pytest.raises(ValueError, match="Nyquist"):
        anchor_path(d, ref, 9000)


@pytest.mark.parametrize("scheme,match", [
    ({"method": "nope"}, "method"),
    ({"method": "acr", "anchors": [3500]}, "mushra only"),
    ({"method": "mushra", "anchors": [100]}, "cut-offs"),
    ({"method": "mushra", "loop": "yes"}, "true or false"),
    ({"method": "acr", "scale_labels": ["a", "b"]}, "5 labels"),
    ({"method": "mushra", "scale_labels": ["a"] * 5}, "acr, dcr and ccr"),
])
def test_config_validation(scheme, match):
    with pytest.raises(ConfigValidationError, match=match):
        _validate_listening_test(scheme, "annotation_schemes[0]")


def _ctx(out, schemes, answers):
    items = {"t1": ITEM, "t2": dict(ITEM, id="t2")}
    anns = [{"user_id": u, "instance_id": i, "labels": {s: {s: json.dumps(a)}}}
            for (u, i, s, a) in answers]
    return ExportContext(config={"annotation_schemes": schemes}, annotations=anns,
                         items=items, schemas=schemes, output_dir=out)


def _rating_for(plan, condition, score_by_condition):
    return {s["slot"]: score_by_condition[s["condition"]] for s in plan["slots"]}


def test_export_maps_slots_to_conditions_and_screens():
    out = create_test_directory("listening_export")
    answers = []
    for user, ref_score in (("good", 100), ("careless", 40)):
        for iid in ("t1", "t2"):
            plan = build_plan(MUSHRA, ITEM, user, iid)
            scores = {"codec_a": 70, "codec_b": 50, HIDDEN_REFERENCE: ref_score,
                      "anchor_lp3500": 20, "anchor_lp7000": 45}
            answers.append((user, iid, "q", {"ratings": _rating_for(plan, None, scores)}))
    res = ListeningTestExporter().export(_ctx(out, [MUSHRA], answers), out)
    assert res.success, res.errors
    rows = list(csv.DictReader(open(os.path.join(out, "listening_ratings.csv"))))
    assert {r["score"] for r in rows if r["condition"] == "codec_a"} == {"70"}
    summary = {r["condition"]: r for r in csv.DictReader(open(os.path.join(out, "listening_summary.csv")))}
    assert float(summary["codec_b"]["mean"]) == 50.0 and summary["codec_b"]["n"] == "4"
    screen = {r["user_id"]: r for r in csv.DictReader(open(os.path.join(out, "listening_screening.csv")))}
    assert screen["good"]["excluded"] == "0"
    assert screen["careless"]["excluded"] == "1" and "hidden reference" in screen["careless"]["reason"]


def test_export_abx_and_acr():
    out = create_test_directory("listening_export_abx")
    abx = {"name": "x", "annotation_type": "listening_test", "description": "d", "method": "abx"}
    acr = {"name": "m", "annotation_type": "listening_test", "description": "d", "method": "acr"}
    answers = []
    for iid in ("t1", "t2"):
        x_is = build_plan(abx, ITEM, "u", iid)["x_is"]
        answers.append(("u", iid, "x", {"choice": x_is}))
        answers.append(("u", iid, "m", {"rating": 1}))     # "Good" = 4
    res = ListeningTestExporter().export(_ctx(out, [abx, acr], answers), out)
    assert res.success
    abx_rows = list(csv.DictReader(open(os.path.join(out, "listening_abx.csv"))))
    assert abx_rows[0]["correct"] == "2" and abx_rows[0]["proportion"] == "1.0"
    acr_rows = [r for r in csv.DictReader(open(os.path.join(out, "listening_ratings.csv")))
                if r["schema"] == "m"]
    assert {r["score"] for r in acr_rows} == {"4"} and {r["condition"] for r in acr_rows} == {"codec_a"}


def test_malformed_items_are_named():
    """Audit 96 L10: a missing reference, too few stimuli, or a stimulus named
    like a condition Potato adds used to lose slots silently."""
    from potato.listening.checks import item_problems
    mushra = {"name": "q", "method": "mushra"}
    items = [("ok", {"reference": "/media/r.wav", "stimuli": {"a": "/media/a.wav"}}),
             ("noref", {"stimuli": {"a": "/media/a.wav"}}),
             ("clash", {"reference": "/media/r.wav",
                        "stimuli": {"hidden_reference": "/media/x.wav"}})]
    problems = " ".join(item_problems(mushra, items))
    assert "no reference" in problems and "noref" in problems
    assert "hidden_reference" in problems and "clash" in problems and " ok" not in problems
    abx = {"name": "x", "method": "abx"}
    assert "needs 2" in " ".join(item_problems(abx, [("one", {"stimuli": {"a": "/m/a.wav"}})]))
