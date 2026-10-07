"""
Judge alignment, cheating detection, solo-mode agreement, gold auto-promotion,
judge calibration and step QC, on the inputs the earlier tests never used:
versions written out of hash order, several schemas, re-saves, an imbalanced
task with a constant answerer, a corrected label, duplicated LLM spans, a tie,
and no data at all.
"""

from __future__ import annotations

import json
import os

import pytest

from potato.server_utils import judge_alignment as ja
from potato.server_utils.cheating_detection import correlated_agreement
from tests.helpers.test_utils import create_test_directory


def _cfg(name, schemas=("verdict",)):
    path = create_test_directory(name)
    return {
        "task_dir": path, "output_annotation_dir": path,
        "annotation_schemes": [{"annotation_type": "radio", "name": s,
                                "labels": [{"name": "pass"}, {"name": "fail"}]}
                               for s in schemas],
    }


def _predict(cfg, version, schema, labels):
    from potato.ai.judge import JudgePrediction
    for iid, label in labels.items():
        ja.save_prediction(cfg, JudgePrediction(iid, schema, label, 0.9, "", "m", version))


class TestJudgeAlignment:
    GOLD = {f"i{n}": ("pass" if n % 2 else "fail") for n in range(6)}

    def test_trend_follows_creation_order_not_hash_order(self, monkeypatch):
        cfg = _cfg("judge_trend")
        wrong = {iid: ("fail" if g == "pass" else "pass") for iid, g in self.GOLD.items()}
        # "v_zzz" sorts after "v_aaa" but was written first.
        _predict(cfg, "v_zzz", "verdict", wrong)
        _predict(cfg, "v_aaa", "verdict", dict(self.GOLD))
        monkeypatch.setattr(ja, "majority_human_label",
                            lambda iid, schema, users: self.GOLD.get(iid))
        report = ja.compute_judge_alignment(cfg, users=["u"])
        assert report["kappa_trend"]["direction"] == "improving"

    def test_every_schema_gets_its_own_version(self, monkeypatch):
        cfg = _cfg("judge_schemas", schemas=("sentiment", "topic"))
        _predict(cfg, "v_s", "sentiment", dict(self.GOLD))
        _predict(cfg, "v_t", "topic", {k: v for k, v in list(self.GOLD.items())[:4]})
        monkeypatch.setattr(ja, "majority_human_label",
                            lambda iid, schema, users: self.GOLD.get(iid))
        report = ja.compute_judge_alignment(cfg, users=["u"])
        assert report["per_schema"]["sentiment"]["n"] == 6
        assert report["per_schema"]["topic"]["n"] == 4

    def test_running_agreement_counts_items_not_saves(self):
        cfg = _cfg("judge_running")
        for _ in range(4):
            ja.record_comparison(cfg, "i1", "verdict", "pass", "pass", "v", username="u")
        ja.record_comparison(cfg, "i2", "verdict", "neg", "pos", "v", username="u")
        ja.record_comparison(cfg, "i3", "verdict", "neg", "neg", "v", username="u")
        running = ja.running_agreement(cfg, "verdict")
        assert running["n"] == 3
        assert running["agreement_rate"] == pytest.approx(0.667, abs=1e-3)

    def test_a_tied_human_vote_is_no_gold(self, monkeypatch):
        labels = {"u1": "pass", "u2": "fail"}
        monkeypatch.setattr(ja, "human_label_for", lambda iid, s, u: labels[u])
        assert ja.majority_human_label("i1", "verdict", ["u1", "u2"]) is None


class TestCorrelatedAgreement:
    def _obs(self):
        truth = ["A"] * 16 + ["B"] * 4
        obs = []
        for n, label in enumerate(truth):
            for worker in ("h1", "h2", "h3", "h4"):
                obs.append((worker, f"i{n}", label))
            obs.append(("spam", f"i{n}", "A"))
        return obs

    def test_a_constant_answerer_has_no_signal(self):
        """Shnayder et al.: same-item agreement minus sum_k f_w(k) f_peer(k).
        For a worker who always says A that is 0.8 - 0.8 = 0."""
        ca = correlated_agreement(self._obs())
        assert ca["spam"] == pytest.approx(0.0, abs=1e-9)
        assert ca["h1"] > 0.2

    def test_a_worker_with_no_peers_is_unscored(self):
        obs = self._obs() + [("loner", "solo_item", "A")]
        assert correlated_agreement(obs)["loner"] is None


class TestSoloAgreement:
    def _manager(self, annotation_type="radio"):
        from potato.solo_mode.config import parse_solo_mode_config
        from potato.solo_mode.manager import SoloModeManager
        scheme = {"name": "sentiment", "annotation_type": annotation_type,
                  "labels": ["positive", "negative"]}
        config = {"solo_mode": {"enabled": True, "labeling_models": []},
                  "annotation_schemes": [scheme]}
        mgr = SoloModeManager(parse_solo_mode_config(config),
                              {"annotation_schemes": [scheme]})
        mgr.create_prompt_version("p", "u")
        return mgr

    def _predict(self, mgr, iid, label):
        from potato.solo_mode.manager import LLMPrediction
        mgr.set_llm_prediction(iid, "sentiment", LLMPrediction(
            instance_id=iid, schema_name="sentiment", predicted_label=label,
            confidence_score=0.9, uncertainty_score=0.1, prompt_version=1))

    def test_a_corrected_label_updates_the_rate(self):
        mgr = self._manager()
        for n in range(3):
            self._predict(mgr, f"i{n}", "positive")
            mgr.record_human_label(f"i{n}", "sentiment", "negative", "u")
        assert mgr.agreement_metrics.agreement_rate == 0.0
        for n in range(3):
            mgr.record_human_label(f"i{n}", "sentiment", "positive", "u")
        assert mgr.agreement_metrics.agreement_rate == 1.0
        assert mgr.agreement_metrics.total_compared == 3
        assert mgr.validation_tracker.get_metrics().agreements == 3

    def test_duplicated_llm_spans_do_not_double_cover(self):
        mgr = self._manager()
        human = json.dumps([{"start": 0, "end": 10, "label": "X"}])
        llm = json.dumps([{"start": 0, "end": 5, "label": "X"},
                          {"start": 0, "end": 5, "label": "X"}])
        assert mgr._spans_agree(human, llm, 0.9) is False
        assert mgr._spans_agree(human, llm, 0.5) is True

    def test_retroactive_lookup_reads_the_real_user_state_api(self, monkeypatch):
        from potato.item_state_management import Label
        mgr = self._manager()

        class State:
            def get_label_annotations(self, iid):
                return {Label("sentiment", "negative"): "true"} if iid == "i1" else {}

        class USM:
            def get_user_ids(self):
                return ["u"]

            def get_user_state(self, uid):
                return State()

        import potato.user_state_management as usm_module
        monkeypatch.setattr(usm_module, "get_user_state_manager", lambda: USM())
        assert mgr._get_stored_human_label("i1", "sentiment") == "negative"


class TestGoldAutoPromotion:
    def _qc(self, threshold):
        from potato.quality_control import QualityControlManager
        config = {"gold_standards": {
            "enabled": True, "auto_promote": {
                "enabled": True, "min_annotators": 2,
                "agreement_threshold": threshold}}}
        return QualityControlManager(config, create_test_directory("qc_promote"))

    def test_a_tie_is_not_a_consensus(self):
        """At threshold 0.5 a 1-1 split passed ">=" and promoted whichever
        label was counted first."""
        qc = self._qc(0.5)
        assert qc._check_and_promote("item1", {"a": {"s": "pos"}, "b": {"s": "neg"}}) is None
        assert "item1" not in qc.gold_labels

    def test_the_reported_agreement_is_the_real_share(self):
        qc = self._qc(0.6)
        result = qc._check_and_promote(
            "item2", {"a": {"s": "pos"}, "b": {"s": "pos"}, "c": {"s": "neg"}})
        assert result["agreement"] == pytest.approx(2 / 3)

    def test_source_annotators_are_not_graded_on_their_own_consensus(self):
        qc = self._qc(1.0)
        qc._promote_to_gold("item1", {"s": "pos"}, {"a": {"s": "pos"}, "b": {"s": "pos"}})
        assert qc.validate_gold_response("a", "item1", {"s": "pos"}) is None
        assert qc.validate_gold_response("c", "item1", {"s": "pos"}) is not None


class TestCalibrationOnNoData:
    def test_nothing_to_calibrate_is_undefined(self):
        from potato.judge_calibration.calibration import (
            brier_score, expected_calibration_error,
        )
        assert expected_calibration_error([], []) is None
        assert brier_score([], []) is None


class TestStepQc:
    def test_gold_steps_are_scored_from_storage(self):
        from potato.step_quality_control import StepQualityControlManager
        base = create_test_directory("step_qc_gold")
        with open(os.path.join(base, "gold.json"), "w") as f:
            json.dump([{"instance_id": "t1", "step_index": 0,
                        "scheme_name": "s", "expected_label": 3}], f)
        manager = StepQualityControlManager(
            {"enabled": True, "gold_standards_file": "gold.json"}, base)
        manager.score_annotations({"t1": {"ann": {"s": [{"0": "3"}]}}})
        summary = manager.get_quality_summary()
        assert summary["total_checks_performed"] == 1
        assert summary["overall_accuracy"] == 1.0


class TestAttentionCadence:
    def test_re_saving_an_item_does_not_advance_the_count(self):
        from potato.quality_control import QualityControlManager
        qc = QualityControlManager({}, create_test_directory("qc_cadence"))
        for _ in range(3):
            qc.record_regular_item("u", "i1")
        qc.record_regular_item("u", "i2")
        assert qc.user_items_since_attention["u"] == 2
