"""
Tests for disagreement detection.

Tests DisagreementType, Disagreement, and DisagreementDetector.

The legacy DisagreementResolver class was removed — disagreement tracking
now lives directly on SoloModeManager.disagreement_ids; see
tests/server/test_solo_mode/test_b1_b7_regressions.py::TestB3DisagreementsAPI.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from potato.solo_mode.disagreement_resolver import (
    DisagreementType,
    Disagreement,
    DisagreementDetector,
)


class TestDisagreementType:
    """Tests for DisagreementType enum."""

    def test_values(self):
        assert DisagreementType.EXACT_MISMATCH.value == "exact_mismatch"
        assert DisagreementType.THRESHOLD_EXCEEDED.value == "threshold"
        assert DisagreementType.LOW_OVERLAP.value == "low_overlap"
        assert DisagreementType.SEMANTIC_DIFFERENCE.value == "semantic"

    def test_from_value(self):
        assert DisagreementType("exact_mismatch") == DisagreementType.EXACT_MISMATCH
        assert DisagreementType("threshold") == DisagreementType.THRESHOLD_EXCEEDED


class TestDisagreement:
    """Tests for Disagreement dataclass."""

    def test_creation(self):
        d = Disagreement(
            id="dis_0001",
            instance_id="inst_1",
            schema_name="sentiment",
            human_label="positive",
            llm_label="negative",
            llm_confidence=0.6,
            disagreement_type=DisagreementType.EXACT_MISMATCH,
        )
        assert d.id == "dis_0001"
        assert d.resolved is False
        assert d.resolution_label is None
        assert d.triggered_revision is False

    def test_serialization_roundtrip(self):
        d = Disagreement(
            id="dis_0002",
            instance_id="inst_2",
            schema_name="topic",
            human_label="sports",
            llm_label="politics",
            llm_confidence=0.7,
            disagreement_type=DisagreementType.EXACT_MISMATCH,
            resolved=True,
            resolution_label="sports",
            resolution_source="human_wins",
            resolved_at=datetime(2025, 1, 1, 12, 0, 0),
            resolution_notes="Clearly sports",
            triggered_revision=True,
        )
        data = d.to_dict()
        restored = Disagreement.from_dict(data)

        assert restored.id == d.id
        assert restored.instance_id == d.instance_id
        assert restored.human_label == d.human_label
        assert restored.llm_label == d.llm_label
        assert restored.llm_confidence == d.llm_confidence
        assert restored.disagreement_type == d.disagreement_type
        assert restored.resolved is True
        assert restored.resolution_label == "sports"
        assert restored.resolution_source == "human_wins"
        assert restored.triggered_revision is True

    def test_serialization_defaults(self):
        d = Disagreement(
            id="dis_0003",
            instance_id="i",
            schema_name="s",
            human_label="a",
            llm_label="b",
            llm_confidence=0.5,
            disagreement_type=DisagreementType.LOW_OVERLAP,
        )
        data = d.to_dict()
        assert data['resolved'] is False
        assert data['resolution_label'] is None
        assert data['resolved_at'] is None


class TestDisagreementDetector:
    """Tests for DisagreementDetector."""

    @pytest.fixture
    def detector(self):
        return DisagreementDetector()

    @pytest.fixture
    def custom_detector(self):
        return DisagreementDetector(thresholds={
            'likert_tolerance': 2,
            'multiselect_jaccard_threshold': 0.7,
            'span_overlap_threshold': 0.8,
        })

    # --- Categorical ---

    def test_categorical_agree(self, detector):
        is_dis, dtype = detector.detect("radio", "positive", "positive")
        assert is_dis is False
        assert dtype == DisagreementType.EXACT_MISMATCH

    def test_categorical_disagree(self, detector):
        is_dis, dtype = detector.detect("radio", "positive", "negative")
        assert is_dis is True
        assert dtype == DisagreementType.EXACT_MISMATCH

    def test_categorical_string_coercion(self, detector):
        """Integer labels should be compared as strings."""
        is_dis, _ = detector.detect("radio", 1, "1")
        assert is_dis is False

    def test_select_type(self, detector):
        """'select' type should use categorical comparison."""
        is_dis, _ = detector.detect("select", "a", "b")
        assert is_dis is True

    def test_unknown_type_falls_back_to_categorical(self, detector):
        is_dis, dtype = detector.detect("unknown_type", "x", "y")
        assert is_dis is True
        assert dtype == DisagreementType.EXACT_MISMATCH

    # --- Likert ---

    def test_likert_agree_within_tolerance(self, detector):
        """Default tolerance is 1."""
        is_dis, _ = detector.detect("likert", 3, 4)
        assert is_dis is False

    def test_likert_disagree_beyond_tolerance(self, detector):
        is_dis, dtype = detector.detect("likert", 1, 5)
        assert is_dis is True
        assert dtype == DisagreementType.THRESHOLD_EXCEEDED

    def test_likert_exact_match(self, detector):
        is_dis, _ = detector.detect("likert", 3, 3)
        assert is_dis is False

    def test_likert_custom_tolerance(self, custom_detector):
        """Custom tolerance of 2."""
        is_dis, _ = custom_detector.detect("likert", 1, 3)
        assert is_dis is False
        is_dis, _ = custom_detector.detect("likert", 1, 4)
        assert is_dis is True

    def test_likert_non_numeric_falls_back(self, detector):
        """Non-numeric likert values should fall back to categorical."""
        is_dis, dtype = detector.detect("likert", "high", "low")
        assert is_dis is True
        assert dtype == DisagreementType.EXACT_MISMATCH

    # --- Multiselect ---

    def test_multiselect_agree(self, detector):
        """Jaccard >= 0.5."""
        is_dis, _ = detector.detect("multiselect", ["a", "b"], ["a", "b"])
        assert is_dis is False

    def test_multiselect_partial_overlap(self, detector):
        """Jaccard = 1/3 < 0.5."""
        is_dis, _ = detector.detect("multiselect", ["a", "b"], ["a", "c"])
        # Jaccard = 1 / 3 = 0.33 < 0.5
        assert is_dis is True

    def test_multiselect_high_overlap(self, detector):
        """Jaccard = 2/3 >= 0.5."""
        is_dis, _ = detector.detect("multiselect", ["a", "b", "c"], ["a", "b"])
        # Jaccard = 2 / 3 = 0.67 >= 0.5
        assert is_dis is False

    def test_multiselect_both_empty(self, detector):
        is_dis, _ = detector.detect("multiselect", [], [])
        assert is_dis is False

    def test_multiselect_single_value_coercion(self, detector):
        """Non-list values are wrapped in a set."""
        is_dis, _ = detector.detect("multiselect", "a", "a")
        assert is_dis is False

    def test_multiselect_custom_threshold(self, custom_detector):
        """Jaccard threshold 0.7."""
        # Jaccard = 2/3 = 0.67 < 0.7
        is_dis, _ = custom_detector.detect("multiselect", ["a", "b", "c"], ["a", "b"])
        assert is_dis is True

    # --- Textbox ---

    def test_textbox_agree(self, detector):
        is_dis, _ = detector.detect("textbox", "Hello World", "hello world")
        assert is_dis is False

    def test_textbox_disagree(self, detector):
        is_dis, dtype = detector.detect("textbox", "Hello", "Goodbye")
        assert is_dis is True
        assert dtype == DisagreementType.SEMANTIC_DIFFERENCE

    def test_textbox_whitespace(self, detector):
        is_dis, _ = detector.detect("textbox", "  hello  ", "hello")
        assert is_dis is False

    # --- Span ---

    def test_span_agree_exact(self, detector):
        h = [{"start": 0, "end": 10}]
        l = [{"start": 0, "end": 10}]
        is_dis, _ = detector.detect("span", h, l)
        assert is_dis is False

    def test_span_disagree_no_overlap(self, detector):
        h = [{"start": 0, "end": 5}]
        l = [{"start": 10, "end": 15}]
        is_dis, _ = detector.detect("span", h, l)
        assert is_dis is True

    def test_span_partial_overlap_below_threshold(self, detector):
        """Overlap = 2/10 = 0.2 < 0.5."""
        h = [{"start": 0, "end": 10}]
        l = [{"start": 8, "end": 15}]
        is_dis, _ = detector.detect("span", h, l)
        assert is_dis is True

    def test_span_partial_overlap_above_threshold(self, detector):
        """Overlap = 5/10 = 0.5 >= 0.5."""
        h = [{"start": 0, "end": 10}]
        l = [{"start": 5, "end": 15}]
        is_dis, _ = detector.detect("span", h, l)
        assert is_dis is False

    def test_span_both_empty(self, detector):
        is_dis, _ = detector.detect("span", [], [])
        assert is_dis is False

    def test_span_one_empty(self, detector):
        is_dis, _ = detector.detect("span", [{"start": 0, "end": 5}], [])
        assert is_dis is True

    def test_span_single_dict(self, detector):
        """Single span dict instead of list."""
        h = {"start": 0, "end": 10}
        l = {"start": 0, "end": 10}
        is_dis, _ = detector.detect("span", h, l)
        assert is_dis is False

    def test_span_none_input(self, detector):
        is_dis, _ = detector.detect("span", None, None)
        assert is_dis is False

    # --- Numeric ---

    def test_numeric_agree(self, detector):
        is_dis, _ = detector.detect("slider", 50, 52, {"min_value": 0, "max_value": 100})
        # tolerance = 10 (10% of range 100), diff = 2
        assert is_dis is False

    def test_numeric_disagree(self, detector):
        is_dis, dtype = detector.detect("slider", 10, 30, {"min_value": 0, "max_value": 100})
        # tolerance = 10, diff = 20
        assert is_dis is True
        assert dtype == DisagreementType.THRESHOLD_EXCEEDED

    def test_numeric_without_schema(self, detector):
        """Without schema, uses 10% of human value as tolerance."""
        is_dis, _ = detector.detect("number", 100, 105)
        # tolerance = 10 (10% of 100), diff = 5
        assert is_dis is False

    def test_numeric_zero_value(self, detector):
        """Zero value uses fallback tolerance of 0.1."""
        is_dis, _ = detector.detect("number", 0, 0.05)
        assert is_dis is False

    def test_numeric_non_numeric_fallback(self, detector):
        is_dis, dtype = detector.detect("slider", "abc", "def")
        assert is_dis is True
        assert dtype == DisagreementType.EXACT_MISMATCH

    # --- normalize_spans ---

    def test_normalize_spans_list(self, detector):
        spans = [{"start": 0, "end": 5, "label": "x"}, {"start": 10, "end": 15}]
        result = detector._normalize_spans(spans)
        assert len(result) == 2
        assert result[0] == {"start": 0, "end": 5}

    def test_normalize_spans_single_dict(self, detector):
        result = detector._normalize_spans({"start": 0, "end": 5})
        assert len(result) == 1

    def test_normalize_spans_empty(self, detector):
        assert detector._normalize_spans(None) == []
        assert detector._normalize_spans([]) == []

    def test_normalize_spans_invalid(self, detector):
        result = detector._normalize_spans([{"x": 1}, "bad"])
        assert result == []
