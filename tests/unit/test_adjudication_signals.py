"""
Unit tests for AdjudicationManager behavioral signal analysis methods.

Tests cover:
- get_annotator_signals(): flag generation and metric computation
- _get_user_times(): collecting annotation times across queue items
- _compute_user_agreement_rate(): agreement with consensus labels
- _check_similar_item_consistency(): label differences on similar items
- _get_consensus_label(): majority label extraction from AdjudicationItem
- get_similar_items(): enriched similar item results from similarity engine
"""

import logging
import math
import threading

import pytest
from unittest.mock import MagicMock, patch

from potato.adjudication import (
    AdjudicationConfig,
    AdjudicationItem,
    AdjudicationDecision,
    AdjudicationManager,
    clear_adjudication_manager,
)


@pytest.fixture(autouse=True)
def cleanup():
    """Clear singleton between tests."""
    clear_adjudication_manager()
    yield
    clear_adjudication_manager()


def _make_item(instance_id, annotations=None, behavioral_data=None,
               agreement_scores=None, overall_agreement=0.5, num_annotators=2,
               status="pending", span_annotations=None):
    """Helper to create AdjudicationItem with sensible defaults."""
    return AdjudicationItem(
        instance_id=instance_id,
        annotations=annotations or {},
        span_annotations=span_annotations or {},
        behavioral_data=behavioral_data or {},
        agreement_scores=agreement_scores or {},
        overall_agreement=overall_agreement,
        num_annotators=num_annotators,
        status=status,
    )


def _make_manager(adj_config_overrides=None, config_overrides=None):
    """
    Create an AdjudicationManager without real server dependencies.

    Bypasses __init__ and sets up internal state directly.
    """
    mgr = AdjudicationManager.__new__(AdjudicationManager)
    mgr.config = {"annotation_schemes": [{"name": "sentiment"}]}
    if config_overrides:
        mgr.config.update(config_overrides)

    defaults = dict(
        enabled=True,
        adjudicator_users=["expert_1"],
        min_annotations=2,
        agreement_threshold=0.75,
        show_all_items=False,
        show_annotator_names=True,
        show_timing_data=True,
        show_agreement_scores=True,
        fast_decision_warning_ms=2000,
        require_confidence=True,
        require_notes_on_override=False,
        error_taxonomy=["ambiguous_text", "guideline_gap", "annotator_error"],
        similarity_enabled=False,
        similarity_model="all-MiniLM-L6-v2",
        similarity_top_k=5,
        similarity_precompute=True,
        output_subdir="adjudication",
    )
    if adj_config_overrides:
        defaults.update(adj_config_overrides)

    mgr.adj_config = AdjudicationConfig(**defaults)
    mgr.queue = {}
    mgr.decisions = {}
    mgr._queue_built = True
    mgr._lock = threading.RLock()
    mgr.logger = logging.getLogger("test_adjudication_signals")
    mgr.similarity_engine = None
    return mgr


class TestGetUserTimes:
    """Tests for _get_user_times collecting annotation times across queue items."""

    def test_collects_times_for_user(self):
        mgr = _make_manager()
        mgr.queue["item_1"] = _make_item(
            "item_1",
            behavioral_data={"alice": {"total_time_ms": 3000}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            behavioral_data={"alice": {"total_time_ms": 5000}},
        )
        mgr.queue["item_3"] = _make_item(
            "item_3",
            behavioral_data={"alice": {"total_time_ms": 4000}},
        )

        times = mgr._get_user_times("alice")
        assert sorted(times) == [3000, 4000, 5000]

    def test_ignores_zero_times(self):
        mgr = _make_manager()
        mgr.queue["item_1"] = _make_item(
            "item_1",
            behavioral_data={"alice": {"total_time_ms": 3000}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            behavioral_data={"alice": {"total_time_ms": 0}},
        )

        times = mgr._get_user_times("alice")
        assert times == [3000]

    def test_returns_empty_for_unknown_user(self):
        mgr = _make_manager()
        mgr.queue["item_1"] = _make_item(
            "item_1",
            behavioral_data={"alice": {"total_time_ms": 3000}},
        )

        times = mgr._get_user_times("bob")
        assert times == []

    def test_ignores_other_users(self):
        mgr = _make_manager()
        mgr.queue["item_1"] = _make_item(
            "item_1",
            behavioral_data={
                "alice": {"total_time_ms": 3000},
                "bob": {"total_time_ms": 7000},
            },
        )

        times = mgr._get_user_times("alice")
        assert times == [3000]

    def test_handles_missing_behavioral_data(self):
        mgr = _make_manager()
        mgr.queue["item_1"] = _make_item(
            "item_1",
            behavioral_data={},
        )

        times = mgr._get_user_times("alice")
        assert times == []

    def test_handles_behavioral_data_with_to_dict(self):
        """Behavioral data objects with to_dict() are handled correctly."""
        mgr = _make_manager()

        bd_obj = MagicMock()
        bd_obj.to_dict.return_value = {"total_time_ms": 4500}

        mgr.queue["item_1"] = _make_item(
            "item_1",
            behavioral_data={"alice": bd_obj},
        )

        times = mgr._get_user_times("alice")
        assert times == [4500]


class TestConsensusLabel:
    """Tests for _get_consensus_label extracting majority label."""

    def test_radio_string_values_unanimous(self):
        mgr = _make_manager()
        item = _make_item(
            "item_1",
            annotations={
                "user_1": {"sentiment": "positive"},
                "user_2": {"sentiment": "positive"},
                "user_3": {"sentiment": "positive"},
            },
        )
        consensus = mgr._get_consensus_label(item)
        assert consensus == "positive"

    def test_radio_string_values_majority(self):
        mgr = _make_manager()
        item = _make_item(
            "item_1",
            annotations={
                "user_1": {"sentiment": "positive"},
                "user_2": {"sentiment": "negative"},
                "user_3": {"sentiment": "positive"},
            },
        )
        consensus = mgr._get_consensus_label(item)
        assert consensus == "positive"

    def test_multiselect_dict_values(self):
        mgr = _make_manager()
        item = _make_item(
            "item_1",
            annotations={
                "user_1": {"topics": {"food": True, "service": True}},
                "user_2": {"topics": {"food": True, "service": True}},
                "user_3": {"topics": {"food": True, "atmosphere": True}},
            },
        )
        consensus = mgr._get_consensus_label(item)
        # Two users selected food+service, one selected food+atmosphere
        assert consensus == "food, service"

    def test_multiselect_no_true_keys(self):
        """When dict values have no True keys, the str() of the dict is used."""
        mgr = _make_manager()
        item = _make_item(
            "item_1",
            annotations={
                "user_1": {"topics": {"food": False}},
                "user_2": {"topics": {"food": False}},
            },
        )
        consensus = mgr._get_consensus_label(item)
        # Falls back to str(val) since no selected keys
        assert consensus is not None

    def test_empty_annotations(self):
        mgr = _make_manager()
        item = _make_item("item_1", annotations={})
        consensus = mgr._get_consensus_label(item)
        assert consensus is None

    def test_single_annotator(self):
        mgr = _make_manager()
        item = _make_item(
            "item_1",
            annotations={"user_1": {"sentiment": "neutral"}},
        )
        consensus = mgr._get_consensus_label(item)
        assert consensus == "neutral"

    def test_tie_returns_one_value(self):
        """When there is a tie, Counter.most_common returns one of them."""
        mgr = _make_manager()
        item = _make_item(
            "item_1",
            annotations={
                "user_1": {"sentiment": "positive"},
                "user_2": {"sentiment": "negative"},
            },
        )
        consensus = mgr._get_consensus_label(item)
        assert consensus in ("positive", "negative")


class TestComputeUserAgreementRate:
    """Tests for _compute_user_agreement_rate."""

    def test_perfect_agreement(self):
        mgr = _make_manager()
        # User always agrees with consensus (majority)
        for i in range(5):
            mgr.queue[f"item_{i}"] = _make_item(
                f"item_{i}",
                annotations={
                    "alice": {"sentiment": "positive"},
                    "bob": {"sentiment": "positive"},
                    "carol": {"sentiment": "positive"},
                },
            )

        rate = mgr._compute_user_agreement_rate("alice")
        assert rate == 1.0

    def test_zero_agreement(self):
        mgr = _make_manager()
        # Alice always disagrees with majority (bob + carol agree)
        for i in range(4):
            mgr.queue[f"item_{i}"] = _make_item(
                f"item_{i}",
                annotations={
                    "alice": {"sentiment": "negative"},
                    "bob": {"sentiment": "positive"},
                    "carol": {"sentiment": "positive"},
                },
            )

        rate = mgr._compute_user_agreement_rate("alice")
        assert rate == 0.0

    def test_partial_agreement(self):
        mgr = _make_manager()
        # Alice agrees on 2 out of 4 items
        for i in range(2):
            mgr.queue[f"agree_{i}"] = _make_item(
                f"agree_{i}",
                annotations={
                    "alice": {"sentiment": "positive"},
                    "bob": {"sentiment": "positive"},
                    "carol": {"sentiment": "positive"},
                },
            )
        for i in range(2):
            mgr.queue[f"disagree_{i}"] = _make_item(
                f"disagree_{i}",
                annotations={
                    "alice": {"sentiment": "negative"},
                    "bob": {"sentiment": "positive"},
                    "carol": {"sentiment": "positive"},
                },
            )

        rate = mgr._compute_user_agreement_rate("alice")
        assert rate == 0.5

    def test_returns_none_when_fewer_than_3_items(self):
        mgr = _make_manager()
        # Only 2 items
        for i in range(2):
            mgr.queue[f"item_{i}"] = _make_item(
                f"item_{i}",
                annotations={
                    "alice": {"sentiment": "positive"},
                    "bob": {"sentiment": "positive"},
                },
            )

        rate = mgr._compute_user_agreement_rate("alice")
        assert rate is None

    def test_returns_none_when_zero_items(self):
        mgr = _make_manager()
        rate = mgr._compute_user_agreement_rate("alice")
        assert rate is None

    def test_skips_items_where_user_not_present(self):
        mgr = _make_manager()
        # 3 items where alice participated, plus 2 where she did not
        for i in range(3):
            mgr.queue[f"with_alice_{i}"] = _make_item(
                f"with_alice_{i}",
                annotations={
                    "alice": {"sentiment": "positive"},
                    "bob": {"sentiment": "positive"},
                    "carol": {"sentiment": "positive"},
                },
            )
        for i in range(2):
            mgr.queue[f"without_alice_{i}"] = _make_item(
                f"without_alice_{i}",
                annotations={
                    "bob": {"sentiment": "negative"},
                    "carol": {"sentiment": "negative"},
                },
            )

        rate = mgr._compute_user_agreement_rate("alice")
        assert rate == 1.0


class TestCheckSimilarItemConsistency:
    """Tests for _check_similar_item_consistency."""

    def test_returns_zero_when_no_similarity_engine(self):
        mgr = _make_manager()
        mgr.similarity_engine = None

        count = mgr._check_similar_item_consistency("alice", "item_1")
        assert count == 0

    def test_returns_zero_when_no_similar_items(self):
        mgr = _make_manager()
        mock_engine = MagicMock()
        mock_engine.find_similar.return_value = []
        mgr.similarity_engine = mock_engine

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
        )

        count = mgr._check_similar_item_consistency("alice", "item_1")
        assert count == 0

    def test_detects_inconsistency(self):
        mgr = _make_manager()
        mock_engine = MagicMock()
        # item_2 is very similar (0.95) to item_1
        mock_engine.find_similar.return_value = [("item_2", 0.95)]
        mgr.similarity_engine = mock_engine

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={"alice": {"sentiment": "negative"}},
        )

        count = mgr._check_similar_item_consistency("alice", "item_1")
        assert count == 1

    def test_no_inconsistency_when_labels_match(self):
        mgr = _make_manager()
        mock_engine = MagicMock()
        mock_engine.find_similar.return_value = [("item_2", 0.90)]
        mgr.similarity_engine = mock_engine

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={"alice": {"sentiment": "positive"}},
        )

        count = mgr._check_similar_item_consistency("alice", "item_1")
        assert count == 0

    def test_ignores_items_below_similarity_threshold(self):
        """Items with similarity < 0.8 are not checked."""
        mgr = _make_manager()
        mock_engine = MagicMock()
        # Similar items sorted by score desc; second is below 0.8
        mock_engine.find_similar.return_value = [
            ("item_2", 0.85),
            ("item_3", 0.75),
        ]
        mgr.similarity_engine = mock_engine

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={"alice": {"sentiment": "negative"}},
        )
        mgr.queue["item_3"] = _make_item(
            "item_3",
            annotations={"alice": {"sentiment": "negative"}},
        )

        count = mgr._check_similar_item_consistency("alice", "item_1")
        # Only item_2 counts (score >= 0.8); item_3 is below threshold
        assert count == 1

    def test_skips_items_where_user_not_present(self):
        mgr = _make_manager()
        mock_engine = MagicMock()
        mock_engine.find_similar.return_value = [("item_2", 0.90)]
        mgr.similarity_engine = mock_engine

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={"bob": {"sentiment": "negative"}},
        )

        count = mgr._check_similar_item_consistency("alice", "item_1")
        assert count == 0

    def test_multiple_inconsistencies(self):
        mgr = _make_manager()
        mock_engine = MagicMock()
        mock_engine.find_similar.return_value = [
            ("item_2", 0.95),
            ("item_3", 0.90),
            ("item_4", 0.85),
        ]
        mgr.similarity_engine = mock_engine

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={"alice": {"sentiment": "negative"}},
        )
        mgr.queue["item_3"] = _make_item(
            "item_3",
            annotations={"alice": {"sentiment": "neutral"}},
        )
        mgr.queue["item_4"] = _make_item(
            "item_4",
            annotations={"alice": {"sentiment": "positive"}},
        )

        count = mgr._check_similar_item_consistency("alice", "item_1")
        # item_2 and item_3 differ from "positive"; item_4 matches
        assert count == 2

    def test_returns_zero_when_item_not_in_queue(self):
        mgr = _make_manager()
        mock_engine = MagicMock()
        mock_engine.find_similar.return_value = [("item_2", 0.90)]
        mgr.similarity_engine = mock_engine

        count = mgr._check_similar_item_consistency("alice", "item_1")
        assert count == 0

    def test_returns_zero_when_user_not_on_item(self):
        mgr = _make_manager()
        mock_engine = MagicMock()
        mock_engine.find_similar.return_value = [("item_2", 0.90)]
        mgr.similarity_engine = mock_engine

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"bob": {"sentiment": "positive"}},
        )

        count = mgr._check_similar_item_consistency("alice", "item_1")
        assert count == 0

    def test_dict_values_consistency_check(self):
        """Multiselect dict labels are compared correctly."""
        mgr = _make_manager()
        mock_engine = MagicMock()
        mock_engine.find_similar.return_value = [("item_2", 0.90)]
        mgr.similarity_engine = mock_engine

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"topics": {"food": True, "service": True}}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={"alice": {"topics": {"food": True, "atmosphere": True}}},
        )

        count = mgr._check_similar_item_consistency("alice", "item_1")
        # "food, service" vs "atmosphere, food" -- different
        assert count == 1


class TestGetAnnotatorSignals:
    """Tests for get_annotator_signals flag generation and metric computation."""

    def test_speed_z_score_flag_unusually_fast(self):
        """Flag generated when annotation time z-score is below -2.0."""
        mgr = _make_manager()

        # Create 5 items with typical times for this user (mean ~5000ms)
        for i in range(5):
            mgr.queue[f"item_{i}"] = _make_item(
                f"item_{i}",
                annotations={"alice": {"sentiment": "positive"}},
                behavioral_data={"alice": {"total_time_ms": 5000}},
            )

        # Now the item being checked has an extremely fast time
        mgr.queue["fast_item"] = _make_item(
            "fast_item",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {"total_time_ms": 200}},
        )

        result = mgr.get_annotator_signals("alice", "fast_item")

        flag_types = [f["type"] for f in result["flags"]]
        assert "unusually_fast" in flag_types
        assert result["metrics"]["speed_z_score"] < -2.0

    def test_fast_decision_warning(self):
        """Flag generated when annotation time is below fast_decision_warning_ms."""
        mgr = _make_manager(adj_config_overrides={"fast_decision_warning_ms": 2000})

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {"total_time_ms": 500}},
        )

        result = mgr.get_annotator_signals("alice", "item_1")

        flag_types = [f["type"] for f in result["flags"]]
        assert "fast_decision" in flag_types
        fast_flag = [f for f in result["flags"] if f["type"] == "fast_decision"][0]
        assert fast_flag["severity"] == "medium"
        assert "500ms" in fast_flag["message"]

    def test_excessive_changes_flag(self):
        """Flag generated when annotation changes exceed 5."""
        mgr = _make_manager()

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {
                "total_time_ms": 10000,
                "annotation_changes": 8,
            }},
        )

        result = mgr.get_annotator_signals("alice", "item_1")

        flag_types = [f["type"] for f in result["flags"]]
        assert "excessive_changes" in flag_types
        assert result["metrics"]["annotation_changes"] == 8

    def test_low_agreement_flag(self):
        """Flag generated when user agreement rate is below 0.4."""
        mgr = _make_manager()

        # Create 4 items where alice always disagrees with consensus
        for i in range(4):
            mgr.queue[f"item_{i}"] = _make_item(
                f"item_{i}",
                annotations={
                    "alice": {"sentiment": "negative"},
                    "bob": {"sentiment": "positive"},
                    "carol": {"sentiment": "positive"},
                },
                behavioral_data={
                    "alice": {"total_time_ms": 5000},
                    "bob": {"total_time_ms": 5000},
                    "carol": {"total_time_ms": 5000},
                },
            )

        result = mgr.get_annotator_signals("alice", "item_0")

        flag_types = [f["type"] for f in result["flags"]]
        assert "low_agreement" in flag_types
        assert result["metrics"]["agreement_rate"] == 0.0

    def test_similar_item_inconsistency_flag(self):
        """Flag generated when user labels similar items differently."""
        mgr = _make_manager()

        mock_engine = MagicMock()
        mock_engine.enabled = True
        mock_engine.find_similar.return_value = [("item_2", 0.95)]
        mgr.similarity_engine = mock_engine

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {"total_time_ms": 5000}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={"alice": {"sentiment": "negative"}},
            behavioral_data={"alice": {"total_time_ms": 5000}},
        )

        result = mgr.get_annotator_signals("alice", "item_1")

        flag_types = [f["type"] for f in result["flags"]]
        assert "similar_item_inconsistency" in flag_types
        assert result["metrics"]["similar_item_inconsistencies"] == 1

    def test_no_flags_when_everything_normal(self):
        """No flags generated for normal annotation behavior."""
        mgr = _make_manager()

        # Create 5 items with consistent times and labels
        for i in range(5):
            mgr.queue[f"item_{i}"] = _make_item(
                f"item_{i}",
                annotations={
                    "alice": {"sentiment": "positive"},
                    "bob": {"sentiment": "positive"},
                    "carol": {"sentiment": "positive"},
                },
                behavioral_data={
                    "alice": {"total_time_ms": 5000, "annotation_changes": 2},
                },
            )

        result = mgr.get_annotator_signals("alice", "item_0")

        assert result["flags"] == []
        assert result["user_id"] == "alice"
        assert result["instance_id"] == "item_0"
        assert result["metrics"]["total_time_ms"] == 5000
        assert result["metrics"]["annotation_changes"] == 2
        assert result["metrics"]["agreement_rate"] == 1.0

    def test_returns_empty_when_item_not_in_queue(self):
        """Returns empty flags and metrics when item is not in queue."""
        mgr = _make_manager()

        result = mgr.get_annotator_signals("alice", "nonexistent")

        assert result["user_id"] == "alice"
        assert result["instance_id"] == "nonexistent"
        assert result["flags"] == []
        assert result["metrics"] == {}

    def test_speed_z_score_not_computed_with_fewer_than_3_times(self):
        """Speed z-score is not computed when fewer than 3 data points exist."""
        mgr = _make_manager()

        # Only 2 items total
        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {"total_time_ms": 5000}},
        )
        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {"total_time_ms": 100}},
        )

        result = mgr.get_annotator_signals("alice", "item_2")

        assert "speed_z_score" not in result["metrics"]
        # fast_decision may still fire, but not unusually_fast
        flag_types = [f["type"] for f in result["flags"]]
        assert "unusually_fast" not in flag_types

    def test_agreement_rate_not_flagged_when_insufficient_data(self):
        """Agreement rate flag not generated when < 3 items for the user."""
        mgr = _make_manager()

        # Only 2 items for alice
        for i in range(2):
            mgr.queue[f"item_{i}"] = _make_item(
                f"item_{i}",
                annotations={
                    "alice": {"sentiment": "negative"},
                    "bob": {"sentiment": "positive"},
                    "carol": {"sentiment": "positive"},
                },
                behavioral_data={
                    "alice": {"total_time_ms": 5000},
                },
            )

        result = mgr.get_annotator_signals("alice", "item_0")

        flag_types = [f["type"] for f in result["flags"]]
        assert "low_agreement" not in flag_types
        # agreement_rate should not be in metrics since it returns None
        assert "agreement_rate" not in result["metrics"]

    def test_no_fast_decision_when_time_is_zero(self):
        """Fast decision flag not generated when time is 0 (missing data)."""
        mgr = _make_manager()

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {"total_time_ms": 0}},
        )

        result = mgr.get_annotator_signals("alice", "item_1")

        flag_types = [f["type"] for f in result["flags"]]
        assert "fast_decision" not in flag_types

    def test_no_fast_decision_when_threshold_is_zero(self):
        """Fast decision flag not generated when threshold is disabled (0)."""
        mgr = _make_manager(adj_config_overrides={"fast_decision_warning_ms": 0})

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {"total_time_ms": 100}},
        )

        result = mgr.get_annotator_signals("alice", "item_1")

        flag_types = [f["type"] for f in result["flags"]]
        assert "fast_decision" not in flag_types

    def test_no_excessive_changes_at_threshold(self):
        """No excessive_changes flag when changes is exactly 5."""
        mgr = _make_manager()

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {
                "total_time_ms": 10000,
                "annotation_changes": 5,
            }},
        )

        result = mgr.get_annotator_signals("alice", "item_1")

        flag_types = [f["type"] for f in result["flags"]]
        assert "excessive_changes" not in flag_types

    def test_no_similarity_check_when_engine_disabled(self):
        """No similar_item_inconsistency when similarity engine is None."""
        mgr = _make_manager()
        mgr.similarity_engine = None

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {"total_time_ms": 5000}},
        )

        result = mgr.get_annotator_signals("alice", "item_1")

        flag_types = [f["type"] for f in result["flags"]]
        assert "similar_item_inconsistency" not in flag_types
        assert "similar_item_inconsistencies" not in result["metrics"]

    def test_multiple_flags_simultaneously(self):
        """Multiple flags can be generated at once."""
        mgr = _make_manager(adj_config_overrides={"fast_decision_warning_ms": 2000})

        # Create enough items for z-score and agreement calculations
        # Alice is always wrong and always fast
        for i in range(5):
            mgr.queue[f"item_{i}"] = _make_item(
                f"item_{i}",
                annotations={
                    "alice": {"sentiment": "negative"},
                    "bob": {"sentiment": "positive"},
                    "carol": {"sentiment": "positive"},
                },
                behavioral_data={
                    "alice": {"total_time_ms": 5000, "annotation_changes": 1},
                },
            )

        # The target item: very fast, many changes, alice still disagrees
        mgr.queue["target"] = _make_item(
            "target",
            annotations={
                "alice": {"sentiment": "negative"},
                "bob": {"sentiment": "positive"},
                "carol": {"sentiment": "positive"},
            },
            behavioral_data={
                "alice": {"total_time_ms": 300, "annotation_changes": 10},
            },
        )

        result = mgr.get_annotator_signals("alice", "target")

        flag_types = [f["type"] for f in result["flags"]]
        assert "fast_decision" in flag_types
        assert "excessive_changes" in flag_types
        assert "low_agreement" in flag_types
        assert "unusually_fast" in flag_types

    def test_speed_z_score_with_zero_std_dev(self):
        """No z-score flag when all times are identical (std dev = 0)."""
        mgr = _make_manager()

        # All times are exactly the same
        for i in range(5):
            mgr.queue[f"item_{i}"] = _make_item(
                f"item_{i}",
                annotations={"alice": {"sentiment": "positive"}},
                behavioral_data={"alice": {"total_time_ms": 5000}},
            )

        result = mgr.get_annotator_signals("alice", "item_0")

        # With zero std dev, z-score cannot be computed
        assert "speed_z_score" not in result["metrics"]
        flag_types = [f["type"] for f in result["flags"]]
        assert "unusually_fast" not in flag_types

    def test_behavioral_data_with_to_dict_method(self):
        """Behavioral data objects with to_dict() are handled in signals."""
        mgr = _make_manager()

        bd_obj = MagicMock()
        bd_obj.to_dict.return_value = {
            "total_time_ms": 500,
            "annotation_changes": 2,
        }

        mgr.queue["item_1"] = _make_item(
            "item_1",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": bd_obj},
        )

        result = mgr.get_annotator_signals("alice", "item_1")

        assert result["metrics"]["total_time_ms"] == 500
        flag_types = [f["type"] for f in result["flags"]]
        assert "fast_decision" in flag_types

    def test_instance_id_converted_to_string(self):
        """Instance ID is converted to string for lookup."""
        mgr = _make_manager()

        mgr.queue["42"] = _make_item(
            "42",
            annotations={"alice": {"sentiment": "positive"}},
            behavioral_data={"alice": {"total_time_ms": 5000}},
        )

        # Pass integer instance_id
        result = mgr.get_annotator_signals("alice", 42)

        assert result["instance_id"] == "42"
        assert result["metrics"]["total_time_ms"] == 5000


class TestGetSimilarItems:
    """Tests for get_similar_items returning enriched metadata."""

    def test_returns_enriched_metadata(self):
        mgr = _make_manager()

        mock_engine = MagicMock()
        mock_engine.enabled = True
        mock_engine.find_similar.return_value = [
            ("item_2", 0.92),
            ("item_3", 0.85),
        ]
        mock_engine.text_cache = {
            "item_2": "This is item 2 text",
            "item_3": "This is item 3 text",
        }
        mgr.similarity_engine = mock_engine

        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={
                "user_1": {"sentiment": "positive"},
                "user_2": {"sentiment": "positive"},
            },
            overall_agreement=0.8,
            status="pending",
        )

        results = mgr.get_similar_items("item_1")

        assert len(results) == 2

        # First result: item_2 is in queue
        assert results[0]["instance_id"] == "item_2"
        assert results[0]["similarity"] == 0.92
        assert results[0]["text_preview"] == "This is item 2 text"
        assert results[0]["in_queue"] is True
        assert results[0]["status"] == "pending"
        assert results[0]["overall_agreement"] == 0.8
        assert results[0]["consensus_label"] == "positive"
        assert results[0]["decision"] is None

        # Second result: item_3 is NOT in queue
        assert results[1]["instance_id"] == "item_3"
        assert results[1]["similarity"] == 0.85
        assert results[1]["in_queue"] is False
        assert results[1]["status"] is None
        assert results[1]["overall_agreement"] is None
        assert results[1]["consensus_label"] is None

    def test_returns_empty_when_disabled(self):
        mgr = _make_manager()
        mgr.similarity_engine = None

        results = mgr.get_similar_items("item_1")
        assert results == []

    def test_returns_empty_when_engine_not_enabled(self):
        mgr = _make_manager()
        mock_engine = MagicMock()
        mock_engine.enabled = False
        mgr.similarity_engine = mock_engine

        results = mgr.get_similar_items("item_1")
        assert results == []

    def test_completed_decision_metadata(self):
        """Items with completed decisions show decision='completed'."""
        mgr = _make_manager()

        mock_engine = MagicMock()
        mock_engine.enabled = True
        mock_engine.find_similar.return_value = [("item_2", 0.90)]
        mock_engine.text_cache = {"item_2": "Decided item"}
        mgr.similarity_engine = mock_engine

        mgr.queue["item_2"] = _make_item(
            "item_2",
            annotations={"user_1": {"sentiment": "positive"}},
            status="completed",
        )
        mgr.decisions["item_2"] = AdjudicationDecision(
            instance_id="item_2",
            adjudicator_id="expert_1",
            timestamp="2026-02-05T10:00:00",
            label_decisions={"sentiment": "positive"},
            span_decisions=[],
            source={"sentiment": "adjudicator"},
            confidence="high",
            notes="",
            error_taxonomy=[],
        )

        results = mgr.get_similar_items("item_1")

        assert len(results) == 1
        assert results[0]["decision"] == "completed"
        # consensus_label is None when a decision exists
        assert results[0]["consensus_label"] is None

    def test_without_metadata(self):
        """When include_metadata=False, only basic fields returned."""
        mgr = _make_manager()

        mock_engine = MagicMock()
        mock_engine.enabled = True
        mock_engine.find_similar.return_value = [("item_2", 0.88)]
        mock_engine.text_cache = {"item_2": "Some text"}
        mgr.similarity_engine = mock_engine

        results = mgr.get_similar_items("item_1", include_metadata=False)

        assert len(results) == 1
        assert results[0]["instance_id"] == "item_2"
        assert results[0]["similarity"] == 0.88
        assert results[0]["text_preview"] == "Some text"
        assert "in_queue" not in results[0]
        assert "decision" not in results[0]

    def test_similarity_scores_rounded(self):
        """Similarity scores are rounded to 4 decimal places."""
        mgr = _make_manager()

        mock_engine = MagicMock()
        mock_engine.enabled = True
        mock_engine.find_similar.return_value = [("item_2", 0.876543219)]
        mock_engine.text_cache = {"item_2": ""}
        mgr.similarity_engine = mock_engine

        results = mgr.get_similar_items("item_1", include_metadata=False)

        assert results[0]["similarity"] == 0.8765

    def test_empty_text_cache(self):
        """Missing text_cache entries default to empty string."""
        mgr = _make_manager()

        mock_engine = MagicMock()
        mock_engine.enabled = True
        mock_engine.find_similar.return_value = [("item_2", 0.90)]
        mock_engine.text_cache = {}
        mgr.similarity_engine = mock_engine

        results = mgr.get_similar_items("item_1", include_metadata=False)

        assert results[0]["text_preview"] == ""
