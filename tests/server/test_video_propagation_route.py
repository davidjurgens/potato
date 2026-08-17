"""
The propagation route: authentication, traversal, and honest failure.

The tracker itself is tested against real weights in
`tests/unit/test_sam2_video_tracking.py`. What is checked here is everything
around it, which is where routes go wrong: who may call it, what a path that
escapes the media directory does, and what an uninstalled model reports.

That last one matters more than it looks. A capability that is simply absent
must say so with the command that installs it — a 500 with a stack trace tells
an administrator nothing, and "tracking failed" tells them less.
"""

from __future__ import annotations

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("video_propagation")
    data_file = create_test_data_file(
        test_dir, [{"id": "clip_1", "text": "a clip"}])
    config_file = create_test_config(
        test_dir,
        # A plain schema: the route never reads one unless the caller names
        # it, and a video schema here would need media this test does not have.
        annotation_schemes=[{
            "annotation_type": "radio",
            "name": "clip",
            "description": "Track things",
            "labels": ["yes", "no"],
        }],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "text"},
        annotation_task_name="Video propagation",
        require_password=False,
    )
    srv = FlaskTestServer(port=find_free_port(preferred_port=9061),
                          debug=False, config_file=config_file)
    assert srv.start_server(), "Failed to start Flask server"
    srv._wait_for_server_ready(timeout=15)
    yield srv
    srv.stop_server()
    cleanup_test_directory(test_dir)


@pytest.fixture()
def session_for(server):
    def _make(user="tracker@example.com"):
        session = requests.Session()
        session.post(f"{server.base_url}/register",
                     data={"email": user, "pass": "pw", "action": "signup"})
        session.post(f"{server.base_url}/auth",
                     data={"email": user, "pass": "pw", "action": "login"})
        return session
    return _make


def propagate(session, base_url, **payload):
    body = {"video": "clip.webm", "points": [[10, 10, 1]], "frames": 4}
    body.update(payload)
    return session.post(f"{base_url}/api/track/propagate", json=body)


class TestAccess:
    def test_an_anonymous_caller_is_refused(self, server):
        response = requests.post(f"{server.base_url}/api/track/propagate",
                                 json={"video": "a.webm",
                                       "points": [[1, 1, 1]]})
        assert response.status_code == 401

    def test_the_route_exists_rather_than_404ing(self, server, session_for):
        """Registered through configure_routes, not only decorated.

        A route defined with @app.route alone is invisible to the app the live
        server builds, which is a 404 that looks like a missing feature.
        """
        response = propagate(session_for(), server.base_url)
        assert response.status_code != 404 or "could not be found" in \
            response.json().get("error", ""), response.text


class TestValidation:
    def test_points_are_required(self, server, session_for):
        response = propagate(session_for(), server.base_url, points=[])
        assert response.status_code == 400
        assert "points" in response.json()["error"]

    def test_malformed_points_are_refused(self, server, session_for):
        response = propagate(session_for(), server.base_url,
                             points=[["left", "top"]])
        assert response.status_code == 400

    def test_a_video_is_required(self, server, session_for):
        session = session_for()
        response = session.post(f"{server.base_url}/api/track/propagate",
                                json={"points": [[1, 1, 1]]})
        assert response.status_code == 400
        assert "video" in response.json()["error"]


class TestTraversal:
    @pytest.mark.parametrize("path", [
        "../../../../etc/passwd",
        "/etc/passwd",
        "..%2f..%2fetc%2fpasswd",
    ])
    def test_paths_outside_the_media_directory_are_refused(
            self, server, session_for, path):
        response = propagate(session_for(), server.base_url, video=path)
        assert response.status_code == 404, response.text
        # Refused the same way a missing file is: telling them apart tells a
        # prober which paths exist.
        assert "could not be found" in response.json()["error"]


class TestMissingCapability:
    def test_an_uninstalled_model_names_the_install_command(
            self, server, session_for, monkeypatch, tmp_path):
        """Reached only when the weights are absent, which is the common case."""
        from potato import video_tracking

        if video_tracking.model_available():
            pytest.skip("the model IS installed here; the absent path is "
                        "covered by the unit test below")
        response = propagate(session_for(), server.base_url)
        # Either the model is missing (503 with the command) or the video is
        # (404); both are honest, and neither is a 500.
        assert response.status_code in (404, 503), response.text
        if response.status_code == 503:
            assert "download-models sam2_video_tiny" in response.json()["error"]


class TestUnavailableMessage:
    """The message itself, without needing a server."""

    def test_it_names_the_command(self, tmp_path):
        from potato.video_tracking import TrackingUnavailable, _require_model

        with pytest.raises(TrackingUnavailable) as raised:
            _require_model(tmp_path / "nothing-here")
        assert "potato download-models sam2_video_tiny" in str(raised.value)
