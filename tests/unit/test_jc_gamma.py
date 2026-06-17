"""Unit tests for span chance-corrected IAA: token κ/α + local γ."""

from potato.judge_calibration.gamma import (
    unit_dissimilarity,
    gamma_agreement,
    _alignment_cost,
)
from potato.judge_calibration.metrics import compute_span_token_iaa, compute_span_report


def _llm(n):
    return n.startswith("llm::")


class TestDissimilarity:
    def test_identical_units(self):
        assert unit_dissimilarity((0, 5, "PER"), (0, 5, "PER")) == 0.0

    def test_label_difference(self):
        # same position, different label -> only categorical term (1.0)
        assert unit_dissimilarity((0, 5, "PER"), (0, 5, "ORG")) == 1.0

    def test_positional_difference(self):
        d = unit_dissimilarity((0, 10, "X"), (5, 15, "X"))
        assert d > 0


class TestAlignment:
    def test_perfect_alignment_zero_cost(self):
        units = [(0, 5, "PER"), (10, 15, "LOC")]
        cost, n = _alignment_cost(units, list(units), 1.0, 1.0, 1.0)
        assert cost == 0.0
        assert n == 2

    def test_unmatched_costs_delta(self):
        cost, n = _alignment_cost([(0, 5, "PER")], [], 1.0, 1.0, 1.0)
        assert cost == 1.0  # one real unit -> empty
        assert n == 1


class TestGamma:
    def test_identical_annotators_high_gamma(self):
        spans = {"i1": [(0, 5, "PER")], "i2": [(2, 8, "LOC")]}
        raters = {"llm::m1": spans, "human::h1": {k: list(v) for k, v in spans.items()}}
        lengths = {"i1": 100, "i2": 100}
        g = gamma_agreement(raters, lengths, is_llm=_llm, n_samples=20, seed=1)
        # perfect observed agreement (disorder 0) -> γ == 1.0
        assert g["gamma"] == 1.0
        assert g["mean_human_llm"] == 1.0
        assert g["approximate"] is True

    def test_deterministic(self):
        spans_a = {"i1": [(0, 5, "PER")]}
        spans_b = {"i1": [(50, 60, "PER")]}
        raters = {"llm::m1": spans_a, "human::h1": spans_b}
        lengths = {"i1": 200}
        g1 = gamma_agreement(raters, lengths, is_llm=_llm, n_samples=15, seed=7)
        g2 = gamma_agreement(raters, lengths, is_llm=_llm, n_samples=15, seed=7)
        assert g1["gamma"] == g2["gamma"]  # seeded -> reproducible

    def test_single_rater_none(self):
        g = gamma_agreement({"llm::m1": {"i1": [(0, 5, "X")]}}, {"i1": 50}, is_llm=_llm)
        assert g["gamma"] is None


class TestTokenKappa:
    def test_perfect_segment_agreement(self):
        # Two spans with a gap -> segments [PER, O, LOC]; 3 categories so kappa
        # has variance and is well-defined (a single-category case is degenerate).
        spans = [(0, 5, "PER"), (10, 15, "LOC")]
        units = {
            "llm::m1": {"i1": list(spans)},
            "human::h1": {"i1": list(spans)},
        }
        res = compute_span_token_iaa(units)
        assert res["cohen"]["mean_human_llm"] == 1.0

    def test_partial_overlap_disagreement(self):
        # one labels [0,10), other [0,5): segment [5,10) is PER vs O -> partial
        units = {
            "llm::m1": {"i1": [(0, 10, "PER")]},
            "human::h1": {"i1": [(0, 5, "PER")]},
        }
        res = compute_span_token_iaa(units)
        # kappa should be defined and < 1 (they disagree on segment [5,10))
        k = res["cohen"]["mean_human_llm"]
        assert k is None or k < 1.0

    def test_report_includes_both_metrics(self):
        gold = {"i1": [{"start": 0, "end": 5, "label": "PER"}]}
        preds = {"i1": [{"start": 0, "end": 5, "label": "PER", "confidence": 1.0}]}
        rep = compute_span_report(
            "ner", ["PER"], {"m1": preds}, {"h1": gold},
            instance_lengths={"i1": 50}, gamma_samples=10,
        )
        assert "token_kappa" in rep["iaa"]
        assert "gamma" in rep["iaa"]
        assert "span_f1" in rep["iaa"]
