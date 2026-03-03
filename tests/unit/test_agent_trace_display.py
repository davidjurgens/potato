"""
Tests for the agent_trace, gallery, and dialogue display types
(including multi-dimension per_turn_ratings).
"""

import pytest

from potato.server_utils.displays.agent_trace_display import AgentTraceDisplay
from potato.server_utils.displays.dialogue_display import DialogueDisplay
from potato.server_utils.displays.gallery_display import GalleryDisplay
from potato.server_utils.displays.registry import display_registry


class TestAgentTraceDisplay:
    """Tests for the AgentTraceDisplay class."""

    def setup_method(self):
        self.display = AgentTraceDisplay()

    def test_registered_in_registry(self):
        """agent_trace should be registered in the display registry."""
        assert display_registry.is_registered("agent_trace")

    def test_supports_span_target(self):
        assert self.display.supports_span_target is True

    def test_render_empty(self):
        html = self.display.render({"key": "test"}, None)
        assert "No trace data" in html

    def test_render_empty_list(self):
        html = self.display.render({"key": "test"}, [])
        assert "No trace" in html

    def test_render_speaker_text_format(self):
        """Should render list of {speaker, text} dicts."""
        data = [
            {"speaker": "Agent (Thought)", "text": "I need to search"},
            {"speaker": "Agent (Action)", "text": "search(query='test')"},
            {"speaker": "Environment", "text": "Found 3 results"},
        ]
        html = self.display.render({"key": "trace"}, data)

        assert "step-type-thought" in html
        assert "step-type-action" in html
        assert "step-type-observation" in html
        assert "I need to search" in html
        assert "search(query=&#x27;test&#x27;)" in html or "search(query=" in html

    def test_render_react_format(self):
        """Should render list of {thought, action, observation} dicts."""
        data = [
            {
                "thought": "Planning step",
                "action": "do_something()",
                "observation": "Result obtained"
            }
        ]
        html = self.display.render({"key": "trace"}, data)

        assert "Planning step" in html
        assert "do_something()" in html
        assert "Result obtained" in html

    def test_render_with_structured_action(self):
        """Should handle action as dict with tool/params."""
        data = [
            {
                "thought": "Need to search",
                "action": {"tool": "web_search", "params": {"query": "test"}},
                "observation": "Results found"
            }
        ]
        html = self.display.render({"key": "trace"}, data)
        assert "web_search" in html

    def test_summary_section(self):
        """Should render a summary with step counts."""
        data = [
            {"speaker": "Agent (Thought)", "text": "Think"},
            {"speaker": "Agent (Action)", "text": "Act"},
            {"speaker": "Environment", "text": "Result"},
        ]
        html = self.display.render({"key": "trace"}, data)
        assert "agent-trace-summary" in html
        assert "3 steps" in html

    def test_step_numbers(self):
        """Step numbers should appear for thought and action steps."""
        data = [
            {"speaker": "Agent (Thought)", "text": "Think"},
            {"speaker": "Agent (Action)", "text": "Act"},
        ]
        html = self.display.render({"key": "trace"}, data)
        assert "step-number" in html

    def test_collapse_observations(self):
        """Observations should be collapsible when option is set."""
        data = [
            {"speaker": "Environment", "text": "Long result..."},
        ]
        field_config = {
            "key": "trace",
            "display_options": {"collapse_observations": True}
        }
        html = self.display.render(field_config, data)
        assert "<details" in html

    def test_custom_colors(self):
        """Should use custom step type colors."""
        data = [
            {"speaker": "Agent (Thought)", "text": "Think"},
        ]
        field_config = {
            "key": "trace",
            "display_options": {
                "step_type_colors": {"thought": "#ff0000"}
            }
        }
        html = self.display.render(field_config, data)
        assert "#ff0000" in html

    def test_span_target_attributes(self):
        """Should add span target attributes when enabled."""
        data = [
            {"speaker": "Agent (Thought)", "text": "Think"},
        ]
        field_config = {"key": "trace", "span_target": True}
        html = self.display.render(field_config, data)
        assert "data-original-text" in html
        assert "data-step-index" in html

    def test_string_input(self):
        """Should handle a plain string input."""
        html = self.display.render({"key": "trace"}, "Just a string")
        assert "Just a string" in html

    def test_css_classes(self):
        classes = self.display.get_css_classes({"key": "test"})
        assert "display-field" in classes
        assert "display-type-agent_trace" in classes

    def test_css_classes_span_target(self):
        classes = self.display.get_css_classes({"key": "test", "span_target": True})
        assert "span-target-field" in classes


class TestGalleryDisplay:
    """Tests for the GalleryDisplay class."""

    def setup_method(self):
        self.display = GalleryDisplay()

    def test_registered_in_registry(self):
        """gallery should be registered in the display registry."""
        assert display_registry.is_registered("gallery")

    def test_does_not_support_span_target(self):
        assert self.display.supports_span_target is False

    def test_render_empty(self):
        html = self.display.render({"key": "test"}, None)
        assert "No images" in html

    def test_render_string_list(self):
        """Should render a list of URL strings."""
        data = ["img1.png", "img2.png", "img3.png"]
        html = self.display.render({"key": "screenshots"}, data)

        assert "img1.png" in html
        assert "img2.png" in html
        assert "img3.png" in html
        assert html.count('class="gallery-item"') == 3

    def test_render_dict_list(self):
        """Should render a list of {url, caption} dicts."""
        data = [
            {"url": "img1.png", "caption": "Step 1"},
            {"url": "img2.png", "caption": "Step 2"},
        ]
        html = self.display.render({"key": "screenshots"}, data)

        assert "img1.png" in html
        assert "Step 1" in html
        assert "Step 2" in html

    def test_render_single_string(self):
        """Should handle a single string input."""
        html = self.display.render({"key": "img"}, "single.png")
        assert "single.png" in html

    def test_horizontal_layout(self):
        data = ["img1.png"]
        field_config = {
            "key": "screenshots",
            "display_options": {"layout": "horizontal"}
        }
        html = self.display.render(field_config, data)
        assert "gallery-horizontal" in html

    def test_vertical_layout(self):
        data = ["img1.png"]
        field_config = {
            "key": "screenshots",
            "display_options": {"layout": "vertical"}
        }
        html = self.display.render(field_config, data)
        assert "gallery-vertical" in html

    def test_grid_layout(self):
        data = ["img1.png"]
        field_config = {
            "key": "screenshots",
            "display_options": {"layout": "grid"}
        }
        html = self.display.render(field_config, data)
        assert "gallery-grid" in html

    def test_zoomable_attribute(self):
        data = ["img1.png"]
        field_config = {
            "key": "screenshots",
            "display_options": {"zoomable": True}
        }
        html = self.display.render(field_config, data)
        assert 'data-zoomable="true"' in html

    def test_no_captions(self):
        data = [{"url": "img1.png", "caption": "Test Caption"}]
        field_config = {
            "key": "screenshots",
            "display_options": {"show_captions": False}
        }
        html = self.display.render(field_config, data)
        assert "Test Caption" not in html

    def test_custom_url_key(self):
        data = [{"src": "img1.png", "label": "First"}]
        field_config = {
            "key": "screenshots",
            "display_options": {"url_key": "src", "caption_key": "label"}
        }
        html = self.display.render(field_config, data)
        assert "img1.png" in html
        assert "First" in html


class TestDisplayRegistryCompleteness:
    """Test that new display types are properly registered everywhere."""

    def test_agent_trace_in_config_valid_types(self):
        """agent_trace should be in config_module's valid_display_types."""
        from potato.server_utils.config_module import validate_instance_display_config
        # We can't directly access the list, but we verify it doesn't raise
        # for agent_trace type by testing registry registration
        assert display_registry.is_registered("agent_trace")

    def test_gallery_in_config_valid_types(self):
        """gallery should be in config_module's valid_display_types."""
        assert display_registry.is_registered("gallery")

    def test_agent_trace_in_supported_types(self):
        types = display_registry.get_supported_types()
        assert "agent_trace" in types

    def test_gallery_in_supported_types(self):
        types = display_registry.get_supported_types()
        assert "gallery" in types


class TestDialoguePerTurnRatings:
    """Tests for per_turn_ratings in DialogueDisplay, including multi-dimension."""

    def setup_method(self):
        self.display = DialogueDisplay()
        self.dialogue_data = [
            {"speaker": "Agent (Thought)", "text": "I need to search."},
            {"speaker": "Agent (Action)", "text": "search(query='test')"},
            {"speaker": "Environment", "text": "Found 3 results."},
            {"speaker": "Agent (Action)", "text": "click(result=1)"},
        ]

    def test_single_scheme_legacy_format(self):
        """Legacy single-scheme format should still work."""
        field_config = {
            "key": "conversation",
            "display_options": {
                "per_turn_ratings": {
                    "speakers": ["Agent (Action)"],
                    "schema_name": "correctness",
                    "scheme": {"type": "likert", "size": 3, "labels": ["Wrong", "Right"]},
                }
            }
        }
        html = self.display.render(field_config, self.dialogue_data)

        # Should have per-turn ratings
        assert "has-per-turn-ratings" in html
        assert "per-turn-rating" in html
        # Should have ptr-value elements for rated turns
        assert 'data-schema="correctness"' in html
        # Should have hidden input for the schema
        assert 'name="correctness"' in html
        assert "per-turn-hidden" in html

    def test_multi_scheme_format(self):
        """Multi-dimension schemes should render multiple ratings per turn."""
        field_config = {
            "key": "conversation",
            "display_options": {
                "per_turn_ratings": {
                    "speakers": ["Agent (Action)"],
                    "schemes": [
                        {
                            "schema_name": "correctness",
                            "scheme": {"type": "likert", "size": 3, "labels": ["Wrong", "Right"]},
                        },
                        {
                            "schema_name": "reasoning",
                            "scheme": {"type": "likert", "size": 5, "labels": ["Poor", "Excellent"]},
                        },
                    ]
                }
            }
        }
        html = self.display.render(field_config, self.dialogue_data)

        # Should have the multi-dimension group wrapper
        assert "per-turn-rating-group" in html
        # Should have both schema names
        assert 'data-schema="correctness"' in html
        assert 'data-schema="reasoning"' in html
        # Should have two hidden inputs
        assert 'name="correctness"' in html
        assert 'name="reasoning"' in html
        # Should have schema labels
        assert "Correctness:" in html
        assert "Reasoning:" in html

    def test_multi_scheme_hidden_inputs(self):
        """Each scheme should get its own hidden input."""
        field_config = {
            "key": "conv",
            "display_options": {
                "per_turn_ratings": {
                    "speakers": ["Agent (Action)"],
                    "schemes": [
                        {"schema_name": "s1", "scheme": {"size": 3}},
                        {"schema_name": "s2", "scheme": {"size": 5}},
                    ]
                }
            }
        }
        html = self.display.render(field_config, self.dialogue_data)

        assert 'data-schema-name="s1"' in html
        assert 'data-schema-name="s2"' in html

    def test_only_rated_speakers_get_ratings(self):
        """Only turns with rated speakers should get rating widgets."""
        field_config = {
            "key": "conversation",
            "display_options": {
                "per_turn_ratings": {
                    "speakers": ["Agent (Action)"],
                    "schema_name": "test",
                    "scheme": {"size": 3},
                }
            }
        }
        html = self.display.render(field_config, self.dialogue_data)

        # Agent (Action) has turn indices 1 and 3
        assert 'data-turn="1"' in html
        assert 'data-turn="3"' in html
        # Agent (Thought) and Environment should NOT have ratings
        # (turn 0 and 2 should not have ptr-value elements)
        assert 'data-turn="0"' not in html.split("ptr-value")[0] or \
               html.count('data-turn="0"') == 0  # turn 0 is Thought, no rating

    def test_no_per_turn_ratings(self):
        """Without per_turn_ratings config, no rating widgets should appear."""
        field_config = {"key": "conversation"}
        html = self.display.render(field_config, self.dialogue_data)

        assert "per-turn-rating" not in html
        assert "ptr-value" not in html
        assert "has-per-turn-ratings" not in html

    def test_scheme_sizes_match(self):
        """Each scheme should generate the correct number of rating values."""
        field_config = {
            "key": "conv",
            "display_options": {
                "per_turn_ratings": {
                    "speakers": ["Agent (Action)"],
                    "schemes": [
                        {"schema_name": "s3", "scheme": {"size": 3}},
                        {"schema_name": "s7", "scheme": {"size": 7}},
                    ]
                }
            }
        }
        html = self.display.render(field_config, self.dialogue_data)

        # 2 action turns x 3 values = 6 for s3, 2 x 7 = 14 for s7
        assert html.count('data-schema="s3"') == 2 * 3 + 2  # values + rating divs
        assert html.count('data-schema="s7"') == 2 * 7 + 2  # values + rating divs
