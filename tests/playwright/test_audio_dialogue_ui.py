"""
Playwright UI tests for the audio_dialogue display.

Covers the interactive behaviors that can only be verified in a real browser:
  * per-turn ▶ playback seeks to the turn start and auto-stops at its end,
  * the active turn is highlighted during playback,
  * speaker assignment on an undiarized turn recolors/repositions the bubble and
    PERSISTS across navigate-away-and-back (verified visually + via the API),
  * a per-turn rating persists across navigate-away-and-back.

Uses a small bundled WAV embedded as a data: URI (Chromium plays wav; no network,
no media route needed). Follows the memory rule: verify persistence by
navigating away and back, never by page refresh.

Run:  pytest tests/playwright/test_audio_dialogue_ui.py -v
"""

import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
)
from tests.playwright.test_base import BasePlaywrightTest


def _audio_data_uri():
    wav = os.path.join(os.path.dirname(__file__), "assets", "test_dialogue_8s.wav")
    with open(wav, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return "data:audio/wav;base64," + b64


@pytest.fixture(scope="module")
def ad_server():
    test_dir = create_test_directory("pw_audio_dialogue")
    audio = _audio_data_uri()
    data = [
        {
            "id": "ad_001",
            "title": "Diarized episode",
            "conversation": {
                "audio": audio,
                "turns": [
                    {"turn_id": "t0", "speaker": "host", "start": 0.0, "end": 2.0, "text": "Welcome to the show everyone."},
                    {"turn_id": "t1", "speaker": "guest", "start": 2.0, "end": 4.0, "text": "Thanks, glad to be here today."},
                    {"turn_id": "t2", "speaker": "host", "start": 4.0, "end": 6.0, "text": "Let us start with a question."},
                ],
            },
        },
        {
            "id": "ad_002",
            "title": "Undiarized episode",
            "conversation": {
                "audio": audio,
                "turns": [
                    {"turn_id": "t0", "start": 0.0, "end": 2.0, "text": "Alright, opening the roundtable now."},
                    {"turn_id": "t1", "start": 2.0, "end": 4.0, "text": "I think remote work is here to stay."},
                ],
            },
        },
    ]
    data_file = create_test_data_file(test_dir, data, filename="ad_data.jsonl")

    schemes = [
        {
            "annotation_type": "radio",
            "name": "turn_category",
            "description": "Category of this turn",
            "labels": ["claim", "question", "answer", "aside"],
            "turn_level": True,
            "turn_binding": {"field": "conversation"},
        },
        {
            "annotation_type": "likert",
            "name": "overall_quality",
            "description": "Overall quality",
            "size": 5,
            "min_label": "Poor",
            "max_label": "Excellent",
        },
    ]
    instance_display = {
        "layout": {"direction": "vertical", "gap": "12px"},
        "fields": [
            {"key": "title", "type": "text", "label": "Episode"},
            {
                "key": "conversation",
                "type": "audio_dialogue",
                "label": "Transcript",
                "span_target": True,
                "display_options": {
                    "scroll_height": "400px",
                    "speakers": [
                        {"id": "host", "name": "Host", "color": "#7c3aed", "side": "left"},
                        {"id": "guest", "name": "Guest", "color": "#059669", "side": "right"},
                    ],
                },
            },
        ],
    }
    config_file = create_test_config(
        test_dir,
        schemes,
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "title"},
        additional_config={"instance_display": instance_display},
    )
    srv = FlaskTestServer(port=find_free_port(), debug=False, config_file=config_file)
    if not srv.start():
        pytest.fail("Failed to start audio_dialogue Playwright server")
    yield srv
    srv.stop()


@pytest.mark.playwright
class TestAudioDialogueUI(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_selector(".audio-dialogue", timeout=15000)

    def _wait_audio_ready(self, page):
        page.wait_for_function(
            """() => {
                const a = document.querySelector('.ad-audio');
                return a && a.readyState >= 1 && a.duration > 0;
            }""",
            timeout=10000,
        )

    # ---- per-turn playback ----

    def test_per_turn_play_seeks_and_stops(self, page, ad_server):
        self._open(page, ad_server)
        self._wait_audio_ready(page)

        # Click the second turn's ▶ (start=2, end=4)
        btns = page.query_selector_all(".ad-play")
        assert len(btns) >= 2
        btns[1].click()

        # Seeks to the turn start
        page.wait_for_function(
            "() => Math.abs(document.querySelector('.ad-audio').currentTime - 2.0) < 0.6",
            timeout=4000,
        )

        # Drive time past the turn end -> the handler pauses at the boundary.
        paused = page.evaluate(
            """() => {
                const a = document.querySelector('.ad-audio');
                a.currentTime = 4.1;
                a.dispatchEvent(new Event('timeupdate'));
                return a.paused;
            }"""
        )
        assert paused is True

    def test_active_turn_highlight(self, page, ad_server):
        self._open(page, ad_server)
        self._wait_audio_ready(page)
        # Position inside turn 2 [2,4] and fire timeupdate.
        active_idx = page.evaluate(
            """() => {
                const a = document.querySelector('.ad-audio');
                a.currentTime = 3.0;
                a.dispatchEvent(new Event('timeupdate'));
                const turns = [...document.querySelectorAll('.ad-turn')];
                return turns.findIndex(t => t.classList.contains('ad-active'));
            }"""
        )
        assert active_idx == 1

    # ---- speaker assignment persistence ----

    def _assign_via_menu(self, page, turn_selector, speaker_name):
        """Click a turn's speaker button, then pick a speaker from the popover."""
        page.click(turn_selector + " .ad-speaker-btn")
        page.wait_for_selector(".ad-speaker-menu:not([hidden])", timeout=4000)
        page.click(f'.ad-speaker-menu .ad-menu-item:has-text("{speaker_name}")')

    def test_speaker_assignment_persists_nav_away_back(self, page, ad_server):
        self._open(page, ad_server)
        # Go to the undiarized instance (ad_002)
        page.click("#next-btn")
        page.wait_for_selector(".ad-turn .ad-speaker-btn", timeout=10000)

        # Assign the first turn to "host" via the click menu
        self._assign_via_menu(page, ".ad-turn:nth-of-type(1)", "Host")
        # bubble becomes assigned
        page.wait_for_function(
            """() => {
                const t = document.querySelector('.ad-turn');
                return t.getAttribute('data-speaker') === 'host'
                    && t.classList.contains('ad-assigned');
            }""",
            timeout=4000,
        )
        page.wait_for_timeout(900)  # allow debounced save

        # Server-side check
        anns = self.verify_server_annotations(page, ad_server, "ad_002")
        assert "conversation_speakers" in anns.get("label_annotations", {}), anns

        # Navigate away and back — NOT a refresh (memory rule).
        page.click("#prev-btn")
        page.wait_for_selector(".audio-dialogue", timeout=10000)
        page.click("#next-btn")
        page.wait_for_selector(".ad-turn", timeout=10000)

        # Give the display JS time to re-seed from the restored hidden input and
        # repaint. The first turn's picker is now hidden (assigned), so we assert
        # the bubble state directly rather than waiting on picker visibility.
        page.wait_for_function(
            """() => {
                const t = document.querySelector('.ad-turn');
                return t && t.getAttribute('data-speaker') === 'host';
            }""",
            timeout=8000,
        )

        # Visual state restored: first turn still Host, recolored, picker hidden.
        restored = page.evaluate(
            """() => {
                const t = document.querySelector('.ad-turn');
                return {
                    speaker: t.getAttribute('data-speaker'),
                    assigned: t.classList.contains('ad-assigned'),
                    color: t.style.getPropertyValue('--ad-color').trim(),
                    name: t.querySelector('.ad-speaker-name').getAttribute('data-name'),
                };
            }"""
        )
        assert restored["speaker"] == "host"
        assert restored["assigned"] is True
        assert restored["color"] == "#7c3aed"
        assert restored["name"] == "Host"

    def test_reassign_diarized_turn(self, page, ad_server):
        # ad_001 turn 1 is diarized as Host; the annotator can correct it.
        self._open(page, ad_server)
        page.wait_for_selector(".ad-turn .ad-speaker-btn", timeout=10000)
        assert page.evaluate(
            "() => document.querySelector('.ad-turn').getAttribute('data-speaker')") == "host"

        self._assign_via_menu(page, ".ad-turn:nth-of-type(1)", "Guest")
        page.wait_for_function(
            """() => {
                const t = document.querySelector('.ad-turn');
                return t.getAttribute('data-speaker') === 'guest'
                    && t.classList.contains('ad-side-right')
                    && t.style.getPropertyValue('--ad-color').trim() === '#059669';
            }""",
            timeout=4000,
        )

    def test_add_new_speaker(self, page, ad_server):
        # No fixed speaker count: the annotator adds a label on the fly.
        self._open(page, ad_server)
        page.click("#next-btn")  # undiarized instance
        page.wait_for_selector(".ad-turn .ad-speaker-btn", timeout=10000)

        page.once("dialog", lambda d: d.accept("Narrator"))
        page.click(".ad-turn:nth-of-type(1) .ad-speaker-btn")
        page.wait_for_selector(".ad-speaker-menu:not([hidden])", timeout=4000)
        page.click('.ad-speaker-menu .ad-menu-add')

        # The turn is now assigned to the new speaker
        page.wait_for_function(
            """() => {
                const t = document.querySelector('.ad-turn');
                return t.getAttribute('data-speaker') === 'Narrator'
                    && t.classList.contains('ad-assigned')
                    && t.querySelector('.ad-speaker-name').getAttribute('data-name') === 'Narrator';
            }""",
            timeout=4000,
        )
        # The new speaker is now offered in the menu for other turns
        page.click(".ad-turn:nth-of-type(2) .ad-speaker-btn")
        page.wait_for_selector(".ad-speaker-menu:not([hidden])", timeout=4000)
        assert page.query_selector('.ad-speaker-menu .ad-menu-item:has-text("Narrator")')

    # ---- per-turn rating persistence ----

    def test_turn_rating_persists_nav_away_back(self, page, ad_server):
        self._open(page, ad_server)
        # Click "question" chip on the first turn (turn t0)
        chip = page.query_selector(
            '.ta-chip[data-ta-schema="turn_category"][data-turn-id="t0"][data-value="question"]'
        )
        assert chip, "turn_category chip not found"
        chip.click()
        page.wait_for_function(
            """() => {
                const c = document.querySelector('.ta-chip[data-ta-schema="turn_category"][data-turn-id="t0"][data-value="question"]');
                return c && c.classList.contains('ta-selected');
            }""",
            timeout=4000,
        )
        page.wait_for_timeout(900)  # debounced save

        anns = self.verify_server_annotations(page, ad_server, "ad_001")
        assert "turn_category" in anns.get("label_annotations", {})

        # Navigate away and back
        page.click("#next-btn")
        page.wait_for_selector(".audio-dialogue", timeout=10000)
        page.click("#prev-btn")
        page.wait_for_selector(".audio-dialogue", timeout=10000)

        # Chip is still selected (restored from server _data)
        page.wait_for_function(
            """() => {
                const c = document.querySelector('.ta-chip[data-ta-schema="turn_category"][data-turn-id="t0"][data-value="question"]');
                return c && c.classList.contains('ta-selected');
            }""",
            timeout=6000,
        )
