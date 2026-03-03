"""
Tests for PromptOptimizer.

Tests OptimizationResult, OptimizationConfig, PromptOptimizer
(optimize, background thread, history tracking, example splitting).
"""

import pytest
import time
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

from potato.solo_mode.prompt_optimizer import (
    OptimizationResult,
    OptimizationConfig,
    PromptOptimizer,
)


class TestOptimizationResult:
    """Tests for OptimizationResult dataclass."""

    def test_creation(self):
        r = OptimizationResult(
            original_prompt="old prompt",
            optimized_prompt="new prompt",
            changes_made=["Added examples", "Clarified boundary"],
            rationale="Addresses common errors",
            accuracy_before=0.7,
        )
        assert r.original_prompt == "old prompt"
        assert r.accuracy_after is None
        assert len(r.changes_made) == 2

    def test_to_dict(self):
        r = OptimizationResult(
            original_prompt="old",
            optimized_prompt="new",
            changes_made=["c1"],
            rationale="r",
            accuracy_before=0.6,
            accuracy_after=0.8,
            model_used="test-model",
            num_examples_used=15,
        )
        data = r.to_dict()
        assert data['accuracy_before'] == 0.6
        assert data['accuracy_after'] == 0.8
        assert data['model_used'] == "test-model"
        assert 'timestamp' in data


class TestOptimizationConfig:
    """Tests for OptimizationConfig defaults."""

    def test_defaults(self):
        c = OptimizationConfig()
        assert c.enabled is True
        assert c.find_smallest_model is True
        assert c.target_accuracy == 0.85
        assert c.min_examples_for_optimization == 10
        assert c.optimization_interval_seconds == 300
        assert c.max_prompt_length == 2000


class TestPromptOptimizerInit:
    """Tests for PromptOptimizer initialization."""

    def _make_optimizer(self, **kwargs):
        defaults = {
            'config': {},
            'solo_config': MagicMock(revision_models=[], prompt_optimization=None),
            'prompt_getter': lambda: "current prompt",
            'prompt_setter': lambda text, source='', source_description='': None,
            'examples_getter': lambda: [],
        }
        defaults.update(kwargs)
        return PromptOptimizer(**defaults)

    def test_creation(self):
        opt = self._make_optimizer()
        assert opt.opt_config.enabled is True
        assert len(opt.optimization_history) == 0
        assert opt.is_running() is False

    def test_custom_config(self):
        solo_config = MagicMock()
        solo_config.revision_models = []
        solo_config.prompt_optimization = {
            'enabled': False,
            'target_accuracy': 0.95,
        }
        opt = PromptOptimizer(
            config={},
            solo_config=solo_config,
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        assert opt.opt_config.enabled is False
        assert opt.opt_config.target_accuracy == 0.95


class TestPromptOptimizerExampleSplitting:
    """Tests for example splitting."""

    @pytest.fixture
    def optimizer(self):
        return PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )

    def test_split_all_correct(self, optimizer):
        examples = [{'text': 'a', 'agrees': True}, {'text': 'b', 'agrees': True}]
        correct, incorrect = optimizer._split_examples(examples)
        assert len(correct) == 2
        assert len(incorrect) == 0

    def test_split_all_incorrect(self, optimizer):
        examples = [{'text': 'a', 'agrees': False}, {'text': 'b', 'agrees': False}]
        correct, incorrect = optimizer._split_examples(examples)
        assert len(correct) == 0
        assert len(incorrect) == 2

    def test_split_mixed(self, optimizer):
        examples = [
            {'text': 'a', 'agrees': True},
            {'text': 'b', 'agrees': False},
            {'text': 'c', 'agrees': True},
        ]
        correct, incorrect = optimizer._split_examples(examples)
        assert len(correct) == 2
        assert len(incorrect) == 1

    def test_split_missing_agrees_key(self, optimizer):
        """Missing 'agrees' defaults to True."""
        examples = [{'text': 'a'}]
        correct, incorrect = optimizer._split_examples(examples)
        assert len(correct) == 1
        assert len(incorrect) == 0


class TestPromptOptimizerFormatExamples:
    """Tests for example formatting."""

    @pytest.fixture
    def optimizer(self):
        return PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )

    def test_format_correct(self, optimizer):
        examples = [{'text': 'hello', 'predicted_label': 'positive'}]
        result = optimizer._format_examples(examples, show_correction=False)
        assert "hello" in result
        assert "Label: positive" in result

    def test_format_incorrect(self, optimizer):
        examples = [{
            'text': 'hello', 'predicted_label': 'positive',
            'actual_label': 'negative',
        }]
        result = optimizer._format_examples(examples, show_correction=True)
        assert "LLM predicted: positive" in result
        assert "Correct label: negative" in result

    def test_format_empty(self, optimizer):
        assert optimizer._format_examples([]) == ""

    def test_format_truncates_text(self, optimizer):
        examples = [{'text': 'x' * 500, 'predicted_label': 'a'}]
        result = optimizer._format_examples(examples, show_correction=False)
        assert len(result) < 500


class TestPromptOptimizerJsonParsing:
    """Tests for JSON response parsing."""

    @pytest.fixture
    def optimizer(self):
        return PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )

    def test_parse_valid(self, optimizer):
        result = optimizer._parse_json_response('{"improved_prompt": "better"}')
        assert result['improved_prompt'] == "better"

    def test_parse_markdown(self, optimizer):
        result = optimizer._parse_json_response(
            '```json\n{"improved_prompt": "better"}\n```'
        )
        assert result['improved_prompt'] == "better"

    def test_parse_invalid(self, optimizer):
        result = optimizer._parse_json_response("not json")
        assert result == {}


class TestPromptOptimizerOptimize:
    """Tests for the optimize method."""

    def test_no_examples(self):
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "prompt",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        result = opt.optimize()
        assert result is None

    def test_insufficient_examples(self):
        examples = [{'text': f't{i}', 'agrees': False} for i in range(3)]
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "prompt",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: examples,
        )
        result = opt.optimize()
        assert result is None  # Less than min_examples_for_optimization

    def test_no_incorrect_examples(self):
        examples = [{'text': f't{i}', 'agrees': True} for i in range(20)]
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "prompt",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: examples,
        )
        result = opt.optimize()
        assert result is None

    def test_above_target_accuracy(self):
        """If accuracy already above target, skip optimization."""
        examples = [{'text': f't{i}', 'agrees': True} for i in range(18)]
        examples += [{'text': 'bad', 'agrees': False} for _ in range(2)]
        # accuracy = 18/20 = 0.9 > 0.85 target
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "prompt",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: examples,
        )
        result = opt.optimize()
        assert result is None

    def test_no_endpoint(self):
        """Without endpoint, optimization returns None."""
        examples = [{'text': 'bad', 'agrees': False} for _ in range(15)]
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "prompt",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: examples,
        )
        result = opt.optimize()
        assert result is None

    def test_no_prompt(self):
        examples = [{'text': 'bad', 'agrees': False} for _ in range(15)]
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: None,
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: examples,
        )
        result = opt.optimize()
        assert result is None

    def test_force_with_insufficient_examples(self):
        """Force flag bypasses minimum example check but still needs endpoint."""
        examples = [{'text': 'bad', 'agrees': False}]
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "prompt",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: examples,
        )
        result = opt.optimize(force=True)
        # Still None because no endpoint, but shouldn't fail on example count
        assert result is None


class TestPromptOptimizerHistory:
    """Tests for optimization history."""

    @pytest.fixture
    def optimizer(self):
        return PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )

    def test_empty_history(self, optimizer):
        assert optimizer.get_optimization_history() == []
        assert optimizer.get_last_optimization() is None

    def test_history_tracking(self, optimizer):
        result = OptimizationResult(
            original_prompt="old", optimized_prompt="new",
            changes_made=["c1"], rationale="r", accuracy_before=0.5,
        )
        optimizer.optimization_history.append(result)

        assert len(optimizer.get_optimization_history()) == 1
        assert optimizer.get_last_optimization().optimized_prompt == "new"

    def test_clear_history(self, optimizer):
        result = OptimizationResult(
            original_prompt="old", optimized_prompt="new",
            changes_made=[], rationale="", accuracy_before=0.5,
        )
        optimizer.optimization_history.append(result)
        optimizer.clear_history()
        assert len(optimizer.optimization_history) == 0


class TestPromptOptimizerStatus:
    """Tests for status reporting."""

    def test_status_disabled(self):
        solo_config = MagicMock()
        solo_config.revision_models = []
        solo_config.prompt_optimization = {'enabled': False}
        opt = PromptOptimizer(
            config={},
            solo_config=solo_config,
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        status = opt.get_status()
        assert status['enabled'] is False
        assert status['is_running'] is False
        assert status['optimization_count'] == 0
        assert status['last_optimization'] is None

    def test_status_with_history(self):
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        result = OptimizationResult(
            original_prompt="old", optimized_prompt="new",
            changes_made=[], rationale="", accuracy_before=0.5,
        )
        opt.optimization_history.append(result)

        status = opt.get_status()
        assert status['optimization_count'] == 1
        assert status['last_optimization'] is not None


class TestPromptOptimizerBackgroundThread:
    """Tests for background thread management."""

    def test_start_stop(self):
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        assert opt.start_background_optimization() is True
        assert opt.is_running() is True

        opt.stop_background_optimization()
        assert opt.is_running() is False

    def test_double_start(self):
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        assert opt.start_background_optimization() is True
        assert opt.start_background_optimization() is False  # Already running

        opt.stop_background_optimization()

    def test_start_when_disabled(self):
        solo_config = MagicMock()
        solo_config.revision_models = []
        solo_config.prompt_optimization = {'enabled': False}
        opt = PromptOptimizer(
            config={},
            solo_config=solo_config,
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        assert opt.start_background_optimization() is False

    def test_stop_when_not_running(self):
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        # Should not raise
        opt.stop_background_optimization()


class TestPromptOptimizerModelSelection:
    """Tests for find_smallest_accurate_model."""

    def test_disabled(self):
        solo_config = MagicMock()
        solo_config.revision_models = []
        solo_config.prompt_optimization = {'find_smallest_model': False}
        opt = PromptOptimizer(
            config={},
            solo_config=solo_config,
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        result = opt.find_smallest_accurate_model([], [], "prompt")
        assert result is None

    def test_placeholder_returns_none(self):
        """_test_model_accuracy returns 0.0 (placeholder), so no model qualifies."""
        opt = PromptOptimizer(
            config={},
            solo_config=MagicMock(revision_models=[], prompt_optimization=None),
            prompt_getter=lambda: "",
            prompt_setter=lambda *a, **kw: None,
            examples_getter=lambda: [],
        )
        model = MagicMock()
        model.model = "test-model"
        result = opt.find_smallest_accurate_model([model], [], "prompt")
        assert result is None
