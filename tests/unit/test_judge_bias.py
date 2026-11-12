"""Unit tests for judge bias & robustness diagnostics (E4)."""

import pytest

from potato.server_utils.judge_bias import (
    BiasRecord, verbosity_bias, confidence_calibration,
    position_swap_consistency, build_eval_card,
)


class TestVerbosityBias:
    def test_detects_judge_length_preference(self):
        # Judge labels long items "good"; humans label by parity (not length).
        recs = []
        for n in range(20):
            long = n >= 10
            recs.append(BiasRecord(text_len=(500 if long else 50),
                                   judge_label="good" if long else "bad",   # judge ↔ length
                                   human_label="good" if n % 2 == 0 else "bad"))  # human ↔ parity
        out = verbosity_bias(recs, positive_label="good")
        assert out["length_bias_excess"] > 20
        assert "over-rewards length" in out["interpretation"]

    def test_no_bias_when_judge_matches_human(self):
        recs = [BiasRecord(text_len=100, judge_label="good", human_label="good"),
                BiasRecord(text_len=100, judge_label="bad", human_label="bad")] * 5
        out = verbosity_bias(recs, positive_label="good")
        assert out["interpretation"] in ("no notable length bias", "insufficient variation")

    def test_empty(self):
        assert verbosity_bias([])["length_bias_excess"] is None


class TestCalibration:
    def test_perfect_calibration_low_ece(self):
        # confidence == accuracy in each band
        recs = [(0.9, True)] * 9 + [(0.9, False)] * 1   # 0.9 conf, 0.9 acc
        out = confidence_calibration(recs, n_buckets=5)
        assert out["ece"] < 0.05

    def test_overconfident_high_ece(self):
        recs = [(0.99, False)] * 10   # 0.99 conf, 0.0 acc
        out = confidence_calibration(recs, n_buckets=5)
        assert out["ece"] > 0.5

    def test_empty(self):
        assert confidence_calibration([])["ece"] is None


class TestPositionConsistency:
    def test_flip_rate(self):
        # items 0-2 flip when order reversed; 3-9 stable
        def judge(iid):
            n = int(iid)
            return ("A", "B") if n < 3 else ("A", "A")
        out = position_swap_consistency(judge, [str(i) for i in range(10)])
        assert out["compared"] == 10 and out["flips"] == 3
        assert out["flip_rate"] == pytest.approx(0.3)
        assert "position bias" in out["interpretation"]

    def test_robust(self):
        out = position_swap_consistency(lambda i: ("A", "A"), ["1", "2", "3"])
        assert out["flip_rate"] == 0.0 and out["interpretation"] == "robust to order"


class TestEvalCard:
    def test_trustworthy(self):
        card = build_eval_card("sentiment", kappa=0.82, agreement_rate=0.9,
                               verbosity={"length_bias_excess": 5, "interpretation": "no notable length bias"},
                               calibration={"ece": 0.05}, position={"flip_rate": 0.02, "interpretation": "robust to order"})
        assert card["verdict"] == "trustworthy" and card["concerns"] == []

    def test_flags_concerns(self):
        card = build_eval_card("x", kappa=0.4, agreement_rate=0.6,
                               verbosity={"length_bias_excess": 60, "interpretation": "judge over-rewards length"},
                               calibration={"ece": 0.3}, position={"flip_rate": 0.4, "interpretation": "severe position bias"})
        assert card["verdict"] == "needs review"
        assert len(card["concerns"]) >= 3
