"""
Unit tests for the audio_dialogue display type.

Covers registry membership, span-target wrapper, per-turn play buttons, roster
color/side resolution, undiarized speaker picker, turn-slot injection, and the
speaker-assignment hidden input.
"""

import json
import re

import pytest

from potato.server_utils.displays import display_registry
from potato.server_utils.displays.audio_dialogue_display import AudioDialogueDisplay


DATA = {
    "audio": "ep.mp3",
    "turns": [
        {"turn_id": "t0", "speaker": "host", "start": 0.0, "end": 6.5, "text": "Welcome back."},
        {"turn_id": "t1", "speaker": "guest", "start": 6.5, "end": 12.0, "text": "Glad to be here."},
        {"turn_id": "t2", "start": 12.0, "end": 18.0, "text": "No speaker on this turn."},
    ],
}

ROSTER = [
    {"id": "host", "name": "Host", "color": "#7c3aed", "side": "left"},
    {"id": "guest", "name": "Guest", "color": "#059669", "side": "right"},
]


def _field(span_target=True, options=None, turn_schemes=None):
    field = {
        "key": "conversation",
        "type": "audio_dialogue",
        "span_target": span_target,
        "display_options": {"speakers": ROSTER, **(options or {})},
    }
    if turn_schemes is not None:
        field["_turn_schemes"] = turn_schemes
    return field


def _render(field=None, data=None):
    return display_registry.render("audio_dialogue", field or _field(), data or DATA)


class TestRegistry:
    def test_registered(self):
        assert display_registry.is_registered("audio_dialogue")

    def test_supports_span_target(self):
        assert display_registry.type_supports_span_target("audio_dialogue") is True

    def test_in_span_target_types(self):
        assert "audio_dialogue" in display_registry.get_span_target_types()


class TestRender:
    def test_span_target_wrapper(self):
        html = _render()
        assert 'id="text-content-conversation"' in html
        assert "ad-text-content" in html

    def test_audio_element_and_src(self):
        html = _render()
        assert 'id="ad-audio-conversation"' in html
        assert 'src="ep.mp3"' in html

    def test_per_turn_play_buttons_carry_times(self):
        html = _render()
        assert 'class="ad-play" data-start="0.000" data-end="6.500"' in html
        assert 'data-start="6.500" data-end="12.000"' in html

    def test_roster_colors_and_sides(self):
        html = _render()
        # host -> purple, left; guest -> emerald, right
        assert "--ad-color:#7c3aed" in html
        assert "--ad-color:#059669" in html
        assert "ad-side-left" in html
        assert "ad-side-right" in html

    def test_speaker_button_and_menu(self):
        html = _render()
        assert "ad-unassigned" in html
        # every turn's speaker is a clickable button that opens the menu
        assert 'class="ad-speaker-btn"' in html
        assert 'aria-haspopup="menu"' in html
        # one document-level popover menu container per field (outside .text-content)
        assert 'id="ad-menu-conversation"' in html
        assert 'class="ad-speaker-menu"' in html

    def test_speaker_assignment_hidden_input(self):
        html = _render()
        assert 'name="conversation_speakers"' in html
        assert "annotation-data-input ad-speaker-input" in html

    def test_fully_diarized_with_roster_is_reassignable(self):
        # With a roster, the annotator can correct diarized labels, so the
        # speaker button + assignment store are present even with no gaps.
        data = {"audio": "e.mp3", "turns": [
            {"speaker": "host", "start": 0, "end": 1, "text": "a"},
            {"speaker": "guest", "start": 1, "end": 2, "text": "b"},
        ]}
        html = _render(data=data)
        assert 'class="ad-speaker-btn"' in html
        assert 'name="conversation_speakers"' in html

    def test_assignment_can_be_disabled(self):
        # Explicit opt-out: no speaker button / menu / store.
        data = {"audio": "e.mp3", "turns": [
            {"speaker": "host", "start": 0, "end": 1, "text": "a"},
        ]}
        field = {"key": "conversation", "type": "audio_dialogue", "span_target": False,
                 "display_options": {"speakers": [], "allow_speaker_assignment": False}}
        html = display_registry.render("audio_dialogue", field, data)
        assert "ad-speaker-btn" not in html
        assert 'name="conversation_speakers"' not in html
        assert "ad-speaker-menu" not in html

    def test_roster_json_and_config_on_root(self):
        html = _render()
        m = re.search(r'data-ad-roster="([^"]+)"', html)
        assert m
        roster = json.loads(m.group(1).replace("&quot;", '"'))
        assert roster["host"]["color"] == "#7c3aed"
        assert roster["host"]["side"] == "left"
        assert "on" in roster["host"]  # contrast color present

    def test_turn_slot_injection(self):
        schemes = [{
            "annotation_type": "radio", "name": "turn_category",
            "description": "Category", "labels": ["claim", "question"],
            "turn_binding": {"field": "conversation"},
        }]
        html = _render(_field(turn_schemes=schemes))
        assert "turn-anno-slot" in html
        assert 'data-ta-schema="turn_category"' in html

    def test_timestamps_are_pseudo_content_data_attr(self):
        # Timestamp is a data attribute (CSS pseudo-content), NOT a text node,
        # so it can't shift span offsets.
        html = _render()
        assert 'class="ad-time" data-time="0:00' in html

    def test_original_text_present_on_turn_text(self):
        html = _render()
        assert 'data-original-text="Welcome back."' in html
        assert 'data-turn-index="0"' in html

    def test_placeholder_when_no_turns(self):
        html = _render(data={"audio": "x", "turns": []})
        assert "ad-placeholder" in html

    def test_unlisted_speaker_gets_deterministic_color(self):
        data = {"turns": [{"speaker": "mystery", "start": 0, "end": 1, "text": "?"}]}
        html = _render(_field(options={"speakers": []}, span_target=False), data)
        # deterministic hash color (not the neutral unassigned grey)
        assert "--ad-color:#" in html
        assert "ad-unassigned" not in html  # it IS assigned (has a speaker)
