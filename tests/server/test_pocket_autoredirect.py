"""Integration tests for device auto-routing (phones/tablets → /pocket).

Two real servers: one with a pocket-capable task (radio) where touch devices
must be redirected, and one whose task includes a span scheme (not touch
capable) where they must NOT be redirected and the routing API must say why.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "pocket_autoredirect_admin_key"

IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
             "Mobile/15E148 Safari/604.1")

TEST_ITEMS = [{"id": f"m{i}", "text": f"Mobile test item {i}."}
              for i in range(1, 6)]


def login(base_url, name):
    session = requests.Session()
    user = {"email": name, "pass": "pass"}
    session.post(f"{base_url}/register", data=user, timeout=5)
    response = session.post(f"{base_url}/auth", data=user, timeout=5)
    assert response.status_code in (200, 302)
    session.headers.update({"Origin": base_url})
    return session


class TestAutoRedirectCapableTask:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("pocket_autoredirect")
        create_test_data_file(test_dir, TEST_ITEMS)
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Positive or negative?",
            "labels": ["Positive", "Negative"],
        }]
        config_path = create_test_config(
            test_dir, annotation_schemes, admin_api_key=ADMIN_KEY,
            additional_config={"pocket": {"enabled": True}},
        )
        server = FlaskTestServer(port=9083, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    def test_desktop_ua_not_redirected(self, flask_server):
        session = login(flask_server.base_url, "desk_user")
        response = session.get(f"{flask_server.base_url}/annotate",
                               allow_redirects=False, timeout=5)
        assert response.status_code == 200
        # Desktop users can reach the card-stack UI too: the navbar carries a
        # (JS-revealed) Compact view link pointing at /pocket.
        assert 'id="compact-view-link"' in response.text

    def test_mobile_ua_redirected_to_pocket(self, flask_server):
        session = login(flask_server.base_url, "phone_user")
        response = session.get(f"{flask_server.base_url}/annotate",
                               headers={"User-Agent": IPHONE_UA},
                               allow_redirects=False, timeout=5)
        assert response.status_code == 302
        assert "/pocket" in response.headers["Location"]

    def test_redirected_first_visit_still_gets_items(self, flask_server):
        """A user whose FIRST visit is the redirect must get assignments."""
        session = login(flask_server.base_url, "phone_fresh")
        response = session.get(f"{flask_server.base_url}/annotate",
                               headers={"User-Agent": IPHONE_UA}, timeout=5)
        assert response.status_code == 200  # followed to /pocket
        batch = session.get(f"{flask_server.base_url}/pocket/api/batch",
                            headers={"User-Agent": IPHONE_UA}, timeout=5).json()
        assert batch["items"], "auto-routed user got an empty card stack"

    def test_desktop_optout_is_sticky_until_pocket_visit(self, flask_server):
        session = login(flask_server.base_url, "optout_user")
        # "Desktop site" choice: no redirect despite mobile UA
        response = session.get(f"{flask_server.base_url}/annotate?desktop=1",
                               headers={"User-Agent": IPHONE_UA},
                               allow_redirects=False, timeout=5)
        assert response.status_code == 200
        # ...and it sticks on the next plain visit
        response = session.get(f"{flask_server.base_url}/annotate",
                               headers={"User-Agent": IPHONE_UA},
                               allow_redirects=False, timeout=5)
        assert response.status_code == 200
        # Explicitly opening /pocket clears the choice
        response = session.get(f"{flask_server.base_url}/pocket",
                               headers={"User-Agent": IPHONE_UA}, timeout=5)
        assert response.status_code == 200
        response = session.get(f"{flask_server.base_url}/annotate",
                               headers={"User-Agent": IPHONE_UA},
                               allow_redirects=False, timeout=5)
        assert response.status_code == 302

    def test_routing_api(self, flask_server):
        session = login(flask_server.base_url, "routing_user")
        payload = session.get(f"{flask_server.base_url}/pocket/api/routing",
                              timeout=5).json()
        assert payload == {
            "enabled": True, "capable": True, "auto_redirect": True,
            "available": True, "incompatible_schemes": [],
        }

    def test_device_tracking_and_admin_api(self, flask_server):
        session = login(flask_server.base_url, "tracked_user")
        session.get(f"{flask_server.base_url}/annotate",
                    headers={"User-Agent": IPHONE_UA}, timeout=5)
        # Client-side hint (the iPad-with-desktop-UA path)
        response = session.post(f"{flask_server.base_url}/pocket/api/device_hint",
                                json={"device": "tablet"}, timeout=5)
        assert response.status_code == 200

        # Non-admin is refused
        assert session.get(f"{flask_server.base_url}/pocket/api/devices",
                           timeout=5).status_code == 403
        # Admin key passes
        payload = requests.get(
            f"{flask_server.base_url}/pocket/api/devices",
            headers={"X-API-Key": ADMIN_KEY}, timeout=5).json()
        assert payload["summary"]["n_touch_users"] >= 1
        row = [u for u in payload["users"]
               if u["username"] == "tracked_user"][0]
        assert row["mobile_visits"] >= 1
        assert row["used_touch_device"] is True
        assert payload["routing"]["available"] is True

    def test_nav_posts_never_redirected(self, flask_server):
        """POST /annotate (navigation) must not be device-routed."""
        session = login(flask_server.base_url, "poster_user")
        session.get(f"{flask_server.base_url}/annotate", timeout=5)
        response = session.post(f"{flask_server.base_url}/annotate",
                                data={"action": "next_instance"},
                                headers={"User-Agent": IPHONE_UA},
                                allow_redirects=False, timeout=5)
        assert response.status_code in (200, 302)
        if response.status_code == 302:
            assert "/pocket" not in response.headers.get("Location", "")


class TestNotCapableTask:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("pocket_autoredirect_span")
        create_test_data_file(test_dir, TEST_ITEMS)
        annotation_schemes = [{
            "annotation_type": "span",
            "name": "highlights",
            "description": "Highlight the key phrase",
            "labels": ["Key"],
        }]
        config_path = create_test_config(
            test_dir, annotation_schemes, admin_api_key=ADMIN_KEY,
            additional_config={"pocket": {"enabled": True}},
        )
        server = FlaskTestServer(port=9084, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    def test_mobile_ua_not_redirected_on_span_task(self, flask_server):
        session = login(flask_server.base_url, "span_phone")
        response = session.get(f"{flask_server.base_url}/annotate",
                               headers={"User-Agent": IPHONE_UA},
                               allow_redirects=False, timeout=5)
        assert response.status_code == 200

    def test_routing_reports_not_capable(self, flask_server):
        session = login(flask_server.base_url, "span_router")
        payload = session.get(f"{flask_server.base_url}/pocket/api/routing",
                              timeout=5).json()
        assert payload["capable"] is False
        assert payload["available"] is False
        assert "highlights" in payload["incompatible_schemes"]

    def test_visits_still_tracked_for_admin(self, flask_server):
        session = login(flask_server.base_url, "span_tracked")
        session.get(f"{flask_server.base_url}/annotate",
                    headers={"User-Agent": IPHONE_UA}, timeout=5)
        payload = requests.get(
            f"{flask_server.base_url}/pocket/api/devices",
            headers={"X-API-Key": ADMIN_KEY}, timeout=5).json()
        row = [u for u in payload["users"]
               if u["username"] == "span_tracked"][0]
        assert row["mobile_visits"] >= 1
