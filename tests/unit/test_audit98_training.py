"""Audit 98 (model training): one regression test per finding fixed here.

D3 and D16 have their tests beside the code they cover
(test_training_decision_models.py, tests/jest/audio-segment-provenance.test.js);
D4 is in test_training_backends.py, D7 in
tests/server/test_span_prelabel_api.py, and the item_state part of D17 in
tests/server/test_admin_dashboard_api.py.
"""

import json
import os
import time
import types

import pytest

from potato.publish.preprocessing import _partition_splits
from potato.training import registry, store
from potato.training.config_check import run_problems, training_config_problems


def _rows(n=40):
    return [{"instance_id": "i%d" % i} for i in range(n)]


class TestD1SplitsDoNotDependOnKeyOrder:
    def test_the_same_items_land_in_the_same_splits(self):
        a = _partition_splits(_rows(), {"train": .5, "val": .3, "test": .2}, 0)
        b = _partition_splits(_rows(), {"test": .2, "train": .5, "val": .3}, 0)
        for name in ("train", "val", "test"):
            assert [r["instance_id"] for r in a[name]] == \
                [r["instance_id"] for r in b[name]]


RADIO = {"annotation_type": "radio", "name": "r", "labels": ["a", "b"]}
SLIDER = {"annotation_type": "slider", "name": "stars", "min_value": 1,
          "max_value": 5, "step": 1}
WIDE = {"annotation_type": "slider", "name": "pct", "min_value": 0,
        "max_value": 100, "step": 1}
NUMBER = {"annotation_type": "number", "name": "n"}


class TestD2SlidersAndDecisionModels:
    def test_a_short_slider_gets_the_decision_trainers(self):
        names = {t.name for t in registry.trainers_for_schema(SLIDER)}
        assert {"decision-calibrate", "laya-finetune"} <= names

    def test_other_continuous_answers_do_not(self):
        for scheme in (NUMBER,):
            names = {t.name for t in registry.trainers_for_schema(scheme)}
            assert not names & {"decision-calibrate", "laya-finetune"}

    def test_a_wide_slider_is_refused_with_the_reason(self):
        from potato.training.trainers import _decision_common as dc
        problem = dc.question_problem({"_schemes": {"pct": WIDE}}, "pct")
        assert problem and "21" in problem

    def test_a_slider_value_is_scored(self):
        from potato.training.evaluation import score_split
        rows = [{"instance_id": "0", "targets": {"s": 3.0}},
                {"instance_id": "1", "targets": {"s": 5.0}}]
        preds = {("0", "s"): {"label": "3"}, ("1", "s"): {"label": "4"}}
        metrics, _ = score_split(rows, preds, "s", "continuous")
        assert metrics["accuracy"] == 0.5 and metrics["mae"] == 0.5


class TestD5RttmFileIds:
    def _export(self, tmp_path, items):
        from potato.export.base import ExportContext
        from potato.export.segments_exporter import SegmentsExporter
        seg = {"_data": json.dumps({"segments": [
            {"start_time": 0, "end_time": 1, "label": "x"},
            {"start_time": 2, "end_time": 2, "label": "instant"}]})}
        context = ExportContext(
            config={"item_properties": {"text_key": "audio_file"}},
            annotations=[{"instance_id": iid, "user_id": "u",
                          "labels": {"s": seg}} for iid in items],
            items=items, schemas=[{"annotation_type": "audio_annotation",
                                   "name": "s"}], output_dir="")
        result = SegmentsExporter().export(context, str(tmp_path))
        return result, open(tmp_path / "rttm" / "u.rttm").read().splitlines()

    def test_recordings_sharing_a_name_stay_apart(self, tmp_path):
        result, rttm = self._export(tmp_path, {
            "a3": {"audio_url": "http://x.test/media/talk3.mp3"},
            "a4": {"audio_url": "http://y.test/other/talk3.wav"},
            "a5": {"audio_url": "http://x.test/solo.mp3"}})
        ids = {line.split()[1] for line in rttm}
        assert ids == {"talk3__a3", "talk3__a4", "solo"}

    def test_media_from_the_text_field_and_instants_left_out(self, tmp_path):
        result, rttm = self._export(tmp_path, {"a1": {"audio_file": "/m/rec.wav"}})
        rows = [json.loads(l) for l in open(tmp_path / "segments.jsonl")]
        assert {r["media"] for r in rows} == {"/m/rec.wav"}
        assert len(rows) == 2 and len(rttm) == 1   # the instant stays in JSONL
        assert result.warnings and "zero-length" in result.warnings[0]


def _config(tmp_path, **training):
    return {"task_dir": str(tmp_path), "annotation_schemes": [RADIO],
            "model_training": dict(enabled=True, **training)}


class TestD6D8ConfigChecks:
    def test_a_pre_annotation_field_that_hides_the_prelabels(self, tmp_path):
        config = _config(tmp_path, writeback={"schemas": ["r"]})
        config["pre_annotation"] = {"enabled": True, "field": "model_out"}
        assert any("pre_annotation.field" in p
                   for p in training_config_problems(config))
        config["pre_annotation"]["field"] = "predictions"
        assert training_config_problems(config) == []

    @pytest.mark.parametrize("training, needle", [
        ({"auto_retrain": {"enabled": True, "trainer": "nope", "schemas": ["r"]}},
         "Unknown trainer"),
        ({"auto_retrain": {"enabled": True, "trainer": "sklearn-text",
                           "schemas": ["nosuch"]}}, "No annotation scheme"),
        ({"auto_retrain": {"enabled": True, "trainer": "hf-token-classification",
                           "schemas": ["r"]}}, "does not train"),
        ({"auto_retrain": {"enabled": True, "trainer": "sklearn-text",
                           "schemas": ["r"], "params": {"nope": 1}}},
         "does not take"),
        ({"auto_retrain": {"enabled": False, "accept_license": True}},
         "did you mean accept_licence"),
        ({"writeback": {"schemas": ["ghost"]}}, "not an annotation scheme"),
        ({"writeback": {"schemas": ["r"], "min_confidence": "high"}},
         "min_confidence"),
        ({"splits": {"training": .8, "test": .2}}, "use train, val and test"),
        ({"auto_retrain": {"enabled": False, "accept_licence": "yes"}},
         "must be true or false"),
    ])
    def test_settings_that_used_to_fail_later(self, tmp_path, training, needle):
        problems = training_config_problems(_config(tmp_path, **training))
        assert any(needle in p for p in problems), problems

    def test_a_trainer_param_of_the_wrong_type(self):
        problems = registry.validate_trainer_params(
            {"hf-text-classification": {"epochs": "many"}})
        assert problems and "epochs must be integer" in problems[0]

    def test_a_calibration_file_that_is_not_there(self, tmp_path):
        config = {"task_dir": str(tmp_path), "labeling_engine": {"sources": [
            {"id": "jev", "kind": "decision", "endpoint_type": "systemone",
             "options": {"calibration": "nope/calibration.json"}}]}}
        assert any("no file at" in p for p in training_config_problems(config))
        (tmp_path / "nope").mkdir()
        (tmp_path / "nope" / "calibration.json").write_text("{}")
        assert training_config_problems(config) == []

    def test_validation_refuses_them(self, tmp_path):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_training_backends_config)
        with pytest.raises(ConfigValidationError, match="min_confidence"):
            validate_training_backends_config(_config(
                tmp_path, writeback={"schemas": ["r"], "min_confidence": "high"}))


class TestD9D10RunsRefusedUpFront:
    def test_unknown_scheme_and_wrong_kind(self, tmp_path):
        config = _config(tmp_path)
        assert "No annotation scheme" in run_problems(config, "sklearn-text",
                                                      ["nosuch"])[0]
        assert "does not train" in run_problems(
            config, "hf-token-classification", ["r"])[0]
        assert run_problems(config, "sklearn-text", ["r"]) == []

    def test_start_run_refuses_with_400(self, tmp_path):
        from potato.training.manager import TrainingManager
        outcome = TrainingManager(_config(tmp_path)).start_run(
            "sklearn-text", ["nosuch"])
        assert not outcome["started"] and outcome["http_status"] == 400

    def test_decision_calibrate_needs_a_decision_model(self, tmp_path):
        assert "no decision model" in run_problems(
            _config(tmp_path), "decision-calibrate", ["r"])[0]


def _manager(tmp_path, **training):
    from potato.training.manager import TrainingManager
    config = _config(tmp_path, **training)
    config["annotation_task_name"] = "audit98"
    return TrainingManager(config), config


class TestD11TimeLimit:
    def test_a_run_stopped_by_the_limit_says_so(self, tmp_path):
        manager, config = _manager(tmp_path, max_wall_seconds=5)
        run = store.TrainingRun(run_id="r1", trainer="sklearn-text",
                                schema_names=["r"], status="running")
        store.record_run(config, run)
        manager._wall_limited = "r1"
        manager._record_completion(run, 4, None, None, {})
        stored = store.load_run(config, "r1")
        assert stored.error_code == "timeout"
        assert "max_wall_seconds (5 s)" in stored.error


class TestD13AutoRetrainAfterRestart:
    def test_the_count_starts_from_the_restart(self, tmp_path):
        manager, config = _manager(tmp_path, auto_retrain={
            "enabled": True, "trainer": "sklearn-text", "schemas": ["r"],
            "update_frequency": 5, "min_interval_s": 0})
        old = store.TrainingRun(run_id="r0", trainer="sklearn-text",
                                schema_names=["r"], status="success",
                                finished_at=time.time() - 3600)
        store.record_run(config, old)
        started = []
        manager.start_run = lambda *a, **k: started.append(a) or {
            "started": True, "run_id": "r1"}
        counts = iter([100, 100, 103, 106])
        manager._annotation_count = lambda: next(counts)
        assert not manager.maybe_auto_retrain()["started"]   # 100: baseline
        assert not manager.maybe_auto_retrain()["started"]   # 103: +3
        assert manager.maybe_auto_retrain()["started"]       # 106: +6
        assert len(started) == 1


class TestD14D15D17WriteBack:
    def test_a_rejected_prelabel_comes_down_at_once(self, tmp_path):
        from potato import model_review
        config = _config(tmp_path, writeback={"schemas": ["r"]})
        config["annotation_task_name"] = "audit98"
        store.record_run(config, store.TrainingRun(run_id="r1", trainer="t",
                                                   status="success"))
        store.record_predictions(config, "r1", [("t4", "r", {"label": "a"}, .9)])
        cleared = []
        items = types.SimpleNamespace(clear_prediction=lambda *a, **k:
                                      cleared.append(a) or True)
        import potato.item_state_management as ism
        original = ism.get_item_state_manager
        ism.get_item_state_manager = lambda: items
        try:
            model_review.record_verdict(config, model_review.ReviewVerdict(
                instance_id="t4", schema_name="r", reviewer="rev",
                verdict="reject"))
        finally:
            ism.get_item_state_manager = original
        assert cleared and cleared[0][:2] == ("t4", "r")

    def test_the_report_carries_its_explanation_and_skips_empty(self, tmp_path):
        from potato.training.writeback import WritebackReport, ingest_predictions
        config = _config(tmp_path, writeback={"schemas": ["r"]})
        config["annotation_task_name"] = "audit98"
        path = tmp_path / "predictions.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in [
            {"instance_id": "a", "schema_name": "r", "payload": []},
            {"instance_id": "b", "schema_name": "r",
             "payload": {"segments": []}},
            {"instance_id": "c", "schema_name": "r", "payload": {"label": "a"}}]))
        written = []
        items = types.SimpleNamespace(
            set_prediction=lambda *a, **k: written.append(a) or True,
            clear_prediction=lambda *a, **k: False)
        run = store.TrainingRun(run_id="r2", trainer="t", status="success")
        store.record_run(config, run)
        report = ingest_predictions(run, str(path), config, item_manager=items)
        assert report.n_written == 1 and report.n_skipped_empty == 2
        assert report.to_dict()["summary"].startswith("Published 1")
        empty = WritebackReport().to_dict()["summary"]
        assert "write-back is not enabled for any schema" in empty
