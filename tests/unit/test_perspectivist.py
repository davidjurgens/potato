"""Unit tests for perspectivist / soft-label export (E3)."""

import math
import pytest

from potato.server_utils.perspectivist import (
    soft_labels, normalized_entropy, annotator_perspectives, perspectivist_export, SoftLabel,
)


class TestNormalizedEntropy:
    def test_unanimous_is_zero(self):
        assert normalized_entropy({"a": 1.0}) == 0.0

    def test_even_split_is_one(self):
        assert normalized_entropy({"a": 0.5, "b": 0.5}) == pytest.approx(1.0)

    def test_skewed_between(self):
        e = normalized_entropy({"a": 0.75, "b": 0.25})
        assert 0.0 < e < 1.0


class TestSoftLabels:
    def _obs(self):
        return [
            ("u1", "i1", "yes"), ("u2", "i1", "yes"), ("u3", "i1", "yes"),   # unanimous
            ("u1", "i2", "yes"), ("u2", "i2", "no"),  ("u3", "i2", "no"),    # split 1/2
            ("u1", "i3", "yes"), ("u2", "i3", "no"),                          # even split
        ]

    def test_distribution_and_hard_label(self):
        by = {s.item: s for s in soft_labels(self._obs())}
        assert by["i1"].distribution == {"yes": 1.0}
        assert by["i1"].hard_label == "yes" and by["i1"].entropy == 0.0
        assert by["i2"].distribution["no"] == pytest.approx(2 / 3)
        assert by["i2"].hard_label == "no"

    def test_ambiguous_flag(self):
        by = {s.item: s for s in soft_labels(self._obs(), ambiguity_threshold=0.5)}
        assert by["i1"].ambiguous is False     # unanimous
        assert by["i3"].ambiguous is True      # 50/50

    def test_sorted_by_entropy_desc(self):
        ents = [s.entropy for s in soft_labels(self._obs())]
        assert ents == sorted(ents, reverse=True)

    def test_preserves_per_annotator_labels(self):
        by = {s.item: s for s in soft_labels(self._obs())}
        assert by["i2"].annotators == {"u1": "yes", "u2": "no", "u3": "no"}
        assert by["i2"].n_annotators == 3

    def test_empty(self):
        assert soft_labels([]) == []


class TestAnnotatorPerspectives:
    def test_minority_view_tracked(self):
        obs = [("maj1", "i1", "a"), ("maj2", "i1", "a"), ("dissenter", "i1", "b"),
               ("maj1", "i2", "a"), ("maj2", "i2", "a"), ("dissenter", "i2", "b")]
        persp = annotator_perspectives(obs)
        assert persp["dissenter"]["minority_rate"] == 1.0
        assert persp["maj1"]["majority_rate"] == 1.0


class TestExport:
    def test_export_rows_are_jsonl_ready(self):
        rows = perspectivist_export([("u1", "i1", "x"), ("u2", "i1", "y")])
        assert rows and "distribution" in rows[0] and "ambiguous" in rows[0]
        assert set(rows[0]["distribution"]) == {"x", "y"}
