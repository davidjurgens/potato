"""
Server integration tests for the audio_dialogue display.

Boots the shipped example (examples/audio/audio-dialogue) with a real Flask
instance and verifies:
  * the annotate page renders speaker bubbles, the audio element, per-turn play
    buttons, turn-level slots, and the span/link schemes,
  * per-turn ratings (turn_category :::_data) round-trip through /updateinstance
    and are restored into the hidden input on re-render,
  * speaker assignment ({field}_speakers :::_data) round-trips on the undiarized
    instance,
  * spans (span_annotations) and cross-turn links (link_annotations) round-trip
    via /get_annotations and /api/links.
"""

import json
import os
import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer


def _project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


EXAMPLE_CONFIG = os.path.join(
    _project_root(), "examples/audio/audio-dialogue/config.yaml"
)


@pytest.fixture(scope="module")
def server():
    srv = FlaskTestServer(config=EXAMPLE_CONFIG)
    if not srv.start():
        pytest.fail("Failed to start audio-dialogue example server")
    yield srv
    srv.stop()


def _register(server, username):
    session = requests.Session()
    session.post(
        f"{server.base_url}/register",
        data={"action": "signup", "email": username, "pass": "pass"},
        timeout=10,
    )
    return session


def _annotate_html(session, server):
    r = session.get(f"{server.base_url}/annotate", timeout=10)
    assert r.status_code == 200
    return r.text


def _post(session, server, payload):
    r = session.post(f"{server.base_url}/updateinstance", json=payload, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") != "error", body
    return body


class TestRender:
    def test_page_renders_display(self, server):
        session = _register(server, "ad_render")
        html = _annotate_html(session, server)
        assert 'class="audio-dialogue"' in html
        assert "ad-audio-conversation" in html
        assert 'class="ad-play"' in html
        assert "text-content-conversation" in html

    def test_page_has_turn_slots_and_schemes(self, server):
        session = _register(server, "ad_schemes")
        html = _annotate_html(session, server)
        assert "turn-anno-slot" in html
        assert 'data-ta-schema="turn_category"' in html
        # span + span_link + likert schemes present in the form area
        assert "qa_links" in html
        assert "overall_quality" in html

    def test_assets_loaded(self, server):
        session = _register(server, "ad_assets")
        html = _annotate_html(session, server)
        assert "audio-dialogue.css" in html
        assert "audio-dialogue.js" in html


class TestPerTurnRatingRoundTrip:
    def test_turn_category_persists_and_restores(self, server):
        session = _register(server, "ad_rating")
        _annotate_html(session, server)

        value = json.dumps({
            "v": 1, "schema_type": "radio",
            "turns": {"t2": {"value": "question", "speaker": "host"}},
        })
        _post(session, server, {
            "instance_id": "ep_001",
            "annotations": {"turn_category:::_data": value},
            "span_annotations": [],
        })

        # /get_annotations shows the schema is stored
        r = session.get(f"{server.base_url}/get_annotations",
                        params={"instance_id": "ep_001"}, timeout=10)
        assert r.status_code == 200
        labels = r.json().get("label_annotations", {})
        assert "turn_category" in labels

        # Re-render restores the exact value into the hidden input (BeautifulSoup
        # path sets value + data-server-set).
        html = _annotate_html(session, server)
        hidden = re.search(
            r'<input[^>]*id="turn-anno-turn_category"[^>]*>', html)
        assert hidden, "turn_category hidden input missing"
        tag = hidden.group(0)
        assert 'data-server-set="true"' in tag
        assert "question" in tag  # the stored value is echoed into value=


class TestSpeakerAssignmentRoundTrip:
    def test_speaker_assignment_persists_on_undiarized_instance(self, server):
        session = _register(server, "ad_speaker")
        _annotate_html(session, server)

        value = json.dumps({
            "v": 1, "schema_type": "speaker_assignment",
            "turns": {"t0": {"speaker": "host"}, "t2": {"speaker": "guest"}},
        })
        _post(session, server, {
            "instance_id": "ep_002",
            "annotations": {"conversation_speakers:::_data": value},
            "span_annotations": [],
        })

        r = session.get(f"{server.base_url}/get_annotations",
                        params={"instance_id": "ep_002"}, timeout=10)
        labels = r.json().get("label_annotations", {})
        assert "conversation_speakers" in labels


class TestSpanAndLinkRoundTrip:
    def test_span_persists(self, server):
        session = _register(server, "ad_span")
        _annotate_html(session, server)

        _post(session, server, {
            "instance_id": "ep_001",
            "annotations": {},
            "span_annotations": [{
                "schema": "highlights", "name": "question",
                "title": "question", "start": 5, "end": 20,
                "target_field": "conversation", "value": "question",
                "id": "hl_q_1",
            }],
        })

        r = session.get(f"{server.base_url}/get_annotations",
                        params={"instance_id": "ep_001"}, timeout=10)
        spans = r.json().get("span_annotations", {})
        assert spans, "no span stored"
        assert any(v == "question" for v in spans.values())

    def test_cross_turn_link_persists(self, server):
        session = _register(server, "ad_link")
        _annotate_html(session, server)

        # Two spans (a question in one turn, an answer in another) then a
        # directed link answer -> question.
        _post(session, server, {
            "instance_id": "ep_001",
            "annotations": {},
            "span_annotations": [
                {"schema": "highlights", "name": "question", "title": "question",
                 "start": 5, "end": 20, "target_field": "conversation",
                 "value": "question", "id": "q1"},
                {"schema": "highlights", "name": "answer", "title": "answer",
                 "start": 60, "end": 80, "target_field": "conversation",
                 "value": "answer", "id": "a1"},
            ],
        })
        _post(session, server, {
            "instance_id": "ep_001",
            "annotations": {},
            "link_annotations": [{
                "id": "lnk1", "schema": "qa_links", "link_type": "answers",
                "span_ids": ["a1", "q1"], "direction": "directed",
                "properties": {},
            }],
        })

        r = session.get(f"{server.base_url}/api/links/ep_001", timeout=10)
        assert r.status_code == 200
        links = r.json()
        # endpoint may return a list or {"links": [...]}
        link_list = links.get("links", links) if isinstance(links, dict) else links
        assert link_list, f"no links returned: {links}"
        blob = json.dumps(link_list)
        assert "qa_links" in blob and "answers" in blob
        assert "a1" in blob and "q1" in blob
