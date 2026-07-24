"""Integration tests for the Think-Aloud API (/thinkaloud/*).

Uses the mock STT backend (config ``thinkaloud.stt: mock``) so no audio stack
is required: the chunk endpoint echoes the ``mock_text`` form field, and the
text endpoint bypasses audio entirely.
"""

import io

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "thinkaloud_test_admin_key"

TEST_ITEMS = [
    {"id": "m1", "text": "Send me the slides before the meeting."},
    {"id": "m2", "text": "Per my last email, the deadline was Friday."},
]


class TestThinkAloudAPI:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("thinkaloud_api")
        create_test_data_file(test_dir, TEST_ITEMS)
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "politeness",
            "description": "How polite?",
            "labels": ["Polite", "Neutral", "Impolite"],
        }]
        config_path = create_test_config(
            test_dir,
            annotation_schemes,
            admin_api_key=ADMIN_KEY,
            additional_config={
                "thinkaloud": {
                    "enabled": True,
                    "schema": "politeness",
                    "stt": "mock",
                },
            },
        )
        server = FlaskTestServer(port=9079, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    @pytest.fixture()
    def authed_session(self, flask_server):
        session = requests.Session()
        user = {"email": "ta_user", "pass": "pass"}
        session.post(f"{flask_server.base_url}/register", data=user, timeout=5)
        response = session.post(f"{flask_server.base_url}/auth", data=user, timeout=5)
        assert response.status_code in (200, 302)
        session.headers.update({"Origin": flask_server.base_url})
        return session

    def _text(self, flask_server, session, instance_id, seq, text):
        return session.post(
            f"{flask_server.base_url}/thinkaloud/api/text",
            json={"instance_id": instance_id, "seq": seq, "text": text},
            timeout=5,
        )

    # ------------------------------------------------------------- auth ----
    def test_text_requires_login(self, flask_server):
        response = requests.post(
            f"{flask_server.base_url}/thinkaloud/api/text",
            json={"instance_id": "m1", "seq": 0, "text": "x"},
            timeout=5,
        )
        assert response.status_code == 401

    def test_export_requires_admin(self, flask_server, authed_session):
        response = authed_session.get(
            f"{flask_server.base_url}/thinkaloud/api/export", timeout=5)
        assert response.status_code == 403

    # -------------------------------------------------------------- text ----
    def test_free_speech_then_label_phrase(self, flask_server, authed_session):
        r1 = self._text(flask_server, authed_session, "m1", 0,
                        "okay this is a bare command no please no greeting")
        assert r1.status_code == 200
        assert r1.json()["detection"] is None

        r2 = self._text(flask_server, authed_session, "m1", 1,
                        "so um I label this impolite")
        detection = r2.json()["detection"]
        assert detection["label"] == "Impolite"
        assert "label this" in detection["stem_text"]

    def test_phrase_straddling_chunks(self, flask_server, authed_session):
        self._text(flask_server, authed_session, "m2", 0,
                   "hmm passive aggressive but formal, my answer")
        r = self._text(flask_server, authed_session, "m2", 1, "is neutral")
        assert r.json()["detection"]["label"] == "Neutral"

    def test_state_aggregates_session(self, flask_server, authed_session):
        response = authed_session.get(
            f"{flask_server.base_url}/thinkaloud/api/state",
            params={"instance_id": "m1"}, timeout=5)
        state = response.json()
        assert state["detection"]["label"] == "Impolite"
        assert state["n_chunks"] >= 2
        assert state["filler_count"] >= 1  # the "um"
        assert "bare command" in state["transcript"]
        # Rationale keeps the thinking, drops the label phrase
        assert "impolite" not in state["rationale"]
        assert "bare command" in state["rationale"]

    def test_text_validation(self, flask_server, authed_session):
        response = authed_session.post(
            f"{flask_server.base_url}/thinkaloud/api/text",
            json={"instance_id": "m1", "seq": "zero", "text": "x"},
            timeout=5,
        )
        assert response.status_code == 400

    # ------------------------------------------------------------- audio ----
    def test_chunk_endpoint_with_mock_backend(self, flask_server, authed_session):
        response = authed_session.post(
            f"{flask_server.base_url}/thinkaloud/api/chunk",
            data={"instance_id": "m1", "seq": "10",
                  "mock_text": "final answer impolite"},
            files={"audio": ("chunk.webm", io.BytesIO(b"fake-bytes"), "audio/webm")},
            timeout=5,
        )
        assert response.status_code == 200
        assert response.json()["detection"]["label"] == "Impolite"

    def test_chunk_requires_audio_file(self, flask_server, authed_session):
        response = authed_session.post(
            f"{flask_server.base_url}/thinkaloud/api/chunk",
            data={"instance_id": "m1", "seq": "11"},
            timeout=5,
        )
        assert response.status_code == 400

    # ------------------------------------------------------------- admin ----
    def test_export_with_admin_key(self, flask_server):
        response = requests.get(
            f"{flask_server.base_url}/thinkaloud/api/export",
            headers={"X-API-Key": ADMIN_KEY}, timeout=5)
        assert response.status_code == 200
        sessions = response.json()["sessions"]
        assert any(s["instance_id"] == "m1" and s["detection"] for s in sessions)

    def test_review_page_with_admin_key(self, flask_server):
        response = requests.get(
            f"{flask_server.base_url}/thinkaloud/review",
            headers={"X-API-Key": ADMIN_KEY}, timeout=5)
        assert response.status_code == 200
        assert "Think-Aloud Review" in response.text
