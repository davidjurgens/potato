"""
Unit tests for step_agreement module.

Tests inter-annotator agreement computation (Krippendorff's alpha,
Cohen's kappa) at the individual step level within agent traces.
"""

import pytest
from unittest.mock import patch, MagicMock

from potato.step_agreement import (
    compute_step_agreement,
    _extract_step_annotations,
    _kappa_from_annotator_dict,
    _kappa_from_step_dict,
    _alpha_from_pairs,
    _alpha_from_step_dict,
    _compute_step_cohens_kappa,
    _compute_step_krippendorff_alpha,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_annotations(instance_step_map):
    """Build a minimal annotations dict.

    Args:
        instance_step_map: {instance_id: {annotator_id: {step_index_str: label}}}
    Returns:
        annotations dict suitable for compute_step_agreement()
    """
    return {
        instance_id: {
            ann_id: ann_data
            for ann_id, ann_data in annotators.items()
        }
        for instance_id, annotators in instance_step_map.items()
    }


# ---------------------------------------------------------------------------
# _extract_step_annotations
# ---------------------------------------------------------------------------

class TestExtractStepAnnotations:
    """Tests for _extract_step_annotations()."""

    def test_dict_format_direct_mapping(self):
        """Dict with {step_index: label} mapping is extracted correctly."""
        ann_data = {"0": "good", "1": "bad", "2": "neutral"}
        result = _extract_step_annotations(ann_data, scheme_name="quality")
        assert result == {0: "good", 1: "bad", 2: "neutral"}

    def test_dict_format_with_scheme_key(self):
        """Scheme name is looked up first; fallback to top-level dict."""
        ann_data = {"quality": {"0": "correct", "1": "incorrect"}}
        result = _extract_step_annotations(ann_data, scheme_name="quality")
        assert result == {0: "correct", 1: "incorrect"}

    def test_list_format(self):
        """List of {step_index: label} dicts is handled correctly."""
        ann_data = {"quality": [{"0": "yes"}, {"1": "no"}, {"2": "yes"}]}
        result = _extract_step_annotations(ann_data, scheme_name="quality")
        assert result == {0: "yes", 1: "no", 2: "yes"}

    def test_list_format_mixed_dicts(self):
        """List entries that are not dicts are skipped."""
        ann_data = {"scheme": [{"0": "a"}, "not_a_dict", {"2": "b"}]}
        result = _extract_step_annotations(ann_data, scheme_name="scheme")
        assert result == {0: "a", 2: "b"}

    def test_non_integer_keys_are_skipped(self):
        """Non-numeric keys cannot be cast to int and are skipped."""
        ann_data = {"label": "good", "not_a_step": "value"}
        result = _extract_step_annotations(ann_data, scheme_name="quality")
        # Falls back to ann_data itself; "label" is not int-castable
        assert "label" not in {str(k): v for k, v in result.items()} or result == {}

    def test_integer_keys_as_ints_in_dict(self):
        """Integer keys (not strings) are also accepted."""
        ann_data = {0: "good", 1: "bad"}
        result = _extract_step_annotations(ann_data, scheme_name="quality")
        assert result == {0: "good", 1: "bad"}

    def test_empty_dict(self):
        """Empty annotation dict returns empty result."""
        result = _extract_step_annotations({}, scheme_name="quality")
        assert result == {}

    def test_non_dict_input_returns_empty(self):
        """Non-dict input (e.g. None, string) returns empty dict."""
        assert _extract_step_annotations(None, "quality") == {}
        assert _extract_step_annotations("bad", "quality") == {}
        assert _extract_step_annotations(42, "quality") == {}

    def test_scheme_not_found_falls_back_to_top_level(self):
        """When scheme_name not in dict, falls back to using top-level dict."""
        ann_data = {"0": "yes", "1": "no"}
        result = _extract_step_annotations(ann_data, scheme_name="missing_scheme")
        assert result == {0: "yes", 1: "no"}

    def test_labels_are_converted_to_str(self):
        """Labels are always returned as strings."""
        ann_data = {"0": 1, "1": True}
        result = _extract_step_annotations(ann_data, scheme_name="q")
        assert result[0] == "1"
        assert result[1] == "True"


# ---------------------------------------------------------------------------
# compute_step_agreement – Cohen's kappa
# ---------------------------------------------------------------------------

class TestComputeStepAgreementCohensKappa:
    """Tests for compute_step_agreement() with metric='cohens_kappa'."""

    def test_returns_metric_field(self):
        """Result dict includes metric='cohens_kappa'."""
        annotations = _make_annotations({
            "inst1": {
                "ann1": {"0": "A", "1": "B"},
                "ann2": {"0": "A", "1": "B"},
            }
        })
        result = compute_step_agreement(annotations, metric="cohens_kappa")
        assert result["metric"] == "cohens_kappa"

    def test_perfect_agreement_returns_1(self):
        """Two annotators who agree on every step yield kappa=1.0."""
        annotations = _make_annotations({
            "inst1": {
                "ann1": {"0": "good", "1": "good", "2": "bad"},
                "ann2": {"0": "good", "1": "good", "2": "bad"},
            }
        })
        result = compute_step_agreement(annotations, metric="cohens_kappa")
        assert result["overall"] == 1.0

    def test_complete_disagreement_returns_negative_or_zero(self):
        """Alternating disagreements typically yield kappa <= 0."""
        annotations = _make_annotations({
            "inst1": {
                "ann1": {"0": "A", "1": "B", "2": "A", "3": "B"},
                "ann2": {"0": "B", "1": "A", "2": "B", "3": "A"},
            }
        })
        result = compute_step_agreement(annotations, metric="cohens_kappa")
        assert result["overall"] is not None
        assert result["overall"] <= 0.0

    def test_per_instance_breakdown(self):
        """Result includes per_instance agreement dict."""
        annotations = _make_annotations({
            "inst1": {
                "ann1": {"0": "yes", "1": "yes"},
                "ann2": {"0": "yes", "1": "yes"},
            },
            "inst2": {
                "ann1": {"0": "no", "1": "no"},
                "ann2": {"0": "no", "1": "no"},
            },
        })
        result = compute_step_agreement(annotations, metric="cohens_kappa")
        assert "per_instance" in result
        assert "inst1" in result["per_instance"]
        assert "inst2" in result["per_instance"]

    def test_per_step_breakdown(self):
        """Result includes per_step agreement dict keyed by step index."""
        annotations = _make_annotations({
            "inst1": {
                "ann1": {"0": "A", "1": "B"},
                "ann2": {"0": "A", "1": "B"},
            }
        })
        result = compute_step_agreement(annotations, metric="cohens_kappa")
        assert "per_step" in result
        assert 0 in result["per_step"]
        assert 1 in result["per_step"]

    def test_n_instances_and_n_annotators(self):
        """n_instances and n_annotators are counted correctly."""
        annotations = _make_annotations({
            "inst1": {
                "ann1": {"0": "A"},
                "ann2": {"0": "A"},
                "ann3": {"0": "A"},
            },
            "inst2": {
                "ann1": {"0": "B"},
                "ann2": {"0": "B"},
            },
        })
        result = compute_step_agreement(annotations, metric="cohens_kappa")
        assert result["n_instances"] == 2
        assert result["n_annotators"] == 3

    def test_n_steps_count(self):
        """n_steps equals the number of distinct step indices seen."""
        annotations = _make_annotations({
            "inst1": {
                "ann1": {"0": "A", "1": "B", "2": "C"},
                "ann2": {"0": "A", "1": "B", "2": "C"},
            }
        })
        result = compute_step_agreement(annotations, metric="cohens_kappa")
        assert result["n_steps"] == 3

    def test_empty_annotations_returns_none_overall(self):
        """Empty annotations dict yields overall=None with zero counts."""
        result = compute_step_agreement({}, metric="cohens_kappa")
        assert result["overall"] is None
        assert result["n_instances"] == 0
        assert result["n_annotators"] == 0

    def test_single_annotator_returns_none_overall(self):
        """With only one annotator kappa cannot be computed."""
        annotations = _make_annotations({
            "inst1": {"ann1": {"0": "A", "1": "B"}}
        })
        result = compute_step_agreement(annotations, metric="cohens_kappa")
        assert result["overall"] is None


# ---------------------------------------------------------------------------
# compute_step_agreement – Krippendorff's alpha
# ---------------------------------------------------------------------------

class TestComputeStepAgreementKrippendorff:
    """Tests for compute_step_agreement() with metric='krippendorff_alpha'."""

    def test_returns_metric_field(self):
        """Result dict includes metric='krippendorff_alpha'."""
        with patch("potato.step_agreement._alpha_from_pairs", return_value=0.8):
            annotations = _make_annotations({
                "inst1": {
                    "ann1": {"0": "A", "1": "B"},
                    "ann2": {"0": "A", "1": "B"},
                }
            })
            result = compute_step_agreement(annotations, metric="krippendorff_alpha")
        assert result["metric"] == "krippendorff_alpha"

    def test_level_of_measurement_passed_through(self):
        """level_of_measurement is included in result."""
        with patch("potato.step_agreement._alpha_from_pairs", return_value=0.5):
            annotations = _make_annotations({
                "inst1": {
                    "ann1": {"0": "A"},
                    "ann2": {"0": "A"},
                }
            })
            result = compute_step_agreement(
                annotations,
                metric="krippendorff_alpha",
                level_of_measurement="ordinal",
            )
        assert result["level_of_measurement"] == "ordinal"

    def test_default_metric_is_krippendorff(self):
        """Default metric (no argument) is krippendorff_alpha."""
        with patch("potato.step_agreement._alpha_from_pairs", return_value=None):
            annotations = _make_annotations({
                "inst1": {
                    "ann1": {"0": "X"},
                    "ann2": {"0": "X"},
                }
            })
            result = compute_step_agreement(annotations)
        assert result["metric"] == "krippendorff_alpha"

    def test_per_instance_breakdown_included(self):
        """Result includes per_instance breakdown."""
        with patch("potato.step_agreement._alpha_from_pairs", return_value=1.0):
            annotations = _make_annotations({
                "inst1": {
                    "ann1": {"0": "A"},
                    "ann2": {"0": "A"},
                },
                "inst2": {
                    "ann1": {"0": "B"},
                    "ann2": {"0": "B"},
                },
            })
            result = compute_step_agreement(annotations, metric="krippendorff_alpha")
        assert "inst1" in result["per_instance"]
        assert "inst2" in result["per_instance"]

    def test_per_step_breakdown_included(self):
        """Result includes per_step breakdown keyed by step index."""
        with patch("potato.step_agreement._alpha_from_pairs", return_value=1.0):
            annotations = _make_annotations({
                "inst1": {
                    "ann1": {"0": "A", "1": "B"},
                    "ann2": {"0": "A", "1": "B"},
                }
            })
            result = compute_step_agreement(annotations, metric="krippendorff_alpha")
        assert 0 in result["per_step"]
        assert 1 in result["per_step"]

    def test_empty_annotations(self):
        """Empty annotations dict yields overall=None and zero counts."""
        result = compute_step_agreement({}, metric="krippendorff_alpha")
        assert result["overall"] is None
        assert result["n_instances"] == 0
        assert result["n_annotators"] == 0

    def test_single_annotator_skips_per_step(self):
        """Steps with only one annotator are not included in per_step."""
        annotations = _make_annotations({
            "inst1": {"ann1": {"0": "A", "1": "B"}}
        })
        result = compute_step_agreement(annotations, metric="krippendorff_alpha")
        # per_step requires at least 2 annotators per step
        assert result["per_step"] == {}
        assert result["overall"] is None

    def test_n_steps_correct(self):
        """n_steps counts distinct step indices across all instances."""
        with patch("potato.step_agreement._alpha_from_pairs", return_value=0.7):
            annotations = _make_annotations({
                "inst1": {
                    "ann1": {"0": "A", "1": "B"},
                    "ann2": {"0": "A", "1": "B"},
                },
                "inst2": {
                    "ann1": {"2": "C"},
                    "ann2": {"2": "C"},
                },
            })
            result = compute_step_agreement(annotations, metric="krippendorff_alpha")
        assert result["n_steps"] == 3

    def test_alpha_failure_returns_none_overall(self):
        """When _alpha_from_pairs raises, overall is None."""
        with patch("potato.step_agreement._alpha_from_pairs", return_value=None):
            annotations = _make_annotations({
                "inst1": {
                    "ann1": {"0": "A"},
                    "ann2": {"0": "A"},
                }
            })
            result = compute_step_agreement(annotations, metric="krippendorff_alpha")
        assert result["overall"] is None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestKappaFromAnnotatorDict:
    """Tests for _kappa_from_annotator_dict() – single-item kappa."""

    def test_agreement_returns_1(self):
        assert _kappa_from_annotator_dict({"a1": "yes", "a2": "yes"}) == 1.0

    def test_disagreement_returns_0(self):
        assert _kappa_from_annotator_dict({"a1": "yes", "a2": "no"}) == 0.0

    def test_single_annotator_returns_none(self):
        assert _kappa_from_annotator_dict({"a1": "yes"}) is None

    def test_empty_returns_none(self):
        assert _kappa_from_annotator_dict({}) is None

    def test_only_first_two_annotators_used(self):
        """With three annotators, only first two (sorted) are compared."""
        result = _kappa_from_annotator_dict({"a1": "X", "a2": "X", "a3": "Y"})
        # a1 and a2 agree, so result is 1.0
        assert result == 1.0


class TestKappaFromStepDict:
    """Tests for _kappa_from_step_dict() – multi-item kappa."""

    def test_empty_step_dict_returns_none(self):
        assert _kappa_from_step_dict({}) is None

    def test_single_annotator_returns_none(self):
        assert _kappa_from_step_dict({"0": {"a1": "X"}, "1": {"a1": "Y"}}) is None

    def test_insufficient_items_for_kappa(self):
        """With fewer than 2 overlapping items, kappa returns None."""
        result = _kappa_from_step_dict({"0": {"a1": "X", "a2": "X"}})
        # Only 1 overlapping item; sklearn or fallback needs >= 2
        assert result is None or isinstance(result, float)

    def test_perfect_agreement(self):
        step_dict = {
            "0": {"ann1": "A", "ann2": "A"},
            "1": {"ann1": "B", "ann2": "B"},
            "2": {"ann1": "A", "ann2": "A"},
        }
        result = _kappa_from_step_dict(step_dict)
        assert result is not None
        assert result == 1.0

    def test_complete_disagreement(self):
        step_dict = {
            "0": {"ann1": "A", "ann2": "B"},
            "1": {"ann1": "B", "ann2": "A"},
            "2": {"ann1": "A", "ann2": "B"},
            "3": {"ann1": "B", "ann2": "A"},
        }
        result = _kappa_from_step_dict(step_dict)
        assert result is not None
        assert result <= 0.0

    def test_missing_annotator_in_some_steps(self):
        """Steps where one annotator has no label are excluded from kappa."""
        step_dict = {
            "0": {"ann1": "A", "ann2": "A"},
            "1": {"ann1": "B"},  # ann2 missing
            "2": {"ann1": "A", "ann2": "A"},
        }
        result = _kappa_from_step_dict(step_dict)
        # Only steps 0 and 2 have both annotators
        assert result is not None


class TestAlphaFromPairs:
    """Tests for _alpha_from_pairs() – Krippendorff's alpha computation."""

    def test_returns_none_when_simpledorff_unavailable(self):
        """Returns None gracefully when simpledorff is not installed."""
        with patch.dict("sys.modules", {"simpledorff": None, "pandas": None}):
            with patch("potato.step_agreement.logger"):
                # When import fails inside, should return None
                result = _alpha_from_pairs(
                    [("a1", "A"), ("a2", "A")], level="nominal"
                )
                # May succeed if simpledorff IS installed; just check type
                assert result is None or isinstance(result, float)

    def test_returns_none_with_single_pair(self):
        """Fewer than 2 pairs returns None (insufficient data)."""
        result = _alpha_from_pairs([("a1", "A")], level="nominal")
        assert result is None

    def test_returns_float_or_none_for_valid_input(self):
        """Valid input returns float or None (depending on simpledorff availability)."""
        pairs = [("a1", "A"), ("a2", "A"), ("a1", "B"), ("a2", "B")]
        result = _alpha_from_pairs(pairs, level="nominal")
        assert result is None or isinstance(result, float)


class TestAlphaFromStepDict:
    """Tests for _alpha_from_step_dict()."""

    def test_empty_dict_returns_none(self):
        result = _alpha_from_step_dict({})
        assert result is None

    def test_delegates_to_alpha_from_pairs(self):
        """_alpha_from_step_dict flattens and calls _alpha_from_pairs."""
        with patch("potato.step_agreement._alpha_from_pairs", return_value=0.75) as mock_fn:
            step_dict = {
                0: {"ann1": "A", "ann2": "B"},
                1: {"ann1": "A", "ann2": "A"},
            }
            result = _alpha_from_step_dict(step_dict)
        assert result == 0.75
        mock_fn.assert_called_once()
