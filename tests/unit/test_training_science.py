"""Training group 6, science: molecules (rdkit-property), spectra (peak-cnn),
signals (signal-cnn) and robot episodes (episode-model). Each project is
built from the answers the schemes store, through build_bundle, and the
trainers run end to end through the worker."""

import copy
import json
import math
import os
import random

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle, detect_modality, guess_modality
from potato.training.evaluation import headline_of, score_split
from potato.training.events import EXIT_OK
from potato.training.science_metrics import score_episodes, score_intervals, score_peaks
from tests.unit.test_training_trainers import _context, _predictions, _run, _spec

HAVE = __import__("importlib").util.find_spec
needs_numpy = pytest.mark.skipif(not HAVE("numpy"), reason="numpy absent")
needs_torch = pytest.mark.skipif(not all(HAVE(m) for m in ("torch", "numpy")),
                                 reason="torch/numpy absent")
needs_rdkit = pytest.mark.skipif(not all(HAVE(m) for m in ("rdkit", "sklearn", "numpy")),
                                 reason="rdkit absent")


def _blob(name, answer):
    """A blob scheme's stored value: the JSON under the scheme's own name."""
    return {name: json.dumps(answer)}


# ================================================================ spectra

PEAKS = {"annotation_type": "peak_picking", "name": "peaks", "description": "",
         "viewer_field": "spectrum"}
SPECTRUM_DISPLAY = {"instance_display": {"fields": [
    {"key": "spectrum", "type": "spectrum", "display_options": {"prepick": True}}]}}


def gaussian_spectrum(rng, n_points=1500, n_peaks=None):
    xs = [i * 10.0 / (n_points - 1) for i in range(n_points)]
    centres = sorted(rng.uniform(0.6, 9.4) for _ in range(n_peaks or rng.randint(1, 3)))
    ys = []
    for x in xs:
        y = 0.02 * x + rng.gauss(0, 0.01)
        for c in centres:
            y += math.exp(-0.5 * ((x - c) / 0.04) ** 2)
        ys.append(y)
    return {"x": xs, "y": ys, "x_units": "PPM"}, centres


def peak_answer(centres, rejected=()):
    return {"viewer": "spectrum",
            "items": [{"kind": "peak", "x": round(c, 4), "source": "auto"} for c in centres],
            "rejected": list(rejected)}


def spectrum_project(tmp, n=30, seed=0, file_every=0):
    rng = random.Random(seed)
    items, annotations = {}, []
    for i in range(n):
        iid = "s%02d" % i
        spectrum, centres = gaussian_spectrum(rng)
        if file_every and i % file_every == 0:
            path = tmp / "media" / ("s%02d.csv" % i)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x,y\n" + "\n".join("%f,%f" % xy for xy in
                                                 zip(spectrum["x"], spectrum["y"])))
            items[iid] = {"id": iid, "spectrum": "media/s%02d.csv" % i}
        else:
            items[iid] = {"id": iid, "spectrum": spectrum}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"peaks": _blob("peaks", peak_answer(centres))}})
    config, context = _context(tmp, [PEAKS], items, annotations)
    config.update(copy.deepcopy(SPECTRUM_DISPLAY))
    return config, context


def test_a_peak_answer_trains_on_every_peak_it_kept():
    from potato.training.science import peaks_target
    answer = {"items": [{"kind": "peak", "x": 2.04, "source": "auto"},
                        {"kind": "peak", "x": 7.26, "source": "manual",
                         "fields": {"label": "CHCl3"}},
                        {"kind": "region", "from": 1, "to": 2}],
              "rejected": [0.92]}
    target = peaks_target(_blob("p", answer))
    assert target == {"peaks": [{"x": 2.04}, {"x": 7.26, "label": "CHCl3"}],
                      "rejected": [0.92]}
    # Every suggestion turned down: a spectrum with no peaks is an answer.
    assert peaks_target(_blob("p", {"items": [], "rejected": [1.0]}))["peaks"] == []
    assert peaks_target(_blob("p", {"items": []})) is None


@needs_numpy
def test_spectra_rows_carry_the_inline_spectrum_or_link_the_file(tmp_path):
    config, context = spectrum_project(tmp_path, n=4, file_every=2)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["peaks"],
                                    split_spec={"train": 1.0})
    assert bundle.manifest["modality"] == "spectrum"
    assert bundle.manifest["schemas"][0]["kind"] == "peaks"
    rows = {r["instance_id"]: r for r in bundle.read_split("train")}
    assert os.path.exists(os.path.join(bundle.root, "media", rows["s00"]["media"]))
    assert rows["s00"]["media_source"] == "media/s00.csv"
    assert "inline" in rows["s01"]["science"] and "media" not in rows["s01"]
    assert stats.n_media_linked == 2
    names = [t.name for t in registry.trainers_for_schema(PEAKS, "spectrum")]
    assert names == ["peak-cnn"]


def test_peaks_are_matched_one_to_one_within_the_tolerance():
    gold = [{"peaks": [{"x": 1.0}, {"x": 2.0}, {"x": 3.0}]}]
    # 1.01 matches 1.0; 2.4 is too far; two guesses near 3.0 match it once.
    guess = [{"peaks": [{"x": 1.01}, {"x": 2.4}, {"x": 2.99}, {"x": 3.02}],
              "tolerance": 0.05}]
    metrics = score_peaks(gold, guess)
    assert metrics["precision"] == pytest.approx(2 / 4)
    assert metrics["recall"] == pytest.approx(2 / 3)
    assert metrics["mean_offset"] == pytest.approx(0.01)
    # Without a stated tolerance, 0.5% of the spectrum's x range.
    wide = score_peaks(gold, [{"peaks": [{"x": 1.08}], "x_range": [0, 10]}])
    assert wide["recall"] == 0.0
    near = score_peaks(gold, [{"peaks": [{"x": 1.08}], "x_range": [0, 100]}])
    assert near["recall"] == pytest.approx(1 / 3)
    # A peak predicted on a spectrum the annotator said has none is a false alarm.
    empty = score_peaks([{"peaks": []}], [{"peaks": [{"x": 5.0}], "x_range": [0, 10]}])
    assert empty["precision"] == 0.0 and empty["n_predicted_peaks"] == 1.0


@needs_torch
def test_peak_cnn_learns_gaussian_peaks_and_suggests_them_back(tmp_path):
    config, context = spectrum_project(tmp_path, n=30, file_every=5)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["peaks"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "peak-cnn", "peaks",
                 {"epochs": 25, "batch_size": 4, "length": 1024, "width": 16, "depth": 6,
                  "learning_rate": 3e-3, "warmup_ratio": 0.0, "min_instances": 5,
                  "patience": 25})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith(" f1"), metrics
    assert metrics["heldout_score"] > 0.7, metrics
    payload = _predictions(spec)[0]["payload"]
    assert payload["source"] == "model" and payload["peaks"]
    assert all(0 <= p["x"] <= 10 and 0 <= p["confidence"] <= 1 for p in payload["peaks"])


# ================================================================ signals

def signal_scheme(mode):
    return {"annotation_type": "interval_label", "name": "stage", "description": "",
            "signal_field": "signal", "mode": mode, "epoch_length": 2,
            "labels": [{"name": "slow"}, {"name": "fast"}, {"name": "blink", "kind": "event"}]}


SIGNAL_DISPLAY = {"instance_display": {"fields": [
    {"key": "signal", "type": "time_series", "display_options": {"channels": ["Fz", "Cz"]}}]}}


def sine_recording(rng, labels, rate=50, epoch=2.0, bursts=None):
    """Two channels; each epoch a slow (2 Hz) or fast (9 Hz) sine. With
    *bursts*, noise with 10 Hz bursts at the given (start, end) seconds."""
    data = {"Fz": [], "Cz": [], "O1": []}
    total = len(labels) * epoch if labels else 40.0
    for k in range(int(total * rate)):
        t = k / rate
        if bursts is not None:
            on = any(a <= t < b for a, b in bursts)
            v = (math.sin(2 * math.pi * 10 * t) if on else 0.0) + rng.gauss(0, 0.2)
        else:
            freq = 2.0 if labels[int(t // epoch)] == "slow" else 9.0
            v = math.sin(2 * math.pi * freq * t) + rng.gauss(0, 0.2)
        data["Fz"].append(v)
        data["Cz"].append(-v + rng.gauss(0, 0.1))
        data["O1"].append(rng.gauss(0, 1))
    return {"sampling_rate": rate, "channels": [{"name": n, "unit": "uV", "data": d}
                                                for n, d in data.items()]}


def signal_project(tmp, mode, n=8, seed=0):
    rng = random.Random(seed)
    scheme = signal_scheme(mode)
    items, annotations = {}, []
    for i in range(n):
        iid = "r%d" % i
        if mode == "epoch":
            labels = [rng.choice(["slow", "fast"]) for _ in range(10)]
            items[iid] = {"id": iid, "signal": sine_recording(rng, labels)}
            answer = {"intervals": [{"start": 2.0 * k, "end": 2.0 * k + 2, "label": lab,
                                     "channel": None} for k, lab in enumerate(labels)],
                      "events": [{"time": 1.0, "label": "blink", "channel": None}]}
        else:
            bursts = sorted((s, s + rng.uniform(2, 4)) for s in rng.sample(range(2, 36, 6), 3))
            items[iid] = {"id": iid, "signal": sine_recording(rng, [], bursts=bursts)}
            answer = {"intervals": [{"start": a, "end": b, "label": "fast", "channel": None}
                                    for a, b in bursts], "events": []}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"stage": _blob("stage", answer)}})
    config, context = _context(tmp, [scheme], items, annotations)
    config.update(copy.deepcopy(SIGNAL_DISPLAY))
    return config, context


def test_an_interval_answer_trains_on_interval_labels_not_events():
    from potato.training.science import intervals_target
    scheme = signal_scheme("epoch")
    answer = {"intervals": [{"start": 2, "end": 4, "label": "fast"},
                            {"start": 0, "end": 2, "label": "slow"},
                            {"start": 4, "end": 4, "label": "slow"},
                            {"start": 6, "end": 8, "label": "gone"}],
              "events": [{"time": 1, "label": "blink"}]}
    target = intervals_target(scheme, _blob("stage", answer))
    assert target == {"mode": "epoch", "epoch_length": 2.0, "intervals": [
        {"start": 0.0, "end": 2.0, "label": "slow"},
        {"start": 2.0, "end": 4.0, "label": "fast"}]}


@needs_numpy
def test_signal_rows_carry_the_display_channels_and_wfdb_siblings_are_linked(tmp_path):
    config, context = signal_project(tmp_path, "epoch", n=2)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["stage"],
                                split_spec={"train": 1.0})
    assert bundle.manifest["modality"] == "signal"
    row = next(bundle.read_split("train"))
    assert row["science"]["options"]["channels"] == ["Fz", "Cz"]
    assert bundle.manifest["labels"]["stage"] == ["fast", "slow"]
    # A WFDB header is linked with the record's other files beside it.
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    for name in ("100.hea", "100.dat", "100.atr", "101.dat"):
        (media / name).write_text("x")
    items = {"w": {"id": "w", "signal": "media/100.hea"}}
    answer = {"intervals": [{"start": 0, "end": 2, "label": "slow"}], "events": []}
    cfg, ctx = _context(tmp_path, [signal_scheme("epoch")], items, [
        {"instance_id": "w", "user_id": "a", "labels": {"stage": _blob("stage", answer)}}])
    cfg.update(copy.deepcopy(SIGNAL_DISPLAY))
    wfdb, _, _ = build_bundle(ctx, str(tmp_path / "w"), ["stage"], split_spec={"train": 1.0})
    row = next(wfdb.read_split("train"))
    folder = os.path.dirname(os.path.join(wfdb.root, "media", row["media"]))
    assert sorted(os.listdir(folder)) == ["100.atr", "100.dat", "100.hea"]


def test_intervals_are_scored_per_epoch_or_as_intervals():
    epoch_gold = [{"mode": "epoch", "epoch_length": 30, "intervals": [
        {"start": 0, "end": 60, "label": "N2"}, {"start": 60, "end": 90, "label": "REM"}]}]
    guess = [{"intervals": [{"start": 0, "end": 30, "label": "N2"},
                            {"start": 30, "end": 90, "label": "REM"}]}]
    metrics = score_intervals(epoch_gold, guess)
    assert metrics["n_epochs"] == 3.0 and metrics["accuracy"] == pytest.approx(2 / 3)
    assert headline_of("intervals", metrics) == "macro_f1"
    free_gold = [{"mode": "free", "intervals": [{"start": 0, "end": 10, "label": "a"},
                                                {"start": 20, "end": 30, "label": "a"}]}]
    free = score_intervals(free_gold, [{"intervals": [
        {"start": 1, "end": 10, "label": "a"}, {"start": 20, "end": 21, "label": "a"}]}])
    assert free["interval_precision"] == 0.5 and free["interval_recall"] == 0.5
    assert headline_of("intervals", free) == "interval_f1"


@needs_torch
def test_signal_cnn_stages_epochs(tmp_path):
    config, context = signal_project(tmp_path, "epoch", n=10)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["stage"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "signal-cnn", "stage",
                 {"epochs": 12, "batch_size": 16, "rate": 50.0, "width": 8, "depth": 3,
                  "learning_rate": 3e-3, "warmup_ratio": 0.0, "min_instances": 3,
                  "patience": 12})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith(" macro_f1"), metrics
    assert metrics["heldout_score"] > 0.85, metrics
    payload = _predictions(spec)[0]["payload"]
    epochs = payload["intervals"]
    assert len(epochs) == 10 and all(iv["end"] - iv["start"] == 2.0 for iv in epochs)
    assert {iv["label"] for iv in epochs} <= {"slow", "fast"}
    assert all(iv["source"] == "model" and iv["channel"] is None for iv in epochs)
    with open(os.path.join(spec.workdir, "model_card.json")) as fh:
        card = json.load(fh)
    # The display names two channels; O1 is never read.
    assert card["channel_names"] == ["Fz", "Cz"]


@needs_torch
def test_signal_cnn_finds_free_intervals(tmp_path):
    config, context = signal_project(tmp_path, "free", n=10, seed=1)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["stage"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "signal-cnn", "stage",
                 {"epochs": 15, "batch_size": 8, "rate": 50.0, "width": 8, "depth": 3,
                  "window_s": 10.0, "windows_per_epoch": 64, "frame_s": 0.5,
                  "min_duration": 1.0, "learning_rate": 3e-3, "warmup_ratio": 0.0,
                  "min_instances": 3, "patience": 15})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith(" interval_f1"), metrics
    assert metrics["heldout_score"] > 0.6, metrics


# =============================================================== episodes

EPISODE = {"annotation_type": "episode_annotation", "name": "ep", "description": "",
           "source_field": "episode", "phases": ["reach", "grasp", "lift"],
           "outcomes": ["success", "failure"], "reward_range": [0, 1]}


def episode_project(tmp, n=12, seed=0):
    """Episodes whose gripper series says the phase: open (reach), closing
    (grasp), closed and rising (lift). A failed one never lifts."""
    rng = random.Random(seed)
    items, annotations = {}, []
    for i in range(n):
        iid = "e%02d" % i
        fps, frames = 10.0, 60 + rng.randint(0, 20)
        a, b = rng.randint(15, 25), rng.randint(35, 45)
        success = i % 3 != 0
        gripper, height = [], []
        for f in range(frames):
            gripper.append(0.0 if f < a else (min(1.0, (f - a) / (b - a)) if f < b else 1.0))
            height.append(0.0 if (f < b or not success) else (f - b) / 10.0)
        gripper = [g + rng.gauss(0, 0.03) for g in gripper]
        folder = tmp / "media" / iid
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "episode.json").write_text(json.dumps({
            "episode_id": iid, "fps": fps, "num_frames": frames,
            "series": [{"name": "gripper", "values": gripper},
                       {"name": "z", "values": height}]}))
        items[iid] = {"id": iid, "episode": "media/%s/episode.json" % iid}
        phases = [{"start": 0.0, "end": a / fps, "label": "reach"},
                  {"start": a / fps, "end": b / fps, "label": "grasp"}]
        if success:
            phases.append({"start": b / fps, "end": frames / fps, "label": "lift"})
        answer = {"phases": phases,
                  "outcome": {"result": "success" if success else "failure", "cause": ""},
                  "reward": [{"t": 0.0, "value": 0.0},
                             {"t": frames / fps, "value": 1.0 if success else 0.2}],
                  "instructions": []}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"ep": {"_data": json.dumps(answer)}}})
    return _context(tmp, [EPISODE], items, annotations)


def test_an_episode_answer_keeps_its_three_layers():
    from potato.training.science import episode_target
    answer = {"phases": [{"start": 1, "end": 2, "label": "grasp"},
                         {"start": 0, "end": 1, "label": "reach"},
                         {"start": 2, "end": 3, "label": "dance"}],
              "outcome": {"result": "success", "cause": ""},
              "reward": [{"t": 0, "value": 0}, {"t": 3, "value": 1}], "instructions": ["x"]}
    target = episode_target(EPISODE, {"_data": json.dumps(answer)})
    assert [p["label"] for p in target["phases"]] == ["reach", "grasp"]
    assert target["outcome"] == "success" and len(target["reward"]) == 2
    # A one-point reward curve is no curve, and an outcome the scheme lacks none.
    only = episode_target(EPISODE, {"_data": json.dumps(
        {"phases": [], "outcome": {"result": "meh"}, "reward": [{"t": 0, "value": 1}]})})
    assert only is None


def test_episodes_are_scored_on_phases_outcome_and_reward():
    gold = [{"phases": [{"start": 0, "end": 1, "label": "reach"},
                        {"start": 1, "end": 2, "label": "grasp"}],
             "outcome": "success", "reward": [{"t": 0, "value": 0}, {"t": 2, "value": 1}]}]
    exact = score_episodes(gold, [{"phases": gold[0]["phases"],
                                   "outcome": {"result": "success"},
                                   "reward": [{"t": 0, "value": 0}, {"t": 2, "value": 1}]}])
    assert exact["phase_accuracy"] == 1.0 and exact["phase_macro_f1"] == 1.0
    assert exact["phase_segment_f1"] == 1.0 and exact["outcome_accuracy"] == 1.0
    # A phase predicted in the gap the annotator left between two phases is
    # a false alarm, though every annotated frame is right.
    extra = score_episodes(
        [{"phases": [{"start": 0, "end": 1, "label": "reach"},
                     {"start": 1.5, "end": 2, "label": "grasp"}], "outcome": None,
          "reward": []}],
        [{"phases": [{"start": 0, "end": 1.5, "label": "reach"},
                     {"start": 1.5, "end": 2, "label": "grasp"}]}])
    # reach: 10 right, 5 in the gap (precision 2/3, F1 0.8); grasp: F1 1.
    assert extra["phase_macro_f1"] == pytest.approx(0.9)
    # No phases layer: the headline falls back to the outcome.
    outcome_only = score_episodes([{"phases": [], "outcome": "success", "reward": []}],
                                  [{"outcome": "failure"}])
    assert headline_of("episode", outcome_only) == "outcome_accuracy"


@needs_torch
def test_episode_model_marks_phases_and_predicts_the_outcome(tmp_path):
    config, context = episode_project(tmp_path, n=16)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["ep"], split_seed=0)
    assert bundle.manifest["modality"] == "episode", stats.warnings
    assert bundle.manifest["labels"]["ep"] == ["grasp", "lift", "reach"]
    spec = _spec(tmp_path, config, bundle, "episode-model", "ep",
                 {"epochs": 40, "batch_size": 4, "hidden": 16, "learning_rate": 1e-2,
                  "warmup_ratio": 0.0, "min_instances": 5, "patience": 40,
                  "reward_points": 5})
    spec.params.update({"_reward_range": [0.0, 1.0]})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith(" phase_macro_f1"), metrics
    assert metrics["heldout_score"] > 0.6, metrics
    payload = _predictions(spec)[0]["payload"]
    assert payload["outcome"]["result"] in ("success", "failure")
    assert len(payload["reward"]) == 5 and all(0 <= p["value"] <= 1 for p in payload["reward"])
    from potato.server_utils.prelabel_values import prelabel_values
    stored = json.loads(prelabel_values(EPISODE, payload)["_data"])
    assert stored["phases"] == payload["phases"] and stored["instructions"] == []


def test_an_episode_prelabel_keeps_what_the_scheme_shows():
    from potato.server_utils.prelabel_values import prelabel_values
    scheme = dict(EPISODE, layers=["phases", "outcome"])
    payload = {"phases": [{"start": 0, "end": 1, "label": "reach"},
                          {"start": 1, "end": 0.5, "label": "grasp"},
                          {"start": 1, "end": 2, "label": "dance"}],
               "outcome": {"result": "success"},
               "reward": [{"t": 0, "value": 0}, {"t": 1, "value": 1}]}
    stored = json.loads(prelabel_values(scheme, payload)["_data"])
    assert stored["phases"] == [{"start": 0.0, "end": 1.0, "label": "reach"}]
    assert stored["outcome"] == {"result": "success", "cause": ""}
    assert stored["reward"] == []      # the scheme shows no reward lane
    assert prelabel_values(scheme, {"outcome": "won", "phases": []}) is None


# ============================================================== molecules

ALKANES = ["C", "CC", "CCC", "CCCC", "CCCCC", "CCCCCC", "CCCCCCC", "CCCCCCCC",
           "CC(C)C", "CC(C)CC", "CCC(C)CC", "C1CCCCC1", "C1CCCC1", "CC1CCCCC1",
           "CCCCCCCCC", "CC(C)(C)C", "CCCC(C)C", "C1CCC1", "CCCCCCCCCC", "CC(C)CCC"]
ALCOHOLS = ["CO", "CCO", "CCCO", "CCCCO", "CC(C)O", "OCCO", "CC(O)CC", "OC1CCCCC1",
            "CCCCCO", "CCCCCCO", "OCC(O)CO", "CC(C)(C)O", "OCCCO", "CCC(O)C",
            "CCCCCCCO", "OC1CCCC1", "CC(O)C(C)C", "OCCCCO", "CCCCCCCCO", "CC(C)CO"]

MOLECULE_DISPLAY = {"instance_display": {"fields": [{"key": "smiles", "type": "molecule"}]}}


def molecule_project(tmp, question="radio"):
    if question == "radio":
        scheme = {"annotation_type": "radio", "name": "group", "description": "",
                  "labels": ["alcohol", "alkane"]}
    else:
        scheme = {"annotation_type": "slider", "name": "carbons", "description": "",
                  "min_value": 0, "max_value": 12, "starting_value": 0, "step": 1}
    items, annotations = {}, []
    for n, smiles in enumerate(ALKANES + ALCOHOLS):
        iid = "m%02d" % n
        items[iid] = {"id": iid, "text": "molecule %d" % n, "smiles": smiles}
        if question == "radio":
            value = {"alcohol" if smiles in ALCOHOLS else "alkane": True}
        else:
            value = {"slider": str(smiles.count("C"))}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {scheme["name"]: value}})
    config, context = _context(tmp, [scheme], items, annotations)
    config.update(copy.deepcopy(MOLECULE_DISPLAY))
    return config, context, scheme


def test_a_question_about_a_displayed_molecule_is_a_molecule_bundle(tmp_path):
    config, context, scheme = molecule_project(tmp_path)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["group"],
                                    split_spec={"train": 1.0})
    assert bundle.manifest["modality"] == "molecule" and not stats.warnings
    row = next(r for r in bundle.read_split("train") if r["instance_id"] == "m21")
    assert row["molecule"] == "CCO"
    assert guess_modality(config, scheme, list(context.items.values())) == "molecule"
    names = {t.name for t in registry.trainers_for_schema(scheme, "molecule")}
    # The molecule trainer, and the text classifiers: the item's text is still there.
    assert "rdkit-property" in names and "sklearn-text" in names
    assert "hf-image-classification" not in names
    assert "rdkit-property" not in {t.name for t in registry.trainers_for_schema(scheme, "text")}


def test_a_drawn_structure_is_the_input_and_the_most_common_drawing_wins(tmp_path):
    chem = {"annotation_type": "chemical_structure", "name": "drawn", "description": "",
            "prefill_field": "start"}
    radio = {"annotation_type": "radio", "name": "toxic", "description": "",
             "labels": ["yes", "no"]}
    items = {"a": {"id": "a", "text": "a"}, "b": {"id": "b", "text": "b", "start": "c1ccccc1"},
             "c": {"id": "c", "text": "c"}}
    annotations = [
        {"instance_id": "a", "user_id": "u1",
         "labels": {"toxic": {"yes": True}, "drawn": {"drawn": json.dumps({"smiles": "CCO"})}}},
        {"instance_id": "a", "user_id": "u2",
         "labels": {"toxic": {"yes": True}, "drawn": {"drawn": json.dumps({"smiles": "CCO"})}}},
        {"instance_id": "a", "user_id": "u3",
         "labels": {"toxic": {"yes": True}, "drawn": {"drawn": json.dumps({"smiles": "CCN"})}}},
        {"instance_id": "b", "user_id": "u1", "labels": {"toxic": {"no": True}}},
        {"instance_id": "c", "user_id": "u1", "labels": {"toxic": {"no": True}}}]
    config, context = _context(tmp_path, [chem, radio], items, annotations)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["toxic"],
                                    split_spec={"train": 1.0}, aggregation="majority")
    rows = {r["instance_id"]: r for r in bundle.read_split("train")}
    assert rows["a"]["molecule"] == "CCO"
    # Nobody drew on b: the structure the drawing starts from.
    assert rows["b"]["molecule"] == "c1ccccc1"
    assert "molecule" not in rows["c"]
    assert any("1 item(s) have no structure in scheme 'drawn'" in w for w in stats.warnings)


def test_a_molfile_keeps_its_header_and_a_structure_file_is_read(tmp_path):
    from potato.training.science import molecule_text
    molfile = "\n  RDKit          2D\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n" \
              "    0.0000    0.0000    0.0000 C   0  0\nM  END\n"
    assert molecule_text(molfile, str(tmp_path)) == molfile
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "ethanol.smi").write_text("CCO ethanol\n")
    assert molecule_text("media/ethanol.smi", str(tmp_path)).split()[0] == "CCO"
    outside = tmp_path.parent / "outside.smi"
    outside.write_text("CCC\n")
    assert molecule_text(str(outside), str(tmp_path)) is None


@needs_rdkit
def test_rdkit_property_tells_alcohols_from_alkanes(tmp_path):
    config, context, _ = molecule_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["group"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "rdkit-property", "group", {"min_instances": 5})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["heldout_score"] >= 0.8, result["metrics"]
    payload = _predictions(spec)[0]["payload"]
    assert payload["label"] in ("alcohol", "alkane") and 0 < payload["confidence"] <= 1


@needs_rdkit
def test_rdkit_property_regresses_a_slider_onto_its_steps(tmp_path):
    from potato.training.trainers.rdkit_property import RDKitPropertyTrainer
    config, context, scheme = molecule_project(tmp_path, question="slider")
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["carbons"], split_seed=0)
    params = {"min_instances": 5, "model": "ridge", "alpha": 0.1}
    params.update(RDKitPropertyTrainer.server_params(config, ["carbons"], params))
    assert params["_scale"] == {"min": 0.0, "max": 12.0, "step": 1.0}
    spec = _spec(tmp_path, config, bundle, "rdkit-property", "carbons", params)
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["heldout_metric"].endswith(" accuracy"), result["metrics"]
    assert any(k.endswith("_mae") for k in result["metrics"]), result["metrics"]
    for record in _predictions(spec):
        value = record["payload"]["label"]
        # The page's slider value: "7", a step on the scale.
        assert isinstance(value, str) and value.isdigit() and 0 <= int(value) <= 12


@needs_rdkit
def test_an_unparseable_structure_is_counted_not_trained_on(tmp_path):
    config, context, _ = molecule_project(tmp_path)
    context.items["m00"]["smiles"] = "C1CC(("
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["group"],
                                split_spec={"train": 1.0})
    spec = _spec(tmp_path, config, bundle, "rdkit-property", "group", {"min_instances": 5})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["n_unparseable"] == 1.0


def test_detect_modality_needs_most_rows_to_carry_a_molecule():
    rows = [{"molecule": "CCO"}] * 7 + [{}] * 3
    assert detect_modality([{"annotation_type": "radio"}], rows) == "text"
    assert detect_modality([{"annotation_type": "radio"}], rows[:7] + rows[-1:]) == "molecule"


# ======================================================= prelabel paths

@needs_numpy
def test_model_peaks_are_suggestions_after_the_item_s_own():
    from potato.science.spectra import Spectrum
    from potato.server_utils.displays.spectrum_display import (model_peaks_by_field,
                                                               suggestions_for)
    spectrum = Spectrum(x=[0, 1, 2, 3, 4], y=[0, 5, 0, 3, 0])
    config = {"annotation_schemes": [PEAKS]}
    by_field = model_peaks_by_field(config, {"peaks": json.dumps(
        {"peaks": [{"x": 3.0, "confidence": 0.7}, {"x": "nan"}, {"x": 9.0}],
         "source": "model"})})
    assert by_field == {"spectrum": [{"x": 3.0, "confidence": 0.7}, {"x": 9.0}]}
    options = {"prepick": True}
    shown, method = suggestions_for(spectrum, None, options, "max", by_field["spectrum"])
    # 9.0 is past the spectrum's end; the rest is the model's, marked as such.
    assert method == "model"
    assert shown == [{"x": 3.0, "y": 3.0, "source": "model", "confidence": 0.7}]
    # Under auto, the item's own peaks come first; without the model, the detector.
    assert suggestions_for(spectrum, [1.0], options, "max", by_field["spectrum"])[1] == "item"
    assert suggestions_for(spectrum, None, options, "max", None)[1] == "detect"
    assert suggestions_for(spectrum, None, {"prepick": {"method": "model"}}, "max",
                           None) == ([], "model")


def test_an_accepted_model_peak_is_a_valid_stored_peak():
    from potato.server_utils.displays.spectrum_display import SpectrumDisplay
    display = SpectrumDisplay()
    assert display.validate_item({"kind": "peak", "x": 1.0, "source": "model"}, "i") == []
    assert display.validate_item({"kind": "peak", "x": 1.0, "source": "guess"}, "i")
    assert SpectrumDisplay().validate_options(
        dict(SpectrumDisplay.optional_fields, prepick={"method": "model"}), "f") == []


def test_the_display_sees_model_peaks_only_on_its_own_spectrum_field():
    from potato.server_utils.instance_display import InstanceDisplayRenderer
    renderer = InstanceDisplayRenderer.__new__(InstanceDisplayRenderer)
    record = {"_model_peaks": {"spectrum": [{"x": 1.0}]}}
    field = renderer._with_model_peaks({"key": "spectrum", "type": "spectrum"}, record)
    assert field["_model_peaks"] == [{"x": 1.0}]
    other = {"key": "other", "type": "spectrum"}
    assert renderer._with_model_peaks(other, record) is other
    text = {"key": "spectrum", "type": "text"}
    assert renderer._with_model_peaks(text, record) is text


@needs_numpy
def test_model_intervals_keep_the_scheme_s_interval_labels():
    from potato.science.signal_store import model_intervals
    from potato.science.signals import from_inline
    rec = from_inline({"sampling_rate": 10, "channels": [
        {"name": "Fz", "data": [0.0] * 100}, {"name": "Cz", "data": [0.0] * 100}]})
    scheme = signal_scheme("free")
    payload = json.dumps({"intervals": [
        {"start": 0, "end": 2, "label": "fast", "channel": "Cz", "confidence": 0.9},
        {"start": 2, "end": 3, "label": "fast", "channel": "T7"},
        {"start": 3, "end": 3, "label": "slow"},
        {"start": 4, "end": 5, "label": "blink"},
        {"start": 5, "end": 6, "label": "nope"}]})
    assert model_intervals(scheme, payload, rec) == [
        {"start": 0.0, "end": 2.0, "label": "fast", "channel": "Cz", "source": "model"},
        {"start": 2.0, "end": 3.0, "label": "fast", "channel": None, "source": "model"}]
    assert model_intervals(scheme, "not json", rec) == []
