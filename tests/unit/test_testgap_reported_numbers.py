"""
Numbers that end up in reports and papers: judge calibration, LLM confidence,
the rollout judge's alignment, the per-agent turn rollup, model-review recall
and the solo-mode trend.

Each test is a case the earlier tests did not try: a model with no gold
overlap, a configured label nobody used, a split human vote, failed samples,
a JSON reply whose punctuation is near-certain, a version called "v10", a
number widget's string value, and a sampled pool that stands for a larger one.
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from potato.item_state_management import Label


# ---------------------------------------------------------------------------
# Judge calibration
# ---------------------------------------------------------------------------

class TestJudgeCalibration:
    def test_a_model_with_no_gold_overlap_does_not_crash_the_report(self):
        from potato.judge_calibration.metrics import compute_schema_report
        report = compute_schema_report(
            "s", "radio", ["a", "b"], {"m1": {"x1": "a"}}, {"m1": {"x1": 0.9}},
            {"h1": {"i1": "a"}})
        block = report["per_model"]["m1"]
        assert block["accuracy"] is None and block["f1_macro"] is None

    def test_an_unused_label_does_not_lower_macro_f1(self):
        from potato.judge_calibration.metrics import compute_schema_report
        gold = {"i1": "A", "i2": "B", "i3": "A", "i4": "B"}
        report = compute_schema_report(
            "s", "radio", ["A", "B", "C"], {"m1": dict(gold)},
            {"m1": {k: 1.0 for k in gold}}, {"h1": gold})
        assert report["per_model"]["m1"]["f1_macro"] == 1.0

    def test_spans_with_nothing_on_either_side_are_undefined(self):
        from potato.judge_calibration.metrics import span_prf
        assert span_prf([], [])["f1"] is None
        missed = span_prf([], [{"start": 0, "end": 3, "label": "X"}])
        assert missed["recall"] == 0.0 and missed["precision"] is None
        assert missed["f1"] == 0.0

    def test_a_prediction_without_a_confidence_is_left_out_of_calibration(self):
        from potato.judge_calibration.metrics import compute_schema_report
        gold = {"i1": "a", "i2": "b"}
        report = compute_schema_report(
            "s", "radio", ["a", "b"], {"m1": dict(gold)}, {"m1": {"i1": 1.0}},
            {"h1": gold})
        # One scored, correct, at confidence 1.0: perfectly calibrated. The
        # unscored one used to enter as a 0.0-confidence hit.
        assert report["per_model"]["m1"]["calibration"]["ece"] == 0.0


# ---------------------------------------------------------------------------
# LLM confidence for active learning
# ---------------------------------------------------------------------------

def _llm(method, samples=5):
    from potato.ai.llm_active_learning import LLMActiveLearning, LLMConfig
    llm = LLMActiveLearning.__new__(LLMActiveLearning)
    llm.config = LLMConfig(endpoint_url="http://x", model_name="m",
                           confidence_method=method, consistency_samples=samples,
                           retry_attempts=1, retry_delay=0)
    import logging
    llm.logger = logging.getLogger("t")
    llm.session = MagicMock()
    return llm


def _reply(content, logprobs=None, status=200):
    body = {"choices": [{"message": {"content": content}}]}
    if logprobs is not None:
        body["choices"][0]["logprobs"] = {"content": logprobs}
    return SimpleNamespace(status_code=status, json=lambda: body, text="")


class TestLlmConfidence:
    def test_failed_samples_count_against_consistency(self):
        llm = _llm("consistency", samples=5)
        ok = _reply(json.dumps({"label": "pos"}))
        llm.session.post.side_effect = [ok] + [RuntimeError("down")] * 4
        prediction = llm._predict_consistency("p", {"id": "i1"})
        assert prediction.confidence_score == pytest.approx(0.2)

    def test_a_reply_with_no_label_is_not_a_vote(self):
        llm = _llm("consistency", samples=5)
        replies = [_reply(json.dumps({"label": "pos"}))] * 2 + \
            [_reply(json.dumps({"reason": "x"}))] * 3
        llm.session.post.side_effect = replies
        prediction = llm._predict_consistency("p", {"id": "i1"})
        assert prediction.predicted_label == "pos"

    def test_logprob_confidence_is_the_labels_probability(self):
        llm = _llm("logprobs")
        tokens = [("{\"", -0.01), ("label", -0.01), ("\": \"", -0.01),
                  ("pos", math.log(0.4)), ("itive", 0.0), ("\"}", -0.01)]
        content = "".join(t for t, _ in tokens)
        llm.session.post.return_value = _reply(
            content, [{"token": t, "logprob": lp} for t, lp in tokens])
        prediction = llm._predict_with_logprobs("p", {"id": "i1"})
        assert prediction.confidence_score == pytest.approx(0.4, abs=1e-6)


# ---------------------------------------------------------------------------
# Rollout judge alignment
# ---------------------------------------------------------------------------

class TestRolloutAlignment:
    def test_latest_is_the_version_run_last(self, monkeypatch):
        from potato.rollouts import batch
        # File order is run order: v2 was run after v10. Sorting the names
        # picked v2 here by luck of the alphabet and v10 never.
        monkeypatch.setattr(batch, "load_predictions",
                            lambda config: {"v2": {}, "v10": {}})
        ism = SimpleNamespace(get_instance_ids=lambda: [])
        usm = SimpleNamespace(get_user_ids=lambda: [], get_user_state=lambda u: None)
        with patch("potato.item_state_management.get_item_state_manager", return_value=ism), \
             patch("potato.user_state_management.get_user_state_manager", return_value=usm):
            report = batch.alignment_report({})
        assert report["prompt_version"] == "v10"

    def test_a_split_human_vote_is_not_a_clean_rollout(self):
        from potato.ai.rollout_judge import BreakPrediction, align_with_humans
        prediction = BreakPrediction(instance_id="i1", schema_name="r", stream_id="s", t=3.0,
                                     violation_type="physics", resolution=0.1)
        report = align_with_humans([prediction], {"i1::s": {
            "t": None, "type": "", "tied": True}}, tolerance=0.5)
        assert report["n_compared"] == 0
        assert report["n_human_tied"] == 1


# ---------------------------------------------------------------------------
# Turn-level rollup
# ---------------------------------------------------------------------------

def test_number_widgets_contribute_to_the_mean():
    from potato.server_utils.turn_annotations import compute_agent_rollup
    config = {"annotation_schemes": [{"name": "score", "annotation_type": "number",
                                      "turn_level": True}]}
    stored = {Label("score", "_data"): json.dumps({"turns": {
        "t1": {"value": "3", "agent_id": "a"}, "t2": {"value": "5", "agent_id": "a"}}})}
    ism = SimpleNamespace(instance_annotators={"i1": {"u1"}})
    usm = SimpleNamespace(get_user_state=lambda uid: SimpleNamespace(
        get_label_annotations=lambda iid: stored))
    rollup = compute_agent_rollup(ism, usm, config)
    assert rollup["schemas"]["score"]["agents"]["a"]["mean"] == 4.0


# ---------------------------------------------------------------------------
# Model review
# ---------------------------------------------------------------------------

class TestModelReviewRecall:
    def _verdicts(self, n_accept):
        from potato.model_review import ReviewVerdict
        return [ReviewVerdict(instance_id=f"p{i}", reviewer="r", verdict="accept")
                for i in range(n_accept)]

    def test_a_sampled_miss_rate_is_scaled_to_the_pool(self):
        from potato.model_review import review_metrics
        metrics = review_metrics(self._verdicts(100), ["e1", "e2"], ["e1"],
                                 n_empty_total=1000, n_prelabelled_total=100)
        # 100 found; about 500 missed in the empty pool.
        assert metrics["recall"] == pytest.approx(100 / 600)

    def test_a_second_reviewer_does_not_replace_the_first(self):
        from potato.model_review import ReviewVerdict, review_metrics
        verdicts = [ReviewVerdict(instance_id="p1", reviewer="r1", verdict="accept"),
                    ReviewVerdict(instance_id="p1", reviewer="r2", verdict="reject")]
        assert review_metrics(verdicts)["counts"] == {
            **review_metrics([])["counts"], "accept": 1, "reject": 1}


# ---------------------------------------------------------------------------
# Solo-mode validation tracker
# ---------------------------------------------------------------------------

class TestRecentAgreement:
    def test_one_agreeing_comparison_reads_as_agreement(self):
        from potato.solo_mode.validation_tracker import ValidationTracker
        tracker = ValidationTracker()
        tracker.record_comparison("i1", "pos", "pos", "s", True)
        assert tracker.get_metrics().recent_agreement_rate == 1.0

    def test_a_retraction_updates_the_recent_rate(self):
        from potato.solo_mode.validation_tracker import ValidationTracker
        tracker = ValidationTracker()
        tracker.record_comparison("i1", "pos", "pos", "s", True)
        tracker.record_comparison("i2", "pos", "neg", "s", False)
        tracker.retract_comparison("i2", "s")
        assert tracker.get_metrics().recent_agreement_rate == 1.0


def test_the_report_shows_undefined_values_as_n_a():
    import re
    from potato.judge_calibration.metrics import compute_schema_report
    from potato.judge_calibration.report import render_html
    schema = compute_schema_report(
        "s", "radio", ["pos", "neg"], {"m1": {"x9": "pos"}}, {"m1": {"x9": 0.7}},
        {"h1": {"i1": "pos"}})
    text = re.sub(r"<[^>]+>", " ", render_html({"schemas": {"s": schema}}))
    assert "None" not in text
    assert "n/a" in text
