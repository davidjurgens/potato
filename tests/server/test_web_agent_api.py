"""
Web Agent Recording API Tests

Tests for the web agent recording API endpoints (/api/web_agent/*).
These verify session lifecycle, step saving, screenshot upload,
and concurrent session handling.
"""

import base64
import json
import os
import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


def _create_authenticated_session(base_url, username="testuser", password="test123"):
    """Create a requests.Session that is registered and logged in."""
    session = requests.Session()
    session.post(
        f"{base_url}/register",
        data={"email": username, "pass": password},
        timeout=5,
    )
    session.post(
        f"{base_url}/auth",
        data={"email": username, "pass": password},
        timeout=5,
    )
    return session


class TestWebAgentAPI:
    """Server-side tests for web agent recording endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask test server with a basic config suitable for web agent testing."""
        test_dir = create_test_directory("web_agent_api_test")

        test_data = [
            {
                "id": "task_001",
                "text": "Find and add a blue wool sweater to the shopping cart",
            },
            {
                "id": "task_002",
                "text": "Search for the nearest Italian restaurant",
            },
            {
                "id": "task_003",
                "text": "Find the current weather forecast",
            },
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "name": "completion_status",
                "annotation_type": "radio",
                "labels": ["completed", "partial", "unable"],
                "description": "Did you successfully complete the task?",
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Web Agent API Test",
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start Flask test server")

        request.cls.base_url = server.base_url
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    # ------------------------------------------------------------------
    # 1. start_session
    # ------------------------------------------------------------------

    def test_start_session_returns_session_id(self):
        """POST /api/web_agent/start_session with url returns 200 and a session_id."""
        session = _create_authenticated_session(self.base_url)

        resp = session.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://example.com"},
            timeout=5,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["status"] == "recording"
        assert len(data["session_id"]) > 0

        # Clean up: end the session
        session.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={"session_id": data["session_id"]},
            timeout=5,
        )

    def test_start_session_requires_auth(self):
        """Unauthenticated POST to /api/web_agent/start_session should redirect to login."""
        raw_session = requests.Session()

        resp = raw_session.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://example.com"},
            timeout=5,
            allow_redirects=False,
        )

        # The _login_required decorator redirects to login page
        assert resp.status_code == 302

    # ------------------------------------------------------------------
    # 2. save_step
    # ------------------------------------------------------------------

    def test_save_step_valid(self):
        """POST /api/web_agent/save_step with valid session and step data returns 200."""
        session = _create_authenticated_session(self.base_url, username="step_user")

        # Start a session first
        start_resp = session.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://example.com"},
            timeout=5,
        )
        session_id = start_resp.json()["session_id"]

        # Save a step
        step_data = {
            "action": "click",
            "target": {"tag": "BUTTON", "text": "Submit"},
            "x": 100,
            "y": 200,
            "timestamp": 1234567890.0,
        }
        resp = session.post(
            f"{self.base_url}/api/web_agent/save_step",
            json={"session_id": session_id, "step": step_data},
            timeout=5,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["step_count"] == 1

        # Clean up
        session.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={"session_id": session_id},
            timeout=5,
        )

    def test_save_step_invalid_session(self):
        """POST /api/web_agent/save_step with a non-existent session_id returns 404."""
        session = _create_authenticated_session(
            self.base_url, username="invalid_sess_user"
        )

        resp = session.post(
            f"{self.base_url}/api/web_agent/save_step",
            json={
                "session_id": "nonexistent_id",
                "step": {"action": "click"},
            },
            timeout=5,
        )

        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data

    def test_save_step_without_session_id(self):
        """POST /api/web_agent/save_step without session_id returns 404.

        The endpoint treats a missing session_id as an empty string,
        which is not found in the sessions dict, yielding 404.
        """
        session = _create_authenticated_session(
            self.base_url, username="no_sessid_user"
        )

        resp = session.post(
            f"{self.base_url}/api/web_agent/save_step",
            json={"step": {"action": "click"}},
            timeout=5,
        )

        # Empty string session_id is not found -> 404
        assert resp.status_code == 404

    # ------------------------------------------------------------------
    # 3. save_screenshot
    # ------------------------------------------------------------------

    def test_save_screenshot_valid(self):
        """POST base64 screenshot data to /api/web_agent/save_screenshot returns 200."""
        session = _create_authenticated_session(
            self.base_url, username="screenshot_user"
        )

        # Start a session
        start_resp = session.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://example.com"},
            timeout=5,
        )
        session_id = start_resp.json()["session_id"]

        # Create a minimal valid PNG (1x1 pixel)
        # PNG header + IHDR + IDAT + IEND
        png_bytes = (
            b"\x89PNG\r\n\x1a\n"  # PNG signature
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde"  # 1x1 RGB
            b"\x00\x00\x00\x0cIDATx"
            b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        b64_data = base64.b64encode(png_bytes).decode("utf-8")

        # session_id and step_index are read from form data or query params,
        # not from the JSON body, so pass them as query parameters.
        resp = session.post(
            f"{self.base_url}/api/web_agent/save_screenshot",
            params={"session_id": session_id, "step_index": "0"},
            json={"screenshot_data": b64_data},
            timeout=5,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "screenshot_url" in data

        # Clean up
        session.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={"session_id": session_id},
            timeout=5,
        )

    # ------------------------------------------------------------------
    # 4. end_session
    # ------------------------------------------------------------------

    def test_end_session_valid(self):
        """POST /api/web_agent/end_session with a valid session returns 200."""
        session = _create_authenticated_session(
            self.base_url, username="end_sess_user"
        )

        # Start a session
        start_resp = session.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://example.com"},
            timeout=5,
        )
        session_id = start_resp.json()["session_id"]

        # End the session
        resp = session.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={"session_id": session_id},
            timeout=5,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "saved"
        assert "trace_path" in data
        assert data["step_count"] == 0  # No steps were saved

    def test_end_session_invalid(self):
        """POST /api/web_agent/end_session with non-existent session returns 404."""
        session = _create_authenticated_session(
            self.base_url, username="end_invalid_user"
        )

        resp = session.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={"session_id": "does_not_exist"},
            timeout=5,
        )

        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data

    # ------------------------------------------------------------------
    # 5. Full lifecycle
    # ------------------------------------------------------------------

    def test_session_lifecycle(self):
        """Full flow: start -> save_step x3 -> end_session, all succeed."""
        session = _create_authenticated_session(
            self.base_url, username="lifecycle_user"
        )

        # Start
        start_resp = session.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://example.com"},
            timeout=5,
        )
        assert start_resp.status_code == 200
        session_id = start_resp.json()["session_id"]

        # Save 3 steps
        for i in range(3):
            step_data = {
                "action": "click",
                "target": {"tag": "A", "text": f"Link {i}"},
                "x": 50 + i * 100,
                "y": 100,
                "timestamp": 1000000.0 + i,
            }
            resp = session.post(
                f"{self.base_url}/api/web_agent/save_step",
                json={"session_id": session_id, "step": step_data},
                timeout=5,
            )
            assert resp.status_code == 200
            assert resp.json()["step_count"] == i + 1

        # End session
        end_resp = session.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={
                "session_id": session_id,
                "task_description": "Test lifecycle task",
            },
            timeout=5,
        )
        assert end_resp.status_code == 200
        data = end_resp.json()
        assert data["status"] == "saved"
        assert data["step_count"] == 3

    def test_save_step_increments_index(self):
        """Saving multiple steps increments the step count correctly."""
        session = _create_authenticated_session(
            self.base_url, username="increment_user"
        )

        start_resp = session.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://example.com"},
            timeout=5,
        )
        session_id = start_resp.json()["session_id"]

        step_counts = []
        for i in range(5):
            resp = session.post(
                f"{self.base_url}/api/web_agent/save_step",
                json={
                    "session_id": session_id,
                    "step": {"action": "type", "text": f"step_{i}"},
                },
                timeout=5,
            )
            assert resp.status_code == 200
            step_counts.append(resp.json()["step_count"])

        assert step_counts == [1, 2, 3, 4, 5]

        # Clean up
        session.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={"session_id": session_id},
            timeout=5,
        )

    def test_end_session_returns_trace_data(self):
        """Completed session returns a trace file path and correct step count."""
        session = _create_authenticated_session(
            self.base_url, username="trace_user"
        )

        start_resp = session.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://example.com/page"},
            timeout=5,
        )
        session_id = start_resp.json()["session_id"]

        # Save 2 steps
        for action in ["click", "type"]:
            session.post(
                f"{self.base_url}/api/web_agent/save_step",
                json={
                    "session_id": session_id,
                    "step": {"action": action, "detail": "test"},
                },
                timeout=5,
            )

        end_resp = session.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={
                "session_id": session_id,
                "task_description": "Find a sweater",
            },
            timeout=5,
        )

        assert end_resp.status_code == 200
        data = end_resp.json()
        assert data["status"] == "saved"
        assert data["step_count"] == 2
        assert "trace_path" in data

        # Verify the trace file was actually written
        trace_path = data["trace_path"]
        assert os.path.exists(trace_path), f"Trace file not found at {trace_path}"

        with open(trace_path, "r") as f:
            trace = json.load(f)

        assert trace["id"] == f"recording_{session_id}"
        assert trace["task_description"] == "Find a sweater"
        assert trace["site"] == "https://example.com/page"
        assert len(trace["steps"]) == 2
        assert trace["steps"][0]["action"] == "click"
        assert trace["steps"][1]["action"] == "type"

    def test_concurrent_sessions(self):
        """Two different users can maintain concurrent recording sessions."""
        session_a = _create_authenticated_session(
            self.base_url, username="concurrent_a"
        )
        session_b = _create_authenticated_session(
            self.base_url, username="concurrent_b"
        )

        # Start sessions for both users
        resp_a = session_a.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://site-a.com"},
            timeout=5,
        )
        assert resp_a.status_code == 200
        sid_a = resp_a.json()["session_id"]

        resp_b = session_b.post(
            f"{self.base_url}/api/web_agent/start_session",
            json={"url": "https://site-b.com"},
            timeout=5,
        )
        assert resp_b.status_code == 200
        sid_b = resp_b.json()["session_id"]

        assert sid_a != sid_b

        # Save steps independently
        resp = session_a.post(
            f"{self.base_url}/api/web_agent/save_step",
            json={"session_id": sid_a, "step": {"action": "click", "owner": "a"}},
            timeout=5,
        )
        assert resp.status_code == 200
        assert resp.json()["step_count"] == 1

        resp = session_b.post(
            f"{self.base_url}/api/web_agent/save_step",
            json={"session_id": sid_b, "step": {"action": "type", "owner": "b"}},
            timeout=5,
        )
        assert resp.status_code == 200
        assert resp.json()["step_count"] == 1

        # Save another step for user B -- should not affect user A's count
        resp = session_b.post(
            f"{self.base_url}/api/web_agent/save_step",
            json={"session_id": sid_b, "step": {"action": "scroll", "owner": "b"}},
            timeout=5,
        )
        assert resp.status_code == 200
        assert resp.json()["step_count"] == 2

        # End both sessions
        end_a = session_a.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={"session_id": sid_a},
            timeout=5,
        )
        assert end_a.status_code == 200
        assert end_a.json()["step_count"] == 1

        end_b = session_b.post(
            f"{self.base_url}/api/web_agent/end_session",
            json={"session_id": sid_b},
            timeout=5,
        )
        assert end_b.status_code == 200
        assert end_b.json()["step_count"] == 2
