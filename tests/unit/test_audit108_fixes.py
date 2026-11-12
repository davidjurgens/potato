"""Audit 108: findings from the website's 2.14.0 documentation pass.

Model review counted a rejected prelabel as a label the model missed, and a
newer run whose prediction was not shown left an older run's prelabel on the
item while taking the credit for it.
"""

import json
import types

import pytest

from potato import model_review
from potato.training import store

RADIO = {"annotation_type": "radio", "name": "r", "description": "", "labels": ["a", "b"]}


def _config(tmp_path, **writeback):
    return {"task_dir": str(tmp_path), "annotation_task_name": "audit108",
            "annotation_schemes": [RADIO],
            "model_training": {"enabled": True,
                               "writeback": dict({"schemas": ["r"]}, **writeback)}}


class FakeItems:
    """An item manager holding each item's data, as the review reads it."""

    def __init__(self, data):
        self.data = data

    def find_item(self, instance_id):
        if instance_id not in self.data:
            return None
        return types.SimpleNamespace(get_data=lambda: self.data[instance_id])

    def iter_items(self):
        for instance_id in list(self.data):
            yield instance_id, self.find_item(instance_id)

    def set_prediction(self, instance_id, schema_name, payload, field="predictions"):
        self.data[instance_id].setdefault(field, {})[schema_name] = payload
        return True

    def clear_prediction(self, instance_id, schema_name, field="predictions"):
        return self.data[instance_id].get(field, {}).pop(schema_name, None) is not None


@pytest.fixture
def items(monkeypatch):
    import potato.item_state_management as ism
    holder = FakeItems({})
    monkeypatch.setattr(ism, "get_item_state_manager", lambda: holder)
    return holder


class TestRejectedPrelabelsInTheReviewMetrics:
    def test_a_reject_counts_against_the_prelabel_it_took_down(self, tmp_path, items):
        config = _config(tmp_path)
        store.record_run(config, store.TrainingRun(run_id="r1", trainer="t", status="success"))
        store.record_predictions(config, "r1", [
            (iid, "r", {"label": "a"}, 0.9) for iid in ("p1", "p2", "p3")])
        items.data.update({iid: {"text": iid, "predictions": {"r": {"label": "a"}}}
                           for iid in ("p1", "p2", "p3")})
        for iid, verdict in (("p1", "accept"), ("p2", "correct"), ("p3", "reject")):
            model_review.record_verdict(config, model_review.ReviewVerdict(
                instance_id=iid, schema_name="r", reviewer="rev", verdict=verdict))
        assert "r" not in items.data["p3"]["predictions"]   # the reject took it down

        metrics = model_review.summarize_project(items, config)["metrics"]
        assert metrics["counts"] == {"accept": 1, "correct": 1, "reject": 1}
        assert metrics["precision"] == pytest.approx(1 / 3)
        assert metrics["n_false_negatives"] == 0 and metrics["recall"] is None

    def test_a_verdict_on_an_item_that_showed_nothing_is_still_a_miss(self, tmp_path, items):
        config = _config(tmp_path)
        items.data.update({"p1": {"predictions": {"r": {"label": "a"}}}, "e1": {}})
        model_review.record_verdict(config, model_review.ReviewVerdict(
            instance_id="p1", schema_name="r", reviewer="rev", verdict="accept"))
        model_review.record_verdict(config, model_review.ReviewVerdict(
            instance_id="e1", schema_name="r", reviewer="rev", verdict="correct"))
        metrics = model_review.summarize_project(items, config)["metrics"]
        assert metrics["counts"]["accept"] == 1 and metrics["n_reviewed"] == 1
        assert metrics["n_empty_reviewed"] == 1 and metrics["n_false_negatives"] == 1

    def test_an_older_reject_without_the_record_reads_the_stored_prediction(
            self, tmp_path, items):
        config = _config(tmp_path)
        store.record_run(config, store.TrainingRun(run_id="r1", trainer="t", status="success"))
        store.record_predictions(config, "r1", [("p1", "r", {"label": "a"}, 0.9)])
        items.data.update({"p1": {}})
        conn = model_review._db(str(tmp_path))
        conn.execute("INSERT INTO model_review_verdicts (project, instance_id, schema_name, "
                     "reviewer, verdict, note, updated_at) VALUES (?,?,?,?,?,?,?)",
                     ("audit108", "p1", "r", "rev", "reject", "", 1.0))
        conn.commit()
        assert model_review.load_verdicts(config)[0].had_prelabel is None
        metrics = model_review.summarize_project(items, config)["metrics"]
        assert metrics["counts"]["reject"] == 1 and metrics["n_false_negatives"] == 0


class TestAWeakerNewerRun:
    def _ingest(self, tmp_path, config, items, records, run_id="r2"):
        from potato.training.writeback import ingest_predictions
        path = tmp_path / ("%s.jsonl" % run_id)
        path.write_text("\n".join(json.dumps(r) for r in records))
        run = store.TrainingRun(run_id=run_id, trainer="t", status="success")
        store.record_run(config, run)
        return ingest_predictions(run, str(path), config, item_manager=items)

    def test_its_unshown_prediction_takes_the_older_prelabel_down(self, tmp_path, items):
        config = _config(tmp_path, min_confidence=0.5)
        items.data.update({"x": {"text": "x"}, "y": {"text": "y"}})
        self._ingest(tmp_path, config, items, [
            {"instance_id": "x", "schema_name": "r", "payload": {"label": "a"},
             "confidence": 0.9}], run_id="r1")
        assert items.data["x"]["predictions"]["r"] == {"label": "a"}
        # A prelabel that came with the data, not from a run.
        items.data["y"]["predictions"] = {"r": {"label": "b"}}

        report = self._ingest(tmp_path, config, items, [
            {"instance_id": iid, "schema_name": "r", "payload": {"label": "b"},
             "confidence": 0.2} for iid in ("x", "y")])
        assert report.n_skipped_low_confidence == 2
        assert report.n_superseded_cleared == 1
        assert "r" not in items.data["x"]["predictions"]
        assert items.data["y"]["predictions"]["r"] == {"label": "b"}
        # What the review page credits now matches what is on the item.
        assert store.prediction_runs(config, ["x"]) == {("x", "r"): "r2"}

    def test_a_data_prelabel_stays_when_an_earlier_run_never_published(self, tmp_path, items):
        """V2: an earlier run stored a prediction under the floor, so the
        item's prelabel is the data's, and a weak newer run must not clear it."""
        config = _config(tmp_path, min_confidence=0.5)
        items.data.update({"y": {"predictions": {"r": {"label": "b"}}}})
        self._ingest(tmp_path, config, items, [
            {"instance_id": "y", "schema_name": "r", "payload": {"label": "a"},
             "confidence": 0.3}], run_id="r1")
        report = self._ingest(tmp_path, config, items, [
            {"instance_id": "y", "schema_name": "r", "payload": {"label": "a"},
             "confidence": 0.2}])
        assert report.n_superseded_cleared == 0
        assert items.data["y"]["predictions"]["r"] == {"label": "b"}

    def test_a_confident_newer_run_replaces_it_as_before(self, tmp_path, items):
        config = _config(tmp_path, min_confidence=0.5)
        items.data.update({"x": {"text": "x"}})
        self._ingest(tmp_path, config, items, [
            {"instance_id": "x", "schema_name": "r", "payload": {"label": "a"},
             "confidence": 0.9}], run_id="r1")
        report = self._ingest(tmp_path, config, items, [
            {"instance_id": "x", "schema_name": "r", "payload": {"label": "b"},
             "confidence": 0.8}])
        assert report.n_written == 1 and report.n_superseded_cleared == 0
        assert items.data["x"]["predictions"]["r"] == {"label": "b"}


class TestAgentGracePeriod:
    def test_the_agent_uses_the_servers_grace_seconds(self, tmp_path):
        from potato.training.agent import JobRunner
        from potato.training.manager import ExternalJob
        job = ExternalJob(run_id="r1", backend="b", backend_type="agent", spec={},
                          run_dir=str(tmp_path), sink=None, grace_seconds=45.0)
        assert job.public()["grace_seconds"] == 45.0
        assert JobRunner(None, job.public(), str(tmp_path)).grace_s == 45.0
        # A server from before this sends none: the agent keeps its default.
        assert JobRunner(None, {"job_id": "r2"}, str(tmp_path)).grace_s == 20.0

    def test_a_grace_of_zero_is_zero_on_both_sides(self, tmp_path):
        """V4: `or` read 0 as missing, so the agent waited 20 s after the
        server had already ended the run."""
        from potato.training.agent import JobRunner
        assert JobRunner(None, {"job_id": "r", "grace_seconds": 0}, str(tmp_path)).grace_s == 0.0
        assert JobRunner(None, {"job_id": "r", "grace_seconds": 0.5},
                         str(tmp_path)).grace_s == 0.5

    @pytest.mark.parametrize("value", [-1, "soon", float("nan"), True])
    def test_validation_refuses_a_grace_that_is_not_seconds(self, value):
        """V5: a negative grace was accepted, a string crashed the manager."""
        from potato.training.config_check import training_config_problems
        problems = training_config_problems({"model_training": {"grace_seconds": value}})
        assert any("grace_seconds" in p for p in problems), problems

    def test_validation_accepts_zero_and_checks_the_other_whole_numbers(self):
        from potato.training.config_check import training_config_problems
        assert not training_config_problems({"model_training": {"grace_seconds": 0}})
        problems = training_config_problems({"model_training": {"retain_runs": "5",
                                                                "split_seed": 1.5}})
        assert any("retain_runs" in p for p in problems)
        assert any("split_seed" in p for p in problems)


class TestSlurmTimeWarning:
    def test_validation_reports_a_long_time_limit(self, caplog):
        from potato.server_utils.config_module import validate_training_backends_config
        config = {"model_training": {"enabled": True, "backends": {"cluster": {
            "type": "slurm", "host": "login", "remote_dir": "/shared/potato",
            "job_python": "/opt/env/bin/python", "time": "08:00:00"}}}}
        with caplog.at_level("WARNING"):
            validate_training_backends_config(config)
        assert any("model_training.backends.cluster.time is 08:00:00" in r.getMessage()
                   for r in caplog.records), [r.getMessage() for r in caplog.records]


class TestReRecordedVerdicts:
    """V1: COALESCE(new, old) let a re-sent verdict overwrite had_prelabel
    with False once the reject had taken the prelabel down."""

    def test_the_same_reject_sent_twice_still_counts_as_a_reject(self, tmp_path, items):
        config = _config(tmp_path)
        store.record_run(config, store.TrainingRun(run_id="r1", trainer="t", status="success"))
        store.record_predictions(config, "r1", [("p1", "r", {"label": "a"}, 0.9)])
        items.data.update({"p1": {"predictions": {"r": {"label": "a"}}}})
        for _ in range(2):
            model_review.record_verdict(config, model_review.ReviewVerdict(
                instance_id="p1", schema_name="r", reviewer="rev", verdict="reject"))
        metrics = model_review.summarize_project(items, config)["metrics"]
        assert metrics["counts"]["reject"] == 1
        assert metrics["n_empty_reviewed"] == 0 and metrics["n_false_negatives"] == 0

    def test_an_accept_re_sent_after_the_prelabel_went_stays_in_precision(self, tmp_path, items):
        config = _config(tmp_path)
        items.data.update({"p1": {"predictions": {"r": {"label": "a"}}}})
        verdict = model_review.ReviewVerdict(instance_id="p1", schema_name="r",
                                             reviewer="rev", verdict="accept")
        model_review.record_verdict(config, verdict)
        items.data["p1"]["predictions"] = {}
        model_review.record_verdict(config, verdict)
        assert model_review.load_verdicts(config)[0].had_prelabel is True

    def test_a_prelabel_that_appeared_since_counts(self, tmp_path, items):
        config = _config(tmp_path)
        items.data.update({"e1": {}})
        verdict = model_review.ReviewVerdict(instance_id="e1", schema_name="r",
                                             reviewer="rev", verdict="correct")
        model_review.record_verdict(config, verdict)
        assert model_review.load_verdicts(config)[0].had_prelabel is False
        items.data["e1"]["predictions"] = {"r": {"label": "b"}}
        model_review.record_verdict(config, verdict)
        assert model_review.load_verdicts(config)[0].had_prelabel is True
