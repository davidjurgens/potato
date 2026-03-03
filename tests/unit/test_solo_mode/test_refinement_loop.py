"""
Tests for RefinementLoop.

Tests cycle execution, plateau detection, patience, config parsing,
state persistence, and integration with the manager.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.solo_mode.refinement_loop import RefinementLoop, RefinementCycle
from potato.solo_mode.config import (
    RefinementLoopConfig,
    SoloModeConfig,
    parse_solo_mode_config,
)


def _make_solo_config(**overrides):
    """Create a SoloModeConfig with sensible test defaults."""
    config_data = {
        'solo_mode': {
            'enabled': True,
            'labeling_models': [],
            **overrides,
        },
        'annotation_schemes': [
            {'name': 'sentiment', 'annotation_type': 'radio',
             'labels': ['positive', 'negative', 'neutral']},
        ],
    }
    return parse_solo_mode_config(config_data)


def _make_loop(solo_config=None, app_config=None):
    """Create a RefinementLoop for testing."""
    if solo_config is None:
        solo_config = _make_solo_config()
    if app_config is None:
        app_config = {
            'annotation_schemes': [
                {'name': 'sentiment', 'annotation_type': 'radio',
                 'labels': ['positive', 'negative', 'neutral']},
            ],
        }
    return RefinementLoop(solo_config, app_config)


def _noop_apply(suggestions):
    """Dummy apply function."""
    return {
        'success': True,
        'new_prompt_version': 2,
        'categories_incorporated': len(suggestions),
        'reannotation_count': 0,
    }


def _noop_suggest(pattern, prompt):
    """Dummy suggestion generator."""
    return f"Fix {pattern.predicted_label} vs {pattern.actual_label}"


# === RefinementCycle Tests ===


class TestRefinementCycle:
    """Tests for RefinementCycle dataclass."""

    def test_to_dict(self):
        cycle = RefinementCycle(
            cycle_number=1,
            started_at='2025-01-01T00:00:00',
            completed_at='2025-01-01T00:01:00',
            agreement_rate_before=0.7,
            agreement_rate_after=0.75,
            improvement=0.05,
            patterns_found=3,
            suggestions_generated=2,
            rules_applied=2,
            reannotation_count=10,
            prompt_version_before=1,
            prompt_version_after=2,
            status='completed',
        )
        d = cycle.to_dict()
        assert d['cycle_number'] == 1
        assert d['improvement'] == 0.05
        assert d['patterns_found'] == 3
        assert d['status'] == 'completed'

    def test_default_status(self):
        cycle = RefinementCycle(cycle_number=1, started_at='now')
        assert cycle.status == 'running'
        assert cycle.improvement is None


# === Record Annotation Tests ===


class TestRefinementLoopRecordAnnotation:
    """Tests for annotation tracking and trigger detection."""

    def test_returns_false_when_disabled(self):
        config = _make_solo_config(refinement_loop={'enabled': False})
        loop = _make_loop(solo_config=config)
        assert loop.record_annotation() is False

    def test_returns_false_before_interval(self):
        config = _make_solo_config(refinement_loop={'trigger_interval': 5})
        loop = _make_loop(solo_config=config)

        for _ in range(4):
            assert loop.record_annotation() is False

    def test_returns_true_at_interval(self):
        config = _make_solo_config(refinement_loop={'trigger_interval': 5})
        loop = _make_loop(solo_config=config)

        for _ in range(4):
            loop.record_annotation()
        assert loop.record_annotation() is True

    def test_returns_false_when_stopped(self):
        loop = _make_loop()
        loop._stopped = True
        assert loop.record_annotation() is False


# === Should Trigger Tests ===


class TestRefinementLoopShouldTrigger:
    """Tests for should_trigger() checks."""

    def test_false_when_disabled(self):
        config = _make_solo_config(refinement_loop={'enabled': False})
        loop = _make_loop(solo_config=config)
        assert loop.should_trigger() is False

    def test_false_when_stopped(self):
        loop = _make_loop()
        loop._stopped = True
        assert loop.should_trigger() is False

    def test_false_when_running(self):
        loop = _make_loop()
        loop._running = True
        loop._annotations_since_last_check = 100
        assert loop.should_trigger() is False

    def test_false_below_interval(self):
        config = _make_solo_config(refinement_loop={'trigger_interval': 10})
        loop = _make_loop(solo_config=config)
        loop._annotations_since_last_check = 5
        assert loop.should_trigger() is False

    def test_true_at_interval(self):
        config = _make_solo_config(refinement_loop={'trigger_interval': 10})
        loop = _make_loop(solo_config=config)
        loop._annotations_since_last_check = 10
        assert loop.should_trigger() is True


# === Run Cycle Tests ===


class TestRefinementLoopRunCycle:
    """Tests for run_cycle() execution."""

    def _make_pattern(self, predicted='positive', actual='negative', count=5):
        """Create a mock ConfusionPattern."""
        from potato.solo_mode.confusion_analyzer import ConfusionPattern
        return ConfusionPattern(
            predicted_label=predicted,
            actual_label=actual,
            count=count,
            percent=25.0,
        )

    def test_basic_cycle_with_auto_apply(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
            'max_cycles': 10,
        })
        loop = _make_loop(solo_config=config)

        patterns = [self._make_pattern()]
        cycle = loop.run_cycle(
            agreement_rate=0.7,
            prompt_version=1,
            confusion_patterns=patterns,
            apply_suggestions_fn=_noop_apply,
            generate_suggestion_fn=_noop_suggest,
            current_prompt='Test prompt',
        )

        assert cycle.cycle_number == 1
        assert cycle.status == 'completed'
        assert cycle.suggestions_generated == 1
        assert cycle.rules_applied == 1
        assert cycle.agreement_rate_before == 0.7

    def test_cycle_without_auto_apply(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': False,
        })
        loop = _make_loop(solo_config=config)

        patterns = [self._make_pattern()]
        cycle = loop.run_cycle(
            agreement_rate=0.7,
            prompt_version=1,
            confusion_patterns=patterns,
            apply_suggestions_fn=_noop_apply,
            generate_suggestion_fn=_noop_suggest,
            current_prompt='Test prompt',
        )

        assert cycle.status == 'awaiting_approval'
        assert cycle.suggestions_generated == 1
        assert cycle.rules_applied == 0  # Not applied

    def test_no_patterns(self):
        loop = _make_loop()
        cycle = loop.run_cycle(
            agreement_rate=0.7,
            prompt_version=1,
            confusion_patterns=[],
            apply_suggestions_fn=_noop_apply,
            generate_suggestion_fn=_noop_suggest,
            current_prompt='Test prompt',
        )
        # No patterns but no error either (cycle still records)
        assert cycle.patterns_found == 0

    def test_no_suggestions_generated(self):
        loop = _make_loop()

        patterns = [self._make_pattern()]

        def null_suggest(pattern, prompt):
            return None  # No suggestion available

        cycle = loop.run_cycle(
            agreement_rate=0.7,
            prompt_version=1,
            confusion_patterns=patterns,
            apply_suggestions_fn=_noop_apply,
            generate_suggestion_fn=null_suggest,
            current_prompt='Test prompt',
        )

        assert cycle.status == 'no_suggestions'
        assert cycle.suggestions_generated == 0

    def test_max_cycles_reached(self):
        config = _make_solo_config(refinement_loop={
            'max_cycles': 2,
            'auto_apply_suggestions': True,
        })
        loop = _make_loop(solo_config=config)
        patterns = [self._make_pattern()]

        # Run two cycles
        loop.run_cycle(0.7, 1, patterns, _noop_apply, _noop_suggest, 'p')
        loop.run_cycle(0.72, 2, patterns, _noop_apply, _noop_suggest, 'p')

        # Third should be blocked
        cycle = loop.run_cycle(0.74, 3, patterns, _noop_apply, _noop_suggest, 'p')
        assert cycle.status == 'max_cycles_reached'
        assert loop.is_stopped is True

    def test_cycle_increments_count(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
        })
        loop = _make_loop(solo_config=config)
        patterns = [self._make_pattern()]

        loop.run_cycle(0.7, 1, patterns, _noop_apply, _noop_suggest, 'p')
        assert loop.cycle_count == 1

        loop.run_cycle(0.72, 2, patterns, _noop_apply, _noop_suggest, 'p')
        assert loop.cycle_count == 2

    def test_resets_annotation_counter(self):
        config = _make_solo_config(refinement_loop={'trigger_interval': 5})
        loop = _make_loop(solo_config=config)
        patterns = [self._make_pattern()]

        loop._annotations_since_last_check = 10
        loop.run_cycle(0.7, 1, patterns, _noop_apply, _noop_suggest, 'p')
        assert loop._annotations_since_last_check == 0

    def test_exception_in_cycle_sets_failed(self):
        loop = _make_loop()
        patterns = [self._make_pattern()]

        def bad_apply(suggestions):
            raise RuntimeError("Apply failed")

        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
        })
        loop = _make_loop(solo_config=config)

        cycle = loop.run_cycle(
            agreement_rate=0.7,
            prompt_version=1,
            confusion_patterns=patterns,
            apply_suggestions_fn=bad_apply,
            generate_suggestion_fn=_noop_suggest,
            current_prompt='Test prompt',
        )

        assert cycle.status == 'failed'

    def test_concurrent_run_blocked(self):
        loop = _make_loop()
        loop._running = True

        patterns = [self._make_pattern()]
        with pytest.raises(RuntimeError, match="already running"):
            loop.run_cycle(0.7, 1, patterns, _noop_apply, _noop_suggest, 'p')


# === Post-Cycle Metrics Tests ===


class TestRefinementLoopPostCycleMetrics:
    """Tests for recording post-cycle agreement rates."""

    def _run_one_cycle(self, loop, rate=0.7):
        from potato.solo_mode.confusion_analyzer import ConfusionPattern
        pattern = ConfusionPattern('A', 'B', count=3, percent=30.0)
        loop.run_cycle(rate, 1, [pattern], _noop_apply, _noop_suggest, 'p')

    def test_records_improvement(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
            'min_improvement': 0.02,
        })
        loop = _make_loop(solo_config=config)
        self._run_one_cycle(loop, 0.7)

        loop.record_post_cycle_metrics(0.75)

        last = loop._cycles[-1]
        assert last.agreement_rate_after == 0.75
        assert abs(last.improvement - 0.05) < 1e-6
        assert loop._consecutive_no_improvement == 0

    def test_no_improvement_increments_patience(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
            'min_improvement': 0.02,
            'patience': 3,
        })
        loop = _make_loop(solo_config=config)
        self._run_one_cycle(loop, 0.7)

        loop.record_post_cycle_metrics(0.705)  # Only 0.005 improvement

        assert loop._consecutive_no_improvement == 1
        assert loop.is_stopped is False

    def test_patience_exceeded_stops_loop(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
            'min_improvement': 0.02,
            'patience': 2,
        })
        loop = _make_loop(solo_config=config)

        # Cycle 1: no improvement
        self._run_one_cycle(loop, 0.7)
        loop.record_post_cycle_metrics(0.705)
        assert loop._consecutive_no_improvement == 1

        # Cycle 2: no improvement again
        self._run_one_cycle(loop, 0.705)
        loop.record_post_cycle_metrics(0.71)
        assert loop._consecutive_no_improvement == 2
        assert loop.is_stopped is True
        assert loop.stop_reason == "Improvement plateaued"

    def test_improvement_resets_patience(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
            'min_improvement': 0.02,
            'patience': 2,
        })
        loop = _make_loop(solo_config=config)

        # Cycle 1: no improvement
        self._run_one_cycle(loop, 0.7)
        loop.record_post_cycle_metrics(0.705)
        assert loop._consecutive_no_improvement == 1

        # Cycle 2: good improvement
        self._run_one_cycle(loop, 0.705)
        loop.record_post_cycle_metrics(0.75)
        assert loop._consecutive_no_improvement == 0

    def test_no_cycles_is_noop(self):
        loop = _make_loop()
        loop.record_post_cycle_metrics(0.8)  # No cycles yet
        assert loop.cycle_count == 0

    def test_already_recorded_is_noop(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
        })
        loop = _make_loop(solo_config=config)
        self._run_one_cycle(loop, 0.7)
        loop.record_post_cycle_metrics(0.75)

        # Second call should not update
        loop.record_post_cycle_metrics(0.9)
        assert loop._cycles[-1].agreement_rate_after == 0.75


# === Reset Tests ===


class TestRefinementLoopReset:
    """Tests for reset behavior."""

    def test_reset_clears_state(self):
        loop = _make_loop()
        loop._stopped = True
        loop._stop_reason = "Testing"
        loop._consecutive_no_improvement = 5
        loop._annotations_since_last_check = 42

        loop.reset()

        assert loop.is_stopped is False
        assert loop.stop_reason is None
        assert loop._consecutive_no_improvement == 0
        assert loop._annotations_since_last_check == 0

    def test_reset_preserves_cycles(self):
        """Reset should allow new cycles but keep history."""
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
        })
        loop = _make_loop(solo_config=config)

        from potato.solo_mode.confusion_analyzer import ConfusionPattern
        pattern = ConfusionPattern('A', 'B', count=3, percent=30.0)
        loop.run_cycle(0.7, 1, [pattern], _noop_apply, _noop_suggest, 'p')
        assert loop.cycle_count == 1

        loop._stopped = True
        loop.reset()

        assert loop.is_stopped is False
        assert loop.cycle_count == 1  # History preserved


# === Status Tests ===


class TestRefinementLoopStatus:
    """Tests for get_status()."""

    def test_initial_status(self):
        loop = _make_loop()
        status = loop.get_status()

        assert status['enabled'] is True
        assert status['total_cycles'] == 0
        assert status['is_running'] is False
        assert status['is_stopped'] is False
        assert status['stop_reason'] is None
        assert status['last_cycle'] is None
        assert status['last_improvement'] is None

    def test_status_after_cycle(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
            'trigger_interval': 10,
        })
        loop = _make_loop(solo_config=config)

        from potato.solo_mode.confusion_analyzer import ConfusionPattern
        pattern = ConfusionPattern('A', 'B', count=3, percent=30.0)
        loop.run_cycle(0.7, 1, [pattern], _noop_apply, _noop_suggest, 'p')
        loop.record_post_cycle_metrics(0.75)

        status = loop.get_status()
        assert status['total_cycles'] == 1
        assert status['last_cycle'] is not None
        assert status['last_improvement'] is not None
        assert abs(status['last_improvement'] - 0.05) < 1e-6


# === Persistence Tests ===


class TestRefinementLoopPersistence:
    """Tests for state serialization/deserialization."""

    def test_to_dict_empty(self):
        loop = _make_loop()
        d = loop.to_dict()
        assert d['cycles'] == []
        assert d['annotations_since_last_check'] == 0
        assert d['stopped'] is False

    def test_roundtrip(self):
        config = _make_solo_config(refinement_loop={
            'auto_apply_suggestions': True,
        })
        loop = _make_loop(solo_config=config)

        from potato.solo_mode.confusion_analyzer import ConfusionPattern
        pattern = ConfusionPattern('A', 'B', count=3, percent=30.0)
        loop.run_cycle(0.7, 1, [pattern], _noop_apply, _noop_suggest, 'p')
        loop._annotations_since_last_check = 7
        loop._stopped = True
        loop._stop_reason = "test stop"

        data = loop.to_dict()

        loop2 = _make_loop(solo_config=config)
        loop2.load_state(data)

        assert loop2.cycle_count == 1
        assert loop2._annotations_since_last_check == 7
        assert loop2._stopped is True
        assert loop2._stop_reason == "test stop"
        assert loop2._cycles[0].cycle_number == 1


# === Config Parsing Tests ===


class TestRefinementLoopConfig:
    """Tests for RefinementLoopConfig parsing."""

    def test_defaults(self):
        config = _make_solo_config()
        rl = config.refinement_loop
        assert rl.enabled is True
        assert rl.trigger_interval == 50
        assert rl.min_improvement == 0.02
        assert rl.max_cycles == 5
        assert rl.patience == 2
        assert rl.auto_apply_suggestions is False

    def test_custom_values(self):
        config = _make_solo_config(refinement_loop={
            'enabled': False,
            'trigger_interval': 100,
            'min_improvement': 0.05,
            'max_cycles': 3,
            'patience': 1,
            'auto_apply_suggestions': True,
        })
        rl = config.refinement_loop
        assert rl.enabled is False
        assert rl.trigger_interval == 100
        assert rl.min_improvement == 0.05
        assert rl.max_cycles == 3
        assert rl.patience == 1
        assert rl.auto_apply_suggestions is True

    def test_partial_override(self):
        config = _make_solo_config(refinement_loop={
            'trigger_interval': 25,
        })
        rl = config.refinement_loop
        assert rl.enabled is True  # default
        assert rl.trigger_interval == 25
        assert rl.patience == 2  # default
