"""
Reaching the admin analysis pages from a browser.

Before the 2026-10-08 audit fixes a researcher who typed ``/admin/iaa`` got a
wall of JSON (the page needed ``?format=html``), the dashboard linked to none
of the analysis pages, and the Logout button left the admin key in the
session. These run against a live server because the behaviour is in content
negotiation and session handling, which a mocked request does not exercise.
"""

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

ADMIN_KEY = "iaa-negotiation-key"
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("admin_iaa_negotiation")
    data = [{"id": f"item_{i}", "text": f"text {i}"} for i in range(3)]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Sentiment?",
            "labels": ["positive", "negative"],
        }],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "text"},
        annotation_task_name="IAA negotiation",
        require_password=False,
        admin_api_key=ADMIN_KEY,
        adjudication={"enabled": True, "adjudicator_users": ["adj"]},
    )
    srv = FlaskTestServer(port=find_free_port(preferred_port=9214),
                          debug=False, config_file=config_file)
    assert srv.start_server(), "Failed to start Flask server"
    srv._wait_for_server_ready(timeout=15)
    yield srv
    srv.stop_server()
    cleanup_test_directory(test_dir)


def _admin_session(server):
    """A browser session that signed in through the /admin key form."""
    s = requests.Session()
    r = s.get(f"{server.base_url}/admin", headers={"X-API-Key": ADMIN_KEY})
    assert r.status_code == 200 and "admin-tabs" in r.text
    return s


class TestIaaContentNegotiation:
    def test_browser_navigation_gets_the_page(self, server):
        r = requests.get(f"{server.base_url}/admin/iaa",
                         headers={"X-API-Key": ADMIN_KEY, "Accept": BROWSER_ACCEPT})
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("text/html")

    def test_api_clients_still_get_json(self, server):
        for accept in (None, "*/*", "application/json"):
            headers = {"X-API-Key": ADMIN_KEY}
            if accept:
                headers["Accept"] = accept
            r = requests.get(f"{server.base_url}/admin/iaa", headers=headers)
            assert r.headers["Content-Type"].startswith("application/json"), accept
            assert "schemas" in r.json()

    def test_explicit_format_overrides_accept(self, server):
        r = requests.get(f"{server.base_url}/admin/iaa?format=json",
                         headers={"X-API-Key": ADMIN_KEY, "Accept": BROWSER_ACCEPT})
        assert r.headers["Content-Type"].startswith("application/json")
        r = requests.get(f"{server.base_url}/admin/iaa?format=html",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.headers["Content-Type"].startswith("text/html")

    def test_session_from_the_key_form_opens_the_page(self, server):
        s = _admin_session(server)
        r = s.get(f"{server.base_url}/admin/iaa", headers={"Accept": BROWSER_ACCEPT})
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("text/html")

    def test_no_key_no_session_is_refused(self, server):
        r = requests.get(f"{server.base_url}/admin/iaa", headers={"Accept": BROWSER_ACCEPT})
        assert r.status_code == 403


class TestAgreementSummary:
    def test_summary_has_a_row_per_schema(self, server):
        r = requests.get(f"{server.base_url}/admin/api/iaa_summary",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200
        body = r.json()
        assert [row["schema"] for row in body["schemas"]] == ["sentiment"]
        assert "n_overlap_items" in body

    def test_summary_requires_admin(self, server):
        r = requests.get(f"{server.base_url}/admin/api/iaa_summary")
        assert r.status_code == 403


class TestDashboardLinksAndLogout:
    def test_dashboard_links_enabled_analysis_pages(self, server):
        page = _admin_session(server).get(f"{server.base_url}/admin").text
        assert 'href="/admin/iaa"' in page
        assert 'href="/adjudicate"' in page
        # Not enabled in this config, so not linked.
        assert 'href="/admin/review"' not in page
        assert 'href="/admin/triage-queue"' not in page

    def test_logout_drops_the_admin_key(self, server):
        s = _admin_session(server)
        assert s.get(f"{server.base_url}/admin/api/overview").status_code == 200
        assert s.post(f"{server.base_url}/admin/logout").status_code == 200
        assert s.get(f"{server.base_url}/admin/api/overview").status_code == 403
        page = s.get(f"{server.base_url}/admin").text
        assert 'id="apiKey"' in page

    def test_wrong_key_is_refused_so_the_form_can_say_so(self, server):
        """The key form checks response.ok; a 200 hid every wrong key."""
        r = requests.get(f"{server.base_url}/admin", headers={"X-API-Key": "not-the-key"})
        assert r.status_code == 403
        assert 'id="apiKey"' in r.text
        # Plain navigation with no key is the form, not an error.
        assert requests.get(f"{server.base_url}/admin").status_code == 200

    def test_login_page_names_the_inline_config_key(self, server):
        page = requests.get(f"{server.base_url}/admin").text
        assert "<code>admin_api_key</code> value in this project's config file" in page
        assert "admin_api_key.txt" not in page


class TestAnalysisPagesShareTheHeader:
    """The pages the dashboard links to had their own header or none, and
    four of the five had no way back to the dashboard."""

    @pytest.mark.parametrize("path", [
        "/admin/iaa", "/admin/annotation-integrity", "/admin/triage-queue",
        "/admin/judge-alignment",
    ])
    def test_page_has_the_admin_bar_and_a_way_back(self, server, path):
        from bs4 import BeautifulSoup

        r = _admin_session(server).get(f"{server.base_url}{path}",
                                       headers={"Accept": BROWSER_ACCEPT})
        assert r.status_code == 200, path
        soup = BeautifulSoup(r.text, "html.parser")
        bar = soup.select_one("nav.potato-navbar.admin-navbar")
        assert bar is not None, f"{path} has no admin bar"
        assert "IAA negotiation" in bar.get_text()
        back = bar.select_one("a.admin-back-link")
        assert back is not None and back["href"].endswith("/admin")
        follow = requests.get(server.base_url + back["href"],
                              headers={"X-API-Key": ADMIN_KEY})
        assert follow.status_code == 200 and "admin-tabs" in follow.text
