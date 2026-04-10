#!/usr/bin/env python3
"""
Unit tests for DialogueDisplay span target support.

Verifies that DialogueDisplay generates the correct .text-content wrapper
with proper data-original-text when span_target is true, and omits it
when span_target is false.
"""

import pytest
from potato.server_utils.displays.dialogue_display import DialogueDisplay


class TestDialogueSpanTarget:
    """Test DialogueDisplay span annotation wrapper generation."""

    @pytest.fixture
    def display(self):
        return DialogueDisplay()

    @pytest.fixture
    def dialogue_data(self):
        """Sample dialogue data as list of dicts."""
        return [
            {"speaker": "Agent", "text": "I will search for flights."},
            {"speaker": "Environment", "text": "Found 3 flights."},
            {"speaker": "Agent", "text": "The cheapest is BA117 at $450."},
        ]

    @pytest.fixture
    def span_field_config(self):
        return {
            "key": "conversation",
            "type": "dialogue",
            "span_target": True,
            "display_options": {},
        }

    @pytest.fixture
    def no_span_field_config(self):
        return {
            "key": "conversation",
            "type": "dialogue",
            "span_target": False,
            "display_options": {},
        }

    def test_text_content_wrapper_present_when_span_target(
        self, display, dialogue_data, span_field_config
    ):
        """When span_target is true, output must contain a .text-content wrapper."""
        html = display.render(span_field_config, dialogue_data)
        assert 'class="text-content"' in html
        assert 'id="text-content-conversation"' in html

    def test_data_original_text_contains_concatenated_turns(
        self, display, dialogue_data, span_field_config
    ):
        """Each turn's text must appear in a data-original-text attribute."""
        html = display.render(span_field_config, dialogue_data)
        assert 'data-original-text="I will search for flights."' in html
        assert 'data-original-text="Found 3 flights."' in html
        assert 'data-original-text="The cheapest is BA117 at $450."' in html

    def test_no_text_content_wrapper_without_span_target(
        self, display, dialogue_data, no_span_field_config
    ):
        """When span_target is false, there should be no .text-content wrapper."""
        html = display.render(no_span_field_config, dialogue_data)
        assert 'class="text-content"' not in html
        assert 'id="text-content-conversation"' not in html

    def test_concatenation_format_matches_expected(
        self, display, span_field_config
    ):
        """Verify each turn renders with speaker label and text in separate spans."""
        data = [
            {"speaker": "Alice", "text": "Hello"},
            {"speaker": "Bob", "text": "Hi there"},
        ]
        html = display.render(span_field_config, data)
        assert 'data-speaker="Alice"' in html
        assert 'data-original-text="Hello"' in html
        assert 'data-speaker="Bob"' in html
        assert 'data-original-text="Hi there"' in html

    def test_no_speaker_concatenation(self, display, span_field_config):
        """Turns without a speaker should just use the text."""
        data = [
            {"speaker": "", "text": "No speaker here"},
            {"speaker": "Agent", "text": "I have a speaker"},
        ]
        html = display.render(span_field_config, data)
        assert 'data-original-text="No speaker here"' in html
        assert 'data-speaker="Agent"' in html
        assert 'data-original-text="I have a speaker"' in html

    def test_dialogue_turns_still_rendered_inside_wrapper(
        self, display, dialogue_data, span_field_config
    ):
        """Individual dialogue turns should still be rendered inside the wrapper."""
        html = display.render(span_field_config, dialogue_data)
        assert "dialogue-turn" in html
        assert "dialogue-speaker" in html

    def test_string_data_with_span_target(self, display, span_field_config):
        """String dialogue data should also get the .text-content wrapper."""
        data = "Agent: Hello\nUser: Hi"
        html = display.render(span_field_config, data)
        assert 'class="text-content"' in html
        assert 'id="text-content-conversation"' in html

    def test_special_characters_escaped_in_data_original_text(
        self, display, span_field_config
    ):
        """Special HTML characters in text must be escaped in data-original-text."""
        data = [
            {"speaker": "Agent", "text": 'Price is <$500 & "cheap"'},
        ]
        html = display.render(span_field_config, data)
        # The attribute value should have HTML-escaped content
        assert "&lt;" in html or "&#" in html  # < is escaped
        assert "&amp;" in html  # & is escaped
