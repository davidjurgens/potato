"""
Regression tests for Batch 3 edge case fixes (items 15-18).

Each test class targets a specific edge case identified during code review.
"""

import pytest

from potato.trace_converter.converters.atif_converter import ATIFConverter
from potato.trace_converter.converters.webarena_converter import WebArenaConverter


class TestItem15ATIFNullFields:
    """
    Bug: ATIF converter crashes when JSON fields are explicitly null
    (e.g., "metrics": null). dict.get("metrics", {}) returns None when
    the key exists with value null, then .items() on None raises AttributeError.

    Fix: Use `or {}` pattern to coalesce None to empty dict.
    """

    def test_null_metrics(self):
        """Explicit null metrics should not crash."""
        converter = ATIFConverter()
        data = [{
            "trace_id": "t1",
            "task": {"description": "test"},
            "agent": {"name": "TestAgent"},
            "steps": [],
            "metrics": None
        }]
        traces = converter.convert(data)
        assert len(traces) == 1
        assert traces[0].id == "t1"

    def test_null_task(self):
        """Explicit null task should not crash."""
        converter = ATIFConverter()
        data = [{
            "trace_id": "t1",
            "task": None,
            "agent": {"name": "TestAgent"},
            "steps": [],
        }]
        traces = converter.convert(data)
        assert len(traces) == 1
        assert traces[0].task_description == ""

    def test_null_agent(self):
        """Explicit null agent should not crash."""
        converter = ATIFConverter()
        data = [{
            "trace_id": "t1",
            "task": {"description": "test"},
            "agent": None,
            "steps": [],
        }]
        traces = converter.convert(data)
        assert len(traces) == 1
        assert traces[0].agent_name == ""

    def test_null_steps(self):
        """Explicit null steps should not crash."""
        converter = ATIFConverter()
        data = [{
            "trace_id": "t1",
            "task": {"description": "test"},
            "agent": {"name": "TestAgent"},
            "steps": None,
        }]
        traces = converter.convert(data)
        assert len(traces) == 1
        assert traces[0].conversation == []

    def test_null_outcome(self):
        """Explicit null outcome should not crash."""
        converter = ATIFConverter()
        data = [{
            "trace_id": "t1",
            "task": {"description": "test"},
            "agent": {"name": "TestAgent"},
            "steps": [],
            "outcome": None,
        }]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_all_null_fields(self):
        """All fields null should not crash."""
        converter = ATIFConverter()
        data = [{
            "trace_id": "t1",
            "task": None,
            "agent": None,
            "steps": None,
            "outcome": None,
            "metrics": None,
        }]
        traces = converter.convert(data)
        assert len(traces) == 1


class TestItem16WebArenaNullActions:
    """
    Bug: WebArena converter crashes when actions field is explicitly null.
    Iterating over None raises TypeError.

    Fix: Use `or []` pattern to coalesce None to empty list.
    """

    def test_null_actions(self):
        """Explicit null actions should not crash."""
        converter = WebArenaConverter()
        data = [{
            "task_id": "wa_001",
            "intent": "Do something",
            "actions": None,
        }]
        traces = converter.convert(data)
        assert len(traces) == 1
        assert traces[0].conversation == []

    def test_null_action_history(self):
        """Explicit null action_history (alternate key) should not crash."""
        converter = WebArenaConverter()
        data = [{
            "task_id": "wa_001",
            "intent": "Do something",
            "action_history": None,
        }]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_null_evaluation(self):
        """Explicit null evaluation should not crash."""
        converter = WebArenaConverter()
        data = [{
            "task_id": "wa_001",
            "intent": "Do something",
            "actions": [],
            "evaluation": None,
        }]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_missing_actions_entirely(self):
        """Missing actions key should default to empty list."""
        converter = WebArenaConverter()
        data = [{
            "task_id": "wa_001",
            "intent": "Do something",
        }]
        traces = converter.convert(data)
        assert len(traces) == 1
        assert traces[0].conversation == []


class TestItem17ConversationTreeInValidTypes:
    """
    Bug: conversation_tree display type exists and is registered in the
    display registry, but was missing from config_module.py's
    valid_display_types list, causing config validation to reject it.

    Fix: Add "conversation_tree" to valid_display_types.
    """

    def test_conversation_tree_in_display_registry(self):
        """conversation_tree should be registered in the display registry."""
        from potato.server_utils.displays.registry import display_registry
        assert display_registry.is_registered("conversation_tree")

    def test_conversation_tree_in_valid_display_types(self):
        """conversation_tree should be in config_module's valid_display_types."""
        from potato.server_utils.config_module import validate_instance_display_config
        # This would raise ConfigValidationError if conversation_tree is not valid
        # We test indirectly by ensuring the type is in the list
        # Read the source to check
        import inspect
        source = inspect.getsource(validate_instance_display_config)
        assert "conversation_tree" in source, \
            "conversation_tree should be in valid_display_types in config_module.py"

    def test_all_registered_displays_in_valid_types(self):
        """All registered display types should be in config_module's valid_display_types."""
        from potato.server_utils.displays.registry import display_registry
        import inspect
        from potato.server_utils.config_module import validate_instance_display_config

        source = inspect.getsource(validate_instance_display_config)
        registered_types = display_registry.get_supported_types()
        for display_type in registered_types:
            assert display_type in source, \
                f"Display type '{display_type}' is registered but not in valid_display_types"
