"""
Unit tests for step_quality_control module.

Tests step-level gold standards, attention checks, and quality control
manager functionality for agent trace annotation tasks.
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from potato.step_quality_control import (
    StepGoldStandard,
    StepAttentionCheck,
    StepQualityControlManager,
)


# ---------------------------------------------------------------------------
# StepGoldStandard
# ---------------------------------------------------------------------------

class TestStepGoldStandard:
    """Tests for StepGoldStandard.check()."""

    def _make_gs(self, expected_label="correct", tolerance=0.0):
        return StepGoldStandard(
            instance_id="inst1",
            step_index=0,
            scheme_name="quality",
            expected_label=expected_label,
            tolerance=tolerance,
        )

    # Exact matching (tolerance=0)

    def test_exact_match_returns_true(self):
        gs = self._make_gs(expected_label="correct")
        assert gs.check("correct") is True

    def test_exact_mismatch_returns_false(self):
        gs = self._make_gs(expected_label="correct")
        assert gs.check("incorrect") is False

    def test_case_sensitive_no_tolerance(self):
        """Exact matching is case-sensitive when tolerance=0."""
        gs = self._make_gs(expected_label="Correct")
        assert gs.check("correct") is False

    def test_empty_expected_and_empty_given(self):
        gs = self._make_gs(expected_label="")
        assert gs.check("") is True

    def test_empty_expected_nonempty_given(self):
        gs = self._make_gs(expected_label="")
        assert gs.check("something") is False

    # Numeric tolerance matching

    def test_within_tolerance_returns_true(self):
        gs = self._make_gs(expected_label="5.0", tolerance=0.5)
        assert gs.check("5.3") is True

    def test_at_tolerance_boundary_returns_true(self):
        gs = self._make_gs(expected_label="5.0", tolerance=0.5)
        assert gs.check("5.5") is True

    def test_outside_tolerance_returns_false(self):
        gs = self._make_gs(expected_label="5.0", tolerance=0.5)
        assert gs.check("6.0") is False

    def test_negative_tolerance_boundary(self):
        gs = self._make_gs(expected_label="5.0", tolerance=0.5)
        assert gs.check("4.5") is True

    def test_non_numeric_with_tolerance_falls_back_to_exact(self):
        """Non-numeric labels with tolerance>0 fall back to exact comparison."""
        gs = self._make_gs(expected_label="good", tolerance=1.0)
        assert gs.check("good") is True
        assert gs.check("bad") is False

    def test_to_dict_contains_all_fields(self):
        gs = self._make_gs(expected_label="yes", tolerance=0.1)
        d = gs.to_dict()
        assert d["instance_id"] == "inst1"
        assert d["step_index"] == 0
        assert d["scheme_name"] == "quality"
        assert d["expected_label"] == "yes"
        assert d["tolerance"] == 0.1


# ---------------------------------------------------------------------------
# StepAttentionCheck
# ---------------------------------------------------------------------------

class TestStepAttentionCheck:
    """Tests for StepAttentionCheck.matches_step() and check()."""

    def _make_check(self, expected_answer="correct", action_type=None):
        return StepAttentionCheck(
            question="Is this step correct?",
            expected_answer=expected_answer,
            action_type=action_type,
        )

    # matches_step

    def test_matches_step_no_action_type_always_true(self):
        """Without action_type filter, check applies to any step."""
        check = self._make_check(action_type=None)
        assert check.matches_step({"action_type": "click"}) is True
        assert check.matches_step({"action_type": "type"}) is True
        assert check.matches_step({}) is True

    def test_matches_step_with_action_type_match(self):
        check = self._make_check(action_type="click")
        assert check.matches_step({"action_type": "click"}) is True

    def test_matches_step_with_action_type_mismatch(self):
        check = self._make_check(action_type="click")
        assert check.matches_step({"action_type": "type"}) is False

    def test_matches_step_missing_action_type_key(self):
        """Step without action_type key does not match a filtered check."""
        check = self._make_check(action_type="scroll")
        assert check.matches_step({}) is False

    # check (answer validation)

    def test_correct_answer_returns_true(self):
        check = self._make_check(expected_answer="yes")
        assert check.check("yes") is True

    def test_incorrect_answer_returns_false(self):
        check = self._make_check(expected_answer="yes")
        assert check.check("no") is False

    def test_check_is_case_insensitive(self):
        check = self._make_check(expected_answer="Yes")
        assert check.check("yes") is True
        assert check.check("YES") is True

    def test_check_strips_whitespace(self):
        check = self._make_check(expected_answer="correct")
        assert check.check("  correct  ") is True

    def test_empty_expected_empty_given(self):
        check = self._make_check(expected_answer="")
        assert check.check("") is True

    def test_empty_expected_nonempty_given(self):
        check = self._make_check(expected_answer="")
        assert check.check("something") is False


# ---------------------------------------------------------------------------
# StepQualityControlManager – initialization
# ---------------------------------------------------------------------------

class TestStepQualityControlManagerInit:
    """Tests for StepQualityControlManager initialization."""

    def test_disabled_by_default(self):
        """Manager with empty config is disabled."""
        mgr = StepQualityControlManager({})
        assert mgr.enabled is False

    def test_enabled_flag(self):
        mgr = StepQualityControlManager({"enabled": True})
        assert mgr.enabled is True

    def test_attention_enabled_flag(self):
        config = {
            "enabled": True,
            "attention_checks": {"enabled": True, "frequency": 3},
        }
        mgr = StepQualityControlManager(config)
        assert mgr.attention_enabled is True
        assert mgr.attention_frequency == 3

    def test_attention_disabled_by_default(self):
        mgr = StepQualityControlManager({"enabled": True})
        assert mgr.attention_enabled is False

    def test_attention_frequency_default(self):
        config = {"enabled": True, "attention_checks": {"enabled": True}}
        mgr = StepQualityControlManager(config)
        assert mgr.attention_frequency == 5  # Default

    def test_gold_standards_empty_without_file(self):
        """No gold file configured means empty gold_standards list."""
        mgr = StepQualityControlManager({"enabled": True})
        assert mgr.gold_standards == []

    def test_gold_standards_missing_file_logs_warning(self):
        """Non-existent gold file logs a warning, does not raise."""
        config = {"enabled": True, "gold_standards_file": "nonexistent.json"}
        with patch("potato.step_quality_control.logger") as mock_logger:
            mgr = StepQualityControlManager(config, base_dir="/nonexistent")
        assert mgr.gold_standards == []
        mock_logger.warning.assert_called()

    def test_loads_gold_standards_from_file(self, tmp_path):
        """Gold standards are loaded correctly from a JSON file."""
        data = [
            {
                "instance_id": "inst1",
                "step_index": 0,
                "scheme_name": "quality",
                "expected_label": "correct",
                "tolerance": 0.0,
            }
        ]
        gold_file = tmp_path / "gold_steps.json"
        gold_file.write_text(json.dumps(data))

        config = {
            "enabled": True,
            "gold_standards_file": "gold_steps.json",
        }
        mgr = StepQualityControlManager(config, base_dir=str(tmp_path))
        assert len(mgr.gold_standards) == 1
        assert mgr.gold_standards[0].instance_id == "inst1"
        assert mgr.gold_standards[0].step_index == 0
        assert mgr.gold_standards[0].expected_label == "correct"

    def test_loads_attention_checks_from_config(self):
        """Attention check items defined in config are loaded."""
        config = {
            "enabled": True,
            "attention_checks": {
                "enabled": True,
                "items": [
                    {
                        "question": "Is this correct?",
                        "expected_answer": "yes",
                        "action_type": "click",
                    }
                ],
            },
        }
        mgr = StepQualityControlManager(config)
        assert len(mgr.attention_checks) == 1
        assert mgr.attention_checks[0].question == "Is this correct?"
        assert mgr.attention_checks[0].action_type == "click"

    def test_default_attention_check_created_when_no_items(self):
        """When no items configured, a default attention check is created."""
        config = {"enabled": True, "attention_checks": {"enabled": True}}
        mgr = StepQualityControlManager(config)
        assert len(mgr.attention_checks) >= 1


# ---------------------------------------------------------------------------
# check_step_annotation
# ---------------------------------------------------------------------------

class TestCheckStepAnnotation:
    """Tests for StepQualityControlManager.check_step_annotation()."""

    def _make_manager_with_gold(self, tmp_path, tolerance=0.0):
        """Create a manager with a single gold standard loaded from file."""
        data = [
            {
                "instance_id": "inst1",
                "step_index": 2,
                "scheme_name": "correctness",
                "expected_label": "correct",
                "tolerance": tolerance,
            }
        ]
        gold_file = tmp_path / "gold.json"
        gold_file.write_text(json.dumps(data))
        config = {
            "enabled": True,
            "gold_standards_file": "gold.json",
        }
        return StepQualityControlManager(config, base_dir=str(tmp_path))

    def test_gold_match_returns_correct_true(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        result = mgr.check_step_annotation(
            instance_id="inst1",
            step_index=2,
            scheme_name="correctness",
            annotator_id="ann1",
            label="correct",
        )
        assert result is not None
        assert result["is_gold"] is True
        assert result["correct"] is True
        assert result["expected"] == "correct"
        assert result["given"] == "correct"

    def test_gold_mismatch_returns_correct_false(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        result = mgr.check_step_annotation(
            instance_id="inst1",
            step_index=2,
            scheme_name="correctness",
            annotator_id="ann1",
            label="incorrect",
        )
        assert result is not None
        assert result["is_gold"] is True
        assert result["correct"] is False

    def test_no_gold_standard_returns_none(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        result = mgr.check_step_annotation(
            instance_id="inst1",
            step_index=99,  # No gold for this step
            scheme_name="correctness",
            annotator_id="ann1",
            label="correct",
        )
        assert result is None

    def test_unknown_instance_returns_none(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        result = mgr.check_step_annotation(
            instance_id="unknown_inst",
            step_index=2,
            scheme_name="correctness",
            annotator_id="ann1",
            label="correct",
        )
        assert result is None

    def test_scheme_name_mismatch_returns_none(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        result = mgr.check_step_annotation(
            instance_id="inst1",
            step_index=2,
            scheme_name="wrong_scheme",
            annotator_id="ann1",
            label="correct",
        )
        assert result is None

    def test_result_includes_step_index_and_scheme(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        result = mgr.check_step_annotation(
            instance_id="inst1",
            step_index=2,
            scheme_name="correctness",
            annotator_id="ann1",
            label="correct",
        )
        assert result["step_index"] == 2
        assert result["scheme_name"] == "correctness"

    def test_disabled_manager_gold_not_loaded(self):
        """Disabled manager has no gold standards, so check returns None."""
        mgr = StepQualityControlManager({"enabled": False})
        result = mgr.check_step_annotation(
            instance_id="inst1",
            step_index=0,
            scheme_name="quality",
            annotator_id="ann1",
            label="correct",
        )
        assert result is None


# ---------------------------------------------------------------------------
# should_inject_attention_check
# ---------------------------------------------------------------------------

class TestShouldInjectAttentionCheck:
    """Tests for StepQualityControlManager.should_inject_attention_check()."""

    def _make_manager(self, enabled=True, frequency=5):
        config = {
            "enabled": True,
            "attention_checks": {
                "enabled": enabled,
                "frequency": frequency,
            },
        }
        return StepQualityControlManager(config)

    def test_disabled_returns_false(self):
        mgr = self._make_manager(enabled=False)
        assert mgr.should_inject_attention_check("ann1", steps_annotated=5) is False

    def test_at_frequency_returns_true(self):
        mgr = self._make_manager(frequency=5)
        assert mgr.should_inject_attention_check("ann1", steps_annotated=5) is True

    def test_double_frequency_returns_true(self):
        mgr = self._make_manager(frequency=5)
        assert mgr.should_inject_attention_check("ann1", steps_annotated=10) is True

    def test_not_at_frequency_returns_false(self):
        mgr = self._make_manager(frequency=5)
        assert mgr.should_inject_attention_check("ann1", steps_annotated=3) is False
        assert mgr.should_inject_attention_check("ann1", steps_annotated=6) is False

    def test_zero_steps_returns_false(self):
        """Zero steps should never inject (guard against division by zero)."""
        mgr = self._make_manager(frequency=5)
        assert mgr.should_inject_attention_check("ann1", steps_annotated=0) is False

    def test_frequency_zero_returns_false(self):
        """Frequency of 0 should never inject (avoid modulo-by-zero)."""
        mgr = self._make_manager(frequency=0)
        assert mgr.should_inject_attention_check("ann1", steps_annotated=5) is False

    def test_frequency_one_every_step(self):
        """Frequency of 1 injects on every step."""
        mgr = self._make_manager(frequency=1)
        assert mgr.should_inject_attention_check("ann1", steps_annotated=1) is True
        assert mgr.should_inject_attention_check("ann1", steps_annotated=2) is True

    def test_annotator_id_ignored_for_logic(self):
        """Different annotator IDs should not affect the frequency calculation."""
        mgr = self._make_manager(frequency=5)
        assert mgr.should_inject_attention_check("ann1", steps_annotated=5) is True
        assert mgr.should_inject_attention_check("ann2", steps_annotated=5) is True


# ---------------------------------------------------------------------------
# get_annotator_performance
# ---------------------------------------------------------------------------

class TestGetAnnotatorPerformance:
    """Tests for StepQualityControlManager.get_annotator_performance()."""

    def _make_manager_with_gold(self, tmp_path):
        data = [
            {
                "instance_id": "inst1",
                "step_index": 0,
                "scheme_name": "quality",
                "expected_label": "correct",
                "tolerance": 0.0,
            },
            {
                "instance_id": "inst1",
                "step_index": 1,
                "scheme_name": "quality",
                "expected_label": "correct",
                "tolerance": 0.0,
            },
        ]
        gold_file = tmp_path / "gold.json"
        gold_file.write_text(json.dumps(data))
        config = {"enabled": True, "gold_standards_file": "gold.json"}
        return StepQualityControlManager(config, base_dir=str(tmp_path))

    def test_unknown_annotator_returns_zero_stats(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        perf = mgr.get_annotator_performance("unknown_ann")
        assert perf["total"] == 0
        assert perf["correct"] == 0
        assert perf["accuracy"] == 0.0

    def test_all_correct_accuracy_is_1(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        mgr.check_step_annotation("inst1", 0, "quality", "ann1", "correct")
        mgr.check_step_annotation("inst1", 1, "quality", "ann1", "correct")
        perf = mgr.get_annotator_performance("ann1")
        assert perf["total"] == 2
        assert perf["correct"] == 2
        assert perf["accuracy"] == 1.0

    def test_all_incorrect_accuracy_is_0(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        mgr.check_step_annotation("inst1", 0, "quality", "ann1", "wrong")
        mgr.check_step_annotation("inst1", 1, "quality", "ann1", "wrong")
        perf = mgr.get_annotator_performance("ann1")
        assert perf["total"] == 2
        assert perf["correct"] == 0
        assert perf["accuracy"] == 0.0

    def test_mixed_accuracy(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        mgr.check_step_annotation("inst1", 0, "quality", "ann1", "correct")
        mgr.check_step_annotation("inst1", 1, "quality", "ann1", "wrong")
        perf = mgr.get_annotator_performance("ann1")
        assert perf["total"] == 2
        assert perf["correct"] == 1
        assert abs(perf["accuracy"] - 0.5) < 1e-9

    def test_multiple_annotators_tracked_separately(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        mgr.check_step_annotation("inst1", 0, "quality", "ann1", "correct")
        mgr.check_step_annotation("inst1", 0, "quality", "ann2", "wrong")

        perf_all = mgr.get_annotator_performance()
        assert "ann1" in perf_all
        assert "ann2" in perf_all
        assert perf_all["ann1"]["accuracy"] == 1.0
        assert perf_all["ann2"]["accuracy"] == 0.0

    def test_get_all_returns_dict(self, tmp_path):
        mgr = self._make_manager_with_gold(tmp_path)
        mgr.check_step_annotation("inst1", 0, "quality", "ann1", "correct")
        all_perf = mgr.get_annotator_performance()
        assert isinstance(all_perf, dict)
        assert "ann1" in all_perf

    def test_empty_performance_when_no_checks(self):
        mgr = StepQualityControlManager({"enabled": True})
        all_perf = mgr.get_annotator_performance()
        assert all_perf == {}


# ---------------------------------------------------------------------------
# get_quality_summary
# ---------------------------------------------------------------------------

class TestGetQualitySummary:
    """Tests for StepQualityControlManager.get_quality_summary()."""

    def test_summary_when_disabled(self):
        mgr = StepQualityControlManager({"enabled": False})
        summary = mgr.get_quality_summary()
        assert summary["enabled"] is False
        assert summary["overall_accuracy"] is None

    def test_summary_gold_standards_count(self, tmp_path):
        data = [
            {
                "instance_id": "inst1",
                "step_index": 0,
                "scheme_name": "q",
                "expected_label": "yes",
            }
        ]
        gold_file = tmp_path / "gold.json"
        gold_file.write_text(json.dumps(data))
        config = {"enabled": True, "gold_standards_file": "gold.json"}
        mgr = StepQualityControlManager(config, base_dir=str(tmp_path))
        summary = mgr.get_quality_summary()
        assert summary["gold_standards_count"] == 1

    def test_summary_accuracy_after_checks(self, tmp_path):
        data = [
            {
                "instance_id": "inst1",
                "step_index": 0,
                "scheme_name": "q",
                "expected_label": "yes",
            }
        ]
        gold_file = tmp_path / "gold.json"
        gold_file.write_text(json.dumps(data))
        config = {"enabled": True, "gold_standards_file": "gold.json"}
        mgr = StepQualityControlManager(config, base_dir=str(tmp_path))

        mgr.check_step_annotation("inst1", 0, "q", "ann1", "yes")   # correct
        mgr.check_step_annotation("inst1", 0, "q", "ann2", "no")    # incorrect

        summary = mgr.get_quality_summary()
        assert summary["total_checks_performed"] == 2
        assert summary["total_correct"] == 1
        assert abs(summary["overall_accuracy"] - 0.5) < 1e-9
