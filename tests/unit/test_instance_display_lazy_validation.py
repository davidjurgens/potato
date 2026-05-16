"""Regression tests for instance_display's lazy-populated-field validation.

Display types whose data is populated after initial render (interactive_chat,
live_agent, live_coding_agent) must NOT trigger a field-validation error
when their key is absent from ``instance_data`` at render time -- the
key is expected to be written later (by /agent_chat/finish or similar).

All OTHER missing fields should still be caught, surfaced as
``display_error`` on the template result, and logged at WARNING (not
ERROR) severity.
"""
import logging

import pytest

from potato.server_utils.displays import display_registry
from potato.server_utils.instance_display import (
    InstanceDisplayError,
    InstanceDisplayRenderer,
)


class TestLazyPopulatedRegistry:
    def test_interactive_chat_is_lazy(self):
        assert display_registry.is_lazy_populated("interactive_chat") is True

    def test_live_agent_is_lazy(self):
        assert display_registry.is_lazy_populated("live_agent") is True

    def test_live_coding_agent_is_lazy(self):
        assert display_registry.is_lazy_populated("live_coding_agent") is True

    def test_standard_displays_are_not_lazy(self):
        for name in ("text", "image", "video", "audio", "dialogue",
                     "spreadsheet", "pdf", "code"):
            assert display_registry.is_lazy_populated(name) is False, (
                f"'{name}' unexpectedly reported lazy"
            )

    def test_unknown_type_reports_not_lazy_safely(self):
        assert display_registry.is_lazy_populated("nonexistent_xyz") is False


def _make_renderer(fields):
    config = {
        "instance_display": {
            "fields": fields,
            "layout": {},
        }
    }
    return InstanceDisplayRenderer(config)


class TestInstanceDisplayValidation:
    def test_missing_lazy_field_does_not_raise(self):
        renderer = _make_renderer([
            {"key": "task_description", "type": "text"},
            {"key": "conversation", "type": "interactive_chat"},
        ])
        # `conversation` is absent -- must be accepted as transient.
        instance_data = {"task_description": "Do the thing"}
        # Should NOT raise
        renderer._validate_fields(instance_data)

    def test_missing_non_lazy_field_still_raises(self):
        renderer = _make_renderer([
            {"key": "passage", "type": "text"},
        ])
        with pytest.raises(InstanceDisplayError) as exc_info:
            renderer._validate_fields({"task_description": "x"})
        assert "passage" in str(exc_info.value)

    def test_missing_live_coding_agent_field_allowed(self):
        renderer = _make_renderer([
            {"key": "structured_turns", "type": "live_coding_agent"},
        ])
        renderer._validate_fields({})  # no conversation yet; should be silent

    def test_missing_live_agent_field_allowed(self):
        renderer = _make_renderer([
            {"key": "trace", "type": "live_agent"},
        ])
        renderer._validate_fields({})

    def test_present_lazy_field_also_fine(self):
        renderer = _make_renderer([
            {"key": "conversation", "type": "interactive_chat"},
        ])
        renderer._validate_fields({"conversation": [{"speaker": "A", "text": "hi"}]})


class TestInstanceDisplayLogging:
    def test_non_lazy_validation_failure_logs_warning_not_error(self, caplog):
        renderer = _make_renderer([
            {"key": "oops_typo", "type": "text"},
        ])
        with caplog.at_level(logging.WARNING, logger="potato.server_utils.instance_display"):
            variables = renderer.get_template_variables({"task_description": "x"})

        # Surfaced to the template so the page shows an error div
        assert "display_error" in variables
        assert "oops_typo" in variables["display_error"]

        # Logged at WARNING exactly (not ERROR)
        relevant = [
            r for r in caplog.records
            if r.name == "potato.server_utils.instance_display"
            and "Field validation failed" in r.message
        ]
        assert len(relevant) == 1
        assert relevant[0].levelno == logging.WARNING

    def test_lazy_field_never_produces_a_warning_or_error(self, caplog):
        renderer = _make_renderer([
            {"key": "task_description", "type": "text"},
            {"key": "conversation", "type": "interactive_chat"},
        ])
        with caplog.at_level(logging.DEBUG, logger="potato.server_utils.instance_display"):
            renderer.get_template_variables({"task_description": "t"})
        levels = {r.levelno for r in caplog.records if r.name == "potato.server_utils.instance_display"}
        assert logging.ERROR not in levels
        assert logging.WARNING not in levels
