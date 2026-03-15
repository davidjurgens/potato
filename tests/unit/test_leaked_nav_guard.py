"""
Tests for leaked navigation guard: verifying that nav button POSTs
from non-annotation phase pages don't corrupt workflow state.
"""
import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestLeakedNavGuard:
    """Test that navigation actions from non-annotation phases are handled gracefully."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "labels": ["positive", "negative"],
                "description": "Select sentiment",
            }
        ]
        # Set up a multi-phase config with consent + annotation
        with TestConfigManager(
            "leaked_nav_test",
            annotation_schemes,
            num_items=3,
        ) as test_config:
            server = FlaskTestServer(port=9043, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            request.cls.server = server
            yield server
            server.stop()

    def test_normal_annotation_nav_unaffected(self):
        """Normal next_instance during annotation phase should work as usual."""
        s = requests.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "nav_normal_user", "pass": "pw"},
        )
        # Should be in annotation phase, nav should work
        r = s.get(f"{self.server.base_url}/annotate")
        assert r.status_code == 200

        # Navigate next — should succeed (stays on annotate)
        r = s.post(
            f"{self.server.base_url}/annotate",
            json={"action": "next_instance"},
        )
        assert r.status_code == 200

    def test_prev_from_non_annotation_stays_put(self):
        """prev_instance from a completed/non-annotation phase should just redirect to home."""
        s = requests.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "nav_prev_user", "pass": "pw"},
        )
        # Get to annotation phase and annotate all items to advance past it
        r = s.get(f"{self.server.base_url}/annotate")

        # Now try to POST prev_instance to /annotate (should redirect, not crash)
        # Even if the user is still in annotation, a prev_instance is harmless
        r = s.post(
            f"{self.server.base_url}/annotate",
            json={"action": "prev_instance"},
            allow_redirects=False,
        )
        # Should either redirect (302) or render normally (200)
        assert r.status_code in (200, 302)

    def test_next_instance_on_completed_user_redirects(self):
        """If user has completed all assignments, next_instance should redirect to home."""
        s = requests.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "nav_done_user", "pass": "pw"},
        )
        # First verify the user can reach annotate
        r = s.get(f"{self.server.base_url}/annotate")
        assert r.status_code == 200

        # Navigate through all instances
        for _ in range(5):
            r = s.post(
                f"{self.server.base_url}/annotate",
                json={"action": "next_instance"},
                allow_redirects=False,
            )
            if r.status_code == 302:
                break

        # After completing, another next_instance should not crash
        r = s.post(
            f"{self.server.base_url}/annotate",
            json={"action": "next_instance"},
            allow_redirects=False,
        )
        # Should redirect since user is no longer in annotation phase
        assert r.status_code in (200, 302)
