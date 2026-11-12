"""Calibrating and fine-tuning decision models (Jev, OpenJev, Laya).

The calibration math is checked by hand, the endpoint is checked to apply a
calibration file, and the ``decision-calibrate`` trainer runs end to end
against a stub decision model, so nothing calls a real service. Laya's own
fine-tuning needs its 800 MB checkpoint, so only the data it is given is
checked here.
"""

import json
import os
import random
import types

import pytest

from potato.ai.decision_calibration import (apply_calibration,
                                            calibrate_distribution,
                                            expected_calibration_error,
                                            fit_question,
                                            negative_log_likelihood)
from potato.ai.decision_endpoint import (DecisionAnswer, DecisionModelEndpoint,
                                         DecisionQuestion)
from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from potato.training.trainers import _decision_common as dc
from tests.unit.test_training_trainers import _context, _predictions, _run, _spec


def overconfident_pairs(n=400, seed=0):
    """A model that says 0.95 for its pick and is right 70% of the time."""
    rng = random.Random(seed)
    pairs = []
    for _ in range(n):
        gold = rng.choice("abc")
        pick = gold if rng.random() < 0.7 else rng.choice(
            [o for o in "abc" if o != gold])
        pairs.append(({o: 0.95 if o == pick else 0.025 for o in "abc"}, gold))
    return pairs


class TestCalibration:
    def test_temperature_fixes_overconfidence_without_changing_picks(self):
        pairs = overconfident_pairs()
        entry = fit_question(pairs, "abc", "temperature")
        assert entry["temperature"] > 1.5
        assert expected_calibration_error(pairs, entry) < \
            expected_calibration_error(pairs) / 3
        assert negative_log_likelihood(pairs, entry) < negative_log_likelihood(pairs)
        for probs, _ in pairs[:50]:
            calibrated = calibrate_distribution(probs, entry)
            assert max(calibrated, key=calibrated.get) == max(probs, key=probs.get)

    def test_a_bias_can_move_the_pick_toward_an_underpredicted_option(self):
        # The model never says "b", but it is less sure about the items
        # annotators call "b": an offset is all it needs.
        pairs = [({"a": 0.8, "b": 0.2}, "a")] * 30 + [({"a": 0.55, "b": 0.45}, "b")] * 30
        plain = fit_question(pairs, "ab", "temperature")
        biased = fit_question(pairs, "ab", "temperature+bias", l2=0.0)
        assert plain["bias"]["b"] == 0.0
        assert biased["fitted"] and biased["bias"]["b"] > 0
        assert negative_log_likelihood(pairs, biased) < \
            negative_log_likelihood(pairs, plain)
        picks = {max(p, key=p.get) for p in (
            calibrate_distribution(probs, biased) for probs, _ in pairs)}
        assert picks == {"a", "b"}

    def test_too_little_data_is_the_identity(self):
        entry = fit_question([({"a": 0.9, "b": 0.1}, "a")], "ab")
        assert (entry["temperature"], entry["fitted"]) == (1.0, False)

    def test_a_model_with_no_mistakes_is_not_sharpened_to_certainty(self):
        """Audit 98 D3: 37 of 37 right fitted T=0.05, and every later
        answer, "I am not sure whether I liked it" included, read 1.0."""
        pairs = [({"pos": 0.97, "neg": 0.03}, "pos")] * 20 + \
            [({"pos": 0.04, "neg": 0.96}, "neg")] * 17
        entry = fit_question(pairs, ["pos", "neg"])
        assert entry["fitted"] is False and entry["temperature"] == 1.0
        assert "wrong" in entry["note"]
        unsure = calibrate_distribution({"pos": 0.6, "neg": 0.4}, entry)
        assert unsure["pos"] == pytest.approx(0.6)

    def test_answers_are_recalibrated_and_others_pass_through(self):
        answer = DecisionAnswer(id="s", value="a", confidence=0.95,
                                probabilities={"a": 0.95, "b": 0.05})
        yes_no = DecisionAnswer(id="n", value=True, confidence=0.9,
                                probabilities={"yes": 0.9, "no": 0.1})
        other = DecisionAnswer(id="t", value="x", confidence=0.8,
                               probabilities={"x": 0.8, "y": 0.2})
        out = apply_calibration([answer, yes_no, other], {"questions": {
            "s": {"temperature": 4.0}, "n": {"temperature": 4.0}}})
        assert out[0].value == "a" and out[0].confidence < 0.7
        assert out[1] is yes_no and out[2] is other


class _StubDecision(DecisionModelEndpoint):
    """Answers every question with fixed, overconfident probabilities."""

    def _initialize_client(self):
        pass

    def _get_default_model(self):
        return "stub"

    def _decide_raw(self, state, questions):
        q = questions[0]
        pick = "positive" if "good" in state else "negative"
        return {"answers": {q.id: {"type": "choice", "choice": pick,
                                   "probabilities": {o: 0.97 if o == pick else 0.03
                                                     for o in q.options}}}}

    def health_check(self):
        return True


class TestEndpointAppliesTheCalibration:
    def test_ai_config_calibration_is_applied(self, tmp_path):
        path = tmp_path / "calibration.json"
        path.write_text(json.dumps({"v": 1, "method": "temperature",
                                    "questions": {"s": {"temperature": 3.0}}}))
        q = [DecisionQuestion(id="s", kind="choice", text="?",
                              options=["positive", "negative"])]
        raw = _StubDecision({"ai_config": {}}).decide("good film", q)[0]
        calibrated = _StubDecision({"ai_config": {"calibration": str(path)}}
                                   ).decide("good film", q)[0]
        assert raw.confidence == pytest.approx(0.97)
        assert calibrated.value == "positive"
        assert calibrated.confidence == pytest.approx(
            calibrate_distribution({"positive": 0.97, "negative": 0.03},
                                   {"temperature": 3.0})["positive"])

    def test_a_missing_file_fails_loudly(self, tmp_path):
        from potato.ai.ai_endpoint import AIEndpointRequestError
        q = [DecisionQuestion(id="s", kind="choice", text="?",
                              options=["positive", "negative"])]
        endpoint = _StubDecision({"ai_config": {"calibration": str(tmp_path / "x")}})
        with pytest.raises(AIEndpointRequestError):
            endpoint.decide("good", q)


class TestFindingTheDecisionModel:
    CONFIG = {
        "labeling_engine": {"enabled": False, "sources": [
            {"id": "gpt", "kind": "llm", "endpoint_type": "openai"},
            {"id": "jev", "kind": "decision", "endpoint_type": "systemone",
             "base_url": "https://api.typesafe.ai", "model": "jev-latest",
             "api_key": "sk-secret", "prompt": "Classify.",
             "options": {"max_options": 52, "state_key": ""}}]},
        "solo_mode": {"labeling_models": [
            {"endpoint_type": "laya", "model": "convaiinnovations/laya",
             "device": "cuda"}]},
    }

    def test_engine_sources_and_solo_models_are_found(self):
        found = dc.decision_endpoints(self.CONFIG)
        assert [e["source"] for e in found] == ["jev", "solo_mode"]
        assert found[0]["ai_config"] == {"model": "jev-latest",
                                         "base_url": "https://api.typesafe.ai",
                                         "max_options": 52, "state_key": ""}
        assert found[1]["ai_config"]["device"] == "cuda"
        assert dc.pick_endpoint(self.CONFIG, "solo_mode")["endpoint_type"] == "laya"
        assert dc.pick_endpoint(self.CONFIG, "nope") is None

    def test_the_key_goes_to_the_environment_never_to_the_spec(self):
        from potato.training.trainers.decision_calibrate import \
            DecisionCalibrateTrainer as T
        params = {"source": "jev"}
        spec_params = T.server_params(self.CONFIG, ["s"], params)
        assert "sk-secret" not in json.dumps(spec_params)
        # An option whose name contains "key" is not a secret.
        assert spec_params["_endpoint"]["ai_config"]["state_key"] == ""
        assert T.run_environment(self.CONFIG, params) == {
            dc.API_KEY_ENV: "sk-secret"}

    def test_a_likert_target_matches_its_option_by_value(self):
        assert dc.option_for(3.0, ["1", "2", "3"]) == "3"
        assert dc.option_for("negative", ["positive", "negative"]) == "negative"
        assert dc.option_for("neutral", ["positive", "negative"]) is None


class TestLocalOnly:
    def test_a_remote_backend_is_refused(self, tmp_path):
        from potato.training.manager import TrainingManager
        config = {"task_dir": str(tmp_path), "annotation_schemes": [
                      {"annotation_type": "radio", "name": "s",
                       "labels": ["a", "b"]}],
                  "labeling_engine": {"enabled": False, "sources": [
                      {"id": "jev", "kind": "decision",
                       "endpoint_type": "systemone",
                       "base_url": "http://example.invalid"}]},
                  "model_training": {"enabled": True, "backends": {
                      "gpu": {"type": "ssh", "host": "example.invalid"}}}}
        outcome = TrainingManager(config).start_run(
            "decision-calibrate", ["s"], backend="gpu")
        assert not outcome["started"]
        assert "local backend" in outcome["error"]


def sentiment_items(tmp, n=120):
    rng = random.Random(1)
    items, annotations = {}, []
    for i in range(n):
        good = rng.random() < 0.5
        iid = "r%03d" % i
        items[iid] = {"id": iid, "text": "a %s film %d" % ("good" if good else "bad", i)}
        # The stub is right 80% of the time.
        right = rng.random() < 0.8
        label = ("positive" if good else "negative") if right else \
            ("negative" if good else "positive")
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"sentiment": {label: True}}})
    scheme = {"annotation_type": "radio", "name": "sentiment",
              "description": "Positive or negative?",
              "labels": ["positive", "negative"]}
    return _context(tmp, [scheme], items, annotations)


class TestDecisionCalibrateRun:
    def test_end_to_end_against_a_stub_model(self, tmp_path, monkeypatch):
        from potato.training.trainers import decision_calibrate
        monkeypatch.setattr(decision_calibrate, "_make_endpoint",
                            lambda params: _StubDecision({"ai_config": {}}))
        config, context = sentiment_items(tmp_path)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["sentiment"], split_seed=1,
                                    include_unlabeled=True)
        params = {"min_instances": 10,
                  "_schemes": {"sentiment": config["annotation_schemes"][0]},
                  "_endpoint": {"source": "stub", "endpoint_type": "systemone",
                                "ai_config": {}, "prompt": None}}
        spec = _spec(tmp_path, config, bundle, "decision-calibrate",
                     "sentiment", params)
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        metrics = result["metrics"]
        # 0.97 confidence on an 80% model: calibration lowers it.
        calibration = json.load(open(os.path.join(spec.workdir,
                                                  "calibration.json")))
        assert calibration["questions"]["sentiment"]["temperature"] > 1.0
        assert metrics["val_ece_after"] < metrics["val_ece_before"]
        assert metrics["heldout_metric"] == "val macro_f1"
        prediction = _predictions(spec)[0]["payload"]
        assert prediction["label"] in ("positive", "negative")
        assert prediction["confidence"] < 0.97


class TestLayaData:
    def test_rows_ask_the_endpoints_question(self, tmp_path):
        from potato.training.trainers.laya_finetune import LayaFinetuneTrainer
        config, context = sentiment_items(tmp_path, n=8)
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["sentiment"],
                                    split_spec={"train": 1.0})
        question = dc.question_for(config["annotation_schemes"][0], "")
        schema = types.SimpleNamespace(name="sentiment")
        rows = LayaFinetuneTrainer()._rows(bundle, "train", schema, question)
        assert len(rows) == 8
        row = rows[0]
        assert row["state"] == {"text": row["state"]["text"]}
        assert row["questions"]["sentiment"]["type"] == "choice"
        assert row["expected"]["sentiment"] in ("positive", "negative")

    def test_a_rating_is_trained_as_its_level(self, tmp_path):
        from potato.training.trainers.laya_finetune import LayaFinetuneTrainer
        scheme = {"annotation_type": "likert", "name": "q", "description": "How?",
                  "size": 5, "min_label": "low", "max_label": "high"}
        items = {"i": {"id": "i", "text": "x"}}
        annotations = [{"instance_id": "i", "user_id": "a",
                        "labels": {"q": {"4": "4"}}}]
        config, context = _context(tmp_path, [scheme], items, annotations)
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["q"],
                                    split_spec={"train": 1.0})
        question = dc.question_for(scheme, "")
        rows = LayaFinetuneTrainer()._rows(
            bundle, "train", types.SimpleNamespace(name="q"), question)
        assert question.kind == "score"
        assert rows[0]["expected"] == {"q": 3}


# ---------------------------------------------------------- OpenJev (wev)

FAKE_WEV = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "helpers", "fake_wev")


class TestOpenJevHelpers:
    def test_wev_log_lines(self):
        from potato.training.trainers.openjev_finetune import parse_log_line
        step = parse_log_line("ep 1 step 9 batch 3/23 loss 0.1905 lr 2.0e-10 "
                              "5.11 rec/s peak 15.2GB elapsed 2.4m")
        assert step == {"kind": "step", "epoch": 1, "step": 9, "batch": 3,
                        "batches": 23, "loss": 0.1905}
        dev = parse_log_line('== epoch 0 dev[s]: {"n": 39, "s": {"accuracy": 0.92}}')
        assert dev["result"]["s"]["accuracy"] == 0.92
        assert parse_log_line("Loading weights: 100%") is None

    def test_rows_are_requests_with_the_answer(self):
        from potato.ai.decision_endpoint import build_systemone_questions
        from potato.training.trainers.openjev_finetune import wev_rows
        scheme = {"annotation_type": "likert", "name": "q", "description": "How?",
                  "size": 5, "min_label": "low", "max_label": "high"}
        question = dc.question_for(scheme, "")
        rows = wev_rows([{"instance_id": "i", "text": "x", "targets": {"q": 4.0}},
                         {"instance_id": "j", "text": " ", "targets": {"q": 2.0}}],
                        "q", question, build_systemone_questions([question]))
        assert len(rows) == 1
        assert rows[0]["request"]["state"] == {"text": "x"}
        assert rows[0]["request"]["questions"]["q"]["type"] == "score"
        assert rows[0]["labels"] == {"q": 3}   # the level index


@pytest.fixture
def fake_wev(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(FAKE_WEV)
    monkeypatch.setenv("PYTHONPATH", FAKE_WEV + os.pathsep +
                       os.environ.get("PYTHONPATH", ""))
    import importlib
    import sys as _sys
    for name in [m for m in _sys.modules if m == "wev" or m.startswith("wev.")]:
        monkeypatch.delitem(_sys.modules, name)
    importlib.invalidate_caches()
    earlier = tmp_path / "earlier_run"
    earlier.mkdir()
    (earlier / "head.pt").write_text("fake")
    return str(earlier)


class TestOpenJevRun:
    def _spec(self, tmp_path, start):
        config, context = sentiment_items(tmp_path)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["sentiment"], split_seed=1,
                                    include_unlabeled=True)
        return _spec(tmp_path, config, bundle, "openjev-finetune", "sentiment",
                     {"model_name": start, "epochs": 2, "min_instances": 10,
                      "_schemes": {"sentiment": config["annotation_schemes"][0]}})

    def test_fit_and_predict_through_wev(self, tmp_path, fake_wev):
        spec = self._spec(tmp_path, fake_wev)
        code, result, report = _run(spec)
        assert code == EXIT_OK, [e for e in report.events if e.get("event") == "error"]
        seen = json.load(open(os.path.join(spec.workdir, "model", "seen.json")))
        args = seen["args"]
        # An earlier run is continued as it is, without a bridge.
        assert args["init_from"] == fake_wev
        assert (args["epochs"], args["lr"], args["batch"]) == ("2", "5e-05", "8")
        assert seen["rows"][0]["labels"]["sentiment"] in ("positive", "negative")
        # The optimizer checkpoint is not an artifact.
        assert not os.path.exists(os.path.join(spec.workdir, "model", "ckpt"))
        vals = [e for e in report.events if e.get("event") == "metric"
                and e.get("split") == "val" and e.get("name") == "accuracy"]
        # The two epochs, then the held-out scorer's own val accuracy.
        assert [round(e["value"], 2) for e in vals][:2] == [0.5, 0.6]
        assert result["metrics"]["heldout_metric"] == "val macro_f1"
        # The last epoch's mean step loss (the fake logs 0.5 / (epoch + 1)).
        assert result["metrics"]["train_loss"] == 0.25
        prediction = _predictions(spec)[0]["payload"]
        assert prediction["label"] in ("positive", "negative")

    def test_a_failed_training_process_is_the_runs_error(self, tmp_path,
                                                         fake_wev, monkeypatch):
        monkeypatch.setenv("FAKE_WEV_FAIL", "1")
        spec = self._spec(tmp_path, fake_wev)
        code, _, report = _run(spec)
        assert code != EXIT_OK
        errors = [e for e in report.events if e.get("event") == "error"]
        assert errors and "CUDA out of memory" in errors[0]["message"]
