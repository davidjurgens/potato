"""
Tests for PromptManager.

Tests prompt versioning, persistence, synthesis fallback, revision formatting,
and JSON response parsing.
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from potato.solo_mode.prompt_manager import (
    PromptRevision,
    PromptManager,
)


def _make_mock_solo_config(state_dir=None):
    """Create a mock SoloModeConfig."""
    config = MagicMock()
    config.revision_models = []
    config.state_dir = state_dir
    return config


class TestPromptRevision:
    """Tests for PromptRevision dataclass."""

    def test_creation(self):
        r = PromptRevision(
            from_version=1,
            to_version=2,
            changes_made=["Added edge case guidance"],
            trigger="edge_case",
        )
        assert r.from_version == 1
        assert r.to_version == 2
        assert r.trigger == "edge_case"
        assert len(r.failed_cases) == 0

    def test_to_dict(self):
        r = PromptRevision(
            from_version=1,
            to_version=2,
            changes_made=["c1", "c2"],
            trigger="disagreement",
            failed_cases=[{"text": "abc", "expected_label": "x"}],
        )
        data = r.to_dict()
        assert data['from_version'] == 1
        assert data['to_version'] == 2
        assert len(data['changes_made']) == 2
        assert data['trigger'] == "disagreement"
        assert 'timestamp' in data


class TestPromptManagerVersioning:
    """Tests for prompt version management."""

    @pytest.fixture
    def manager(self):
        config = {'annotation_schemes': [
            {'name': 'test', 'annotation_type': 'radio', 'labels': ['a', 'b']}
        ]}
        return PromptManager(config, _make_mock_solo_config())

    def test_no_prompt_initially(self, manager):
        assert manager.get_current_prompt() is None
        assert manager.current_version == 0

    def test_add_prompt_version(self, manager):
        v = manager._add_prompt_version("First prompt", "user", "Initial")
        assert v == 1
        assert manager.current_version == 1
        assert manager.get_current_prompt() == "First prompt"

    def test_multiple_versions(self, manager):
        manager._add_prompt_version("v1", "user")
        manager._add_prompt_version("v2", "llm_synthesis")
        manager._add_prompt_version("v3", "llm_revision")

        assert manager.current_version == 3
        assert manager.get_current_prompt() == "v3"

    def test_get_prompt_version(self, manager):
        manager._add_prompt_version("first", "user")
        manager._add_prompt_version("second", "user")

        v1 = manager.get_prompt_version(1)
        assert v1['prompt_text'] == "first"
        assert v1['version'] == 1

        v2 = manager.get_prompt_version(2)
        assert v2['prompt_text'] == "second"
        assert v2['parent_version'] == 1

    def test_get_prompt_version_invalid(self, manager):
        assert manager.get_prompt_version(0) is None
        assert manager.get_prompt_version(99) is None

    def test_get_all_versions(self, manager):
        manager._add_prompt_version("v1", "user")
        manager._add_prompt_version("v2", "user")
        versions = manager.get_all_versions()
        assert len(versions) == 2

    def test_get_all_versions_returns_copies(self, manager):
        manager._add_prompt_version("v1", "user")
        versions = manager.get_all_versions()
        versions[0]['prompt_text'] = "modified"
        assert manager.get_current_prompt() == "v1"

    def test_update_prompt(self, manager):
        manager._add_prompt_version("original", "user")
        v = manager.update_prompt("updated", "user")
        assert v == 2
        assert manager.get_current_prompt() == "updated"


class TestPromptManagerTaskDescription:
    """Tests for task description management."""

    @pytest.fixture
    def manager(self):
        return PromptManager({}, _make_mock_solo_config())

    def test_set_and_get(self, manager):
        manager.set_task_description("Classify sentiment")
        assert manager.get_task_description() == "Classify sentiment"

    def test_default_empty(self, manager):
        assert manager.get_task_description() == ""


class TestPromptManagerSchemaInfo:
    """Tests for schema info management."""

    @pytest.fixture
    def manager(self):
        return PromptManager({}, _make_mock_solo_config())

    def test_set_schema_info(self, manager):
        info = {'name': 'test', 'type': 'radio'}
        manager.set_schema_info(info)
        assert manager.schema_info == info


class TestPromptManagerFallback:
    """Tests for fallback prompt creation."""

    def test_fallback_prompt(self):
        config = {'annotation_schemes': [
            {'name': 'test', 'labels': ['positive', 'negative']}
        ]}
        manager = PromptManager(config, _make_mock_solo_config())
        manager.set_task_description("Classify tweets")

        result = manager._create_fallback_prompt()
        assert "Classify tweets" in result
        assert "positive" in result
        assert "negative" in result
        assert manager.current_version == 1

    def test_synthesize_prompt_no_endpoint_returns_fallback(self):
        config = {'annotation_schemes': [
            {'name': 'test', 'labels': ['a', 'b']}
        ]}
        manager = PromptManager(config, _make_mock_solo_config())
        result = manager.synthesize_prompt("Label the text")
        assert result is not None
        assert "Label the text" in result
        assert manager.current_version == 1


class TestPromptManagerFormatting:
    """Tests for formatting helper methods."""

    @pytest.fixture
    def manager(self):
        return PromptManager({}, _make_mock_solo_config())

    def test_format_schema_info(self, manager):
        schemes = [
            {'name': 'sentiment', 'annotation_type': 'radio', 'description': 'Classify sentiment'},
            {'name': 'topic', 'annotation_type': 'multiselect', 'description': 'Select topics'},
        ]
        result = manager._format_schema_info(schemes)
        assert "sentiment: radio" in result
        assert "topic: multiselect" in result

    def test_extract_labels_strings(self, manager):
        schemes = [{'labels': ['positive', 'negative', 'neutral']}]
        result = manager._extract_labels(schemes)
        assert result == "positive, negative, neutral"

    def test_extract_labels_dicts(self, manager):
        schemes = [{'labels': [
            {'name': 'pos', 'description': 'positive'},
            {'name': 'neg'},
        ]}]
        result = manager._extract_labels(schemes)
        assert "pos" in result
        assert "neg" in result

    def test_extract_labels_empty(self, manager):
        assert manager._extract_labels([]) == ""
        assert manager._extract_labels([{}]) == ""

    def test_format_failed_cases(self, manager):
        cases = [
            {'text': 'example text', 'expected_label': 'positive', 'actual_label': 'negative'},
            {'text': 'another one', 'expected_label': 'neutral', 'actual_label': 'positive'},
        ]
        result = manager._format_failed_cases(cases)
        assert "example text" in result
        assert "Expected: positive" in result
        assert "Got: negative" in result

    def test_format_failed_cases_truncates(self, manager):
        """Long text should be truncated to 200 chars."""
        cases = [{'text': 'x' * 500, 'expected_label': 'a', 'actual_label': 'b'}]
        result = manager._format_failed_cases(cases)
        # Truncated to 200 chars of 'x'
        assert len(result) < 500

    def test_format_failed_cases_limits_to_10(self, manager):
        cases = [
            {'text': f'text_{i}', 'expected_label': 'a', 'actual_label': 'b'}
            for i in range(20)
        ]
        result = manager._format_failed_cases(cases)
        # Should only include first 10
        assert "text_9" in result
        assert "text_10" not in result

    def test_format_discrepancies(self, manager):
        cases = [
            {'expected_label': 'positive', 'actual_label': 'negative'},
            {'expected_label': 'positive', 'actual_label': 'negative'},
            {'expected_label': 'neutral', 'actual_label': 'positive'},
        ]
        result = manager._format_discrepancies(cases)
        assert "negative" in result
        assert "positive" in result


class TestPromptManagerJsonParsing:
    """Tests for JSON response parsing."""

    @pytest.fixture
    def manager(self):
        return PromptManager({}, _make_mock_solo_config())

    def test_parse_plain_json(self, manager):
        result = manager._parse_json_response('{"prompt": "hello"}')
        assert result == {"prompt": "hello"}

    def test_parse_markdown_json(self, manager):
        result = manager._parse_json_response('```json\n{"prompt": "hello"}\n```')
        assert result == {"prompt": "hello"}

    def test_parse_markdown_no_lang(self, manager):
        result = manager._parse_json_response('```\n{"prompt": "hello"}\n```')
        assert result == {"prompt": "hello"}

    def test_parse_invalid_json(self, manager):
        result = manager._parse_json_response("Just some text")
        assert result == {"prompt": "Just some text"}


class TestPromptManagerValidation:
    """Tests for validation accuracy tracking."""

    @pytest.fixture
    def manager(self):
        config = {'annotation_schemes': [{'name': 'test', 'labels': ['a']}]}
        m = PromptManager(config, _make_mock_solo_config())
        m._add_prompt_version("v1", "user")
        return m

    def test_set_validation_accuracy(self, manager):
        manager.set_validation_accuracy(1, 0.85)
        v = manager.get_prompt_version(1)
        assert v['validation_accuracy'] == 0.85

    def test_set_validation_accuracy_invalid_version(self, manager):
        # Should not raise
        manager.set_validation_accuracy(99, 0.5)


class TestPromptManagerPersistence:
    """Tests for state persistence."""

    def test_save_and_load(self, tmp_path):
        config = {'annotation_schemes': [{'name': 'test', 'labels': ['a', 'b']}]}
        solo_config = _make_mock_solo_config(str(tmp_path))

        m1 = PromptManager(config, solo_config)
        m1.set_task_description("Test task")
        m1._add_prompt_version("prompt v1", "user")
        m1._add_prompt_version("prompt v2", "llm_revision")

        m2 = PromptManager(config, solo_config)
        assert m2.load_state() is True
        assert m2.get_task_description() == "Test task"
        assert m2.current_version == 2
        assert m2.get_current_prompt() == "prompt v2"
        assert len(m2.get_all_versions()) == 2

    def test_load_nonexistent(self, tmp_path):
        solo_config = _make_mock_solo_config(str(tmp_path))
        m = PromptManager({}, solo_config)
        assert m.load_state() is False

    def test_load_no_state_dir(self):
        m = PromptManager({}, _make_mock_solo_config(None))
        assert m.load_state() is False

    def test_save_no_state_dir(self):
        """Save should be a no-op without state_dir."""
        m = PromptManager({}, _make_mock_solo_config(None))
        m._add_prompt_version("test", "user")  # should not raise


class TestPromptManagerStatus:
    """Tests for status reporting."""

    def test_status_empty(self):
        m = PromptManager({}, _make_mock_solo_config())
        status = m.get_status()
        assert status['has_task_description'] is False
        assert status['current_version'] == 0
        assert status['total_versions'] == 0
        assert status['current_prompt_length'] == 0

    def test_status_with_data(self):
        m = PromptManager({}, _make_mock_solo_config())
        m.set_task_description("Test")
        m._add_prompt_version("Hello World", "user")
        status = m.get_status()
        assert status['has_task_description'] is True
        assert status['current_version'] == 1
        assert status['total_versions'] == 1
        assert status['current_prompt_length'] == 11
