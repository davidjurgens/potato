#!/usr/bin/env python3
"""
Contract enforcement tests for the display type span annotation system.

These tests verify structural invariants that prevent the class of bug
where a display type declares supports_span_target=True but fails to
produce the required .text-content wrapper.

See displays/ARCHITECTURE.md for the full contract specification.
"""

import pytest
from potato.server_utils.displays import display_registry
from potato.server_utils.displays.base import BaseDisplay, concatenate_dialogue_text


# ---------------------------------------------------------------------------
# Sample data for each display type that supports span_target
# ---------------------------------------------------------------------------
SPAN_TARGET_TEST_DATA = {
    "text": "The quick brown fox jumps over the lazy dog.",
    "dialogue": [
        {"speaker": "Alice", "text": "Hello there."},
        {"speaker": "Bob", "text": "Hi, how are you?"},
    ],
    "document": "<p>This is a document paragraph.</p>",
    "code": "def hello():\n    print('world')\n",
    "interactive_chat": [
        {"speaker": "User", "text": "Tell me a joke."},
        {"speaker": "Agent", "text": "Why did the chicken cross the road?"},
    ],
}


def _get_span_target_types():
    """Get all display types that declare supports_span_target=True."""
    return display_registry.get_span_target_types()


class TestSpanTargetContract:
    """Every display type declaring supports_span_target=True must produce
    a .text-content wrapper when span_target is True in the field config."""

    @pytest.fixture(params=_get_span_target_types(), ids=lambda t: t)
    def span_type(self, request):
        return request.param

    def _render_with_span_target(self, type_name):
        field_config = {
            "key": "test_field",
            "type": type_name,
            "label": "Test",
            "span_target": True,
            "display_options": {},
        }
        data = SPAN_TARGET_TEST_DATA.get(type_name, "Default test text.")
        return display_registry.render(type_name, field_config, data)

    def test_text_content_wrapper_present(self, span_type):
        """Rendered HTML must contain a .text-content div."""
        html = self._render_with_span_target(span_type)
        assert 'class="text-content"' in html or "text-content" in html, (
            f"Display type '{span_type}' declares supports_span_target=True "
            f"but render output does not contain .text-content wrapper. "
            f"SpanManager will silently skip this field."
        )

    def test_text_content_id_present(self, span_type):
        """Rendered HTML must contain id='text-content-{field_key}'."""
        html = self._render_with_span_target(span_type)
        assert 'id="text-content-test_field"' in html, (
            f"Display type '{span_type}' missing id='text-content-test_field' "
            f"in render output. SpanManager uses this ID for field lookup."
        )

    def test_data_original_text_present(self, span_type):
        """Rendered HTML must contain data-original-text attribute.

        Exception: code display intentionally omits data-original-text and
        uses DOM textContent directly for more accurate character positioning.
        """
        if span_type == "code":
            pytest.skip("code display uses DOM textContent instead of data-original-text")
        html = self._render_with_span_target(span_type)
        assert "data-original-text=" in html, (
            f"Display type '{span_type}' missing data-original-text attribute. "
            f"SpanManager uses this for offset-based positioning."
        )

    def test_span_target_data_attribute(self, span_type):
        """Outer container must have data-span-target='true'."""
        html = self._render_with_span_target(span_type)
        assert 'data-span-target="true"' in html, (
            f"Display type '{span_type}' missing data-span-target='true'. "
            f"SpanManager discovers fields via this attribute."
        )


class TestRegistryConsistency:
    """Verify registry metadata is consistent with display class attributes."""

    def test_get_span_target_types_non_empty(self):
        """At least some display types should support span targets."""
        types = display_registry.get_span_target_types()
        assert len(types) > 0, "No display types support span targets"

    def test_registry_lists_match_class_attributes(self):
        """DisplayDefinition.supports_span_target must match the class attribute."""
        for info in display_registry.list_displays():
            name = info["name"]
            registry_value = info["supports_span_target"]
            class_value = display_registry.type_supports_span_target(name)
            assert registry_value == class_value, (
                f"Display '{name}': list_displays says supports_span_target="
                f"{registry_value} but type_supports_span_target() returns "
                f"{class_value}"
            )

    def test_non_span_types_excluded(self):
        """Types with supports_span_target=False must NOT appear in
        get_span_target_types()."""
        span_types = set(display_registry.get_span_target_types())
        for info in display_registry.list_displays():
            if not info["supports_span_target"]:
                assert info["name"] not in span_types, (
                    f"Display '{info['name']}' has supports_span_target=False "
                    f"but appears in get_span_target_types()"
                )


class TestConcatenateDialogueText:
    """Verify the shared dialogue concatenation utility."""

    def test_list_of_dicts(self):
        data = [
            {"speaker": "A", "text": "Hello"},
            {"speaker": "B", "text": "Hi"},
        ]
        assert concatenate_dialogue_text(data) == "A: Hello\nB: Hi"

    def test_no_speaker(self):
        data = [
            {"speaker": "", "text": "No speaker"},
            {"speaker": "B", "text": "With speaker"},
        ]
        assert concatenate_dialogue_text(data) == "No speaker\nB: With speaker"

    def test_list_of_strings(self):
        data = ["Hello", "World"]
        assert concatenate_dialogue_text(data) == "Hello\nWorld"

    def test_string_passthrough(self):
        assert concatenate_dialogue_text("just a string") == "just a string"

    def test_custom_keys(self):
        data = [{"role": "user", "content": "Hi"}]
        result = concatenate_dialogue_text(data, speaker_key="role", text_key="content")
        assert result == "user: Hi"

    def test_empty_list(self):
        assert concatenate_dialogue_text([]) == ""

    def test_mixed_list(self):
        data = [{"speaker": "A", "text": "dict"}, "plain string", 42]
        result = concatenate_dialogue_text(data)
        assert result == "A: dict\nplain string\n42"


class TestBaseDisplaySpanWrapper:
    """Verify the render_span_wrapper helper method."""

    def test_wrapper_has_text_content_class(self):
        class DummyDisplay(BaseDisplay):
            name = "dummy"
            def render(self, fc, d):
                return ""
        d = DummyDisplay()
        html = d.render_span_wrapper("myfield", "<p>Hello</p>", "Hello")
        assert 'class="text-content"' in html

    def test_wrapper_has_correct_id(self):
        class DummyDisplay(BaseDisplay):
            name = "dummy"
            def render(self, fc, d):
                return ""
        d = DummyDisplay()
        html = d.render_span_wrapper("conversation", "<p>Hi</p>", "Hi")
        assert 'id="text-content-conversation"' in html

    def test_wrapper_has_data_original_text(self):
        class DummyDisplay(BaseDisplay):
            name = "dummy"
            def render(self, fc, d):
                return ""
        d = DummyDisplay()
        html = d.render_span_wrapper("f", "<p>Test</p>", "Test text here")
        assert 'data-original-text="Test text here"' in html

    def test_wrapper_escapes_html_in_text(self):
        class DummyDisplay(BaseDisplay):
            name = "dummy"
            def render(self, fc, d):
                return ""
        d = DummyDisplay()
        html = d.render_span_wrapper("f", "<p>X</p>", 'Price <$500 & "cheap"')
        assert "&lt;" in html
        assert "&amp;" in html
        assert "&quot;" in html

    def test_wrapper_preserves_inner_html(self):
        class DummyDisplay(BaseDisplay):
            name = "dummy"
            def render(self, fc, d):
                return ""
        d = DummyDisplay()
        inner = '<span class="dialogue-text">Hello world</span>'
        html = d.render_span_wrapper("f", inner, "Hello world")
        assert inner in html


class TestValidateConfigSpanWarning:
    """validate_config should warn when span_target is set on unsupported types."""

    def test_unsupported_type_warns(self):
        class NoSpanDisplay(BaseDisplay):
            name = "nospan"
            supports_span_target = False
            def render(self, fc, d):
                return ""
        d = NoSpanDisplay()
        errors = d.validate_config({"key": "test", "span_target": True})
        assert any("does not support span_target" in e for e in errors)

    def test_supported_type_no_warning(self):
        class SpanDisplay(BaseDisplay):
            name = "withspan"
            supports_span_target = True
            def render(self, fc, d):
                return ""
        d = SpanDisplay()
        errors = d.validate_config({"key": "test", "span_target": True})
        assert not any("does not support span_target" in e for e in errors)
