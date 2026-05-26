"""Server integration tests for the universal admin search API."""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)

_SCHEMES = [{
    "name": "label", "description": "L",
    "annotation_type": "radio", "labels": ["a", "b"],
}]
_ADMIN_KEY = "test-admin-key-123"


def _login(server, email):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": email, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": email, "pass": "pw"})
    return s


class TestAdminSearchEnabled:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("search_api_enabled")
        data_file = create_test_data_file(test_dir, [
            {"id": "i1", "text": "the quick brown fox"},
            {"id": "i2", "text": "a rare black swan on the river"},
            {"id": "i3", "text": "quick project deadline"},
        ])
        config_file = create_test_config(
            test_dir, _SCHEMES, data_files=[data_file],
            require_password=False, admin_api_key=_ADMIN_KEY)
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_requires_privilege(self):
        s = _login(self.server, "plain")
        r = s.get(f"{self.server.base_url}/admin/api/search?q=quick")
        assert r.status_code == 403

    def test_admin_key_can_search(self):
        r = requests.get(
            f"{self.server.base_url}/admin/api/search?q=quick",
            headers={"X-API-Key": _ADMIN_KEY})
        assert r.status_code == 200
        ids = {h["instance_id"] for h in r.json()["results"]}
        assert ids == {"i1", "i3"}

    def test_missing_query_is_400(self):
        r = requests.get(f"{self.server.base_url}/admin/api/search",
                          headers={"X-API-Key": _ADMIN_KEY})
        assert r.status_code == 400

    def test_no_match_returns_empty(self):
        r = requests.get(
            f"{self.server.base_url}/admin/api/search?q=zzznotpresent",
            headers={"X-API-Key": _ADMIN_KEY})
        assert r.status_code == 200 and r.json()["count"] == 0

    def test_injection_query_is_harmless(self):
        r = requests.get(
            f"{self.server.base_url}/admin/api/search",
            params={"q": '"; DROP TABLE instance_fts; --'},
            headers={"X-API-Key": _ADMIN_KEY})
        assert r.status_code == 200
        # index still works afterwards
        r2 = requests.get(f"{self.server.base_url}/admin/api/search?q=swan",
                          headers={"X-API-Key": _ADMIN_KEY})
        assert {h["instance_id"] for h in r2.json()["results"]} == {"i2"}


class TestAnnotatorClaim:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("search_claim")
        data_file = create_test_data_file(test_dir, [
            {"id": "i1", "text": "common opening line"},
            {"id": "i2", "text": "a rare black swan candidate"},
            {"id": "i3", "text": "another common line"},
            {"id": "i4", "text": "second rare swan example"},
        ])
        # default assignment is fixed_order, no overlap/QC/crowd ->
        # annotator_claim is allowed by the startup guard.
        # Cap per-user assignments so the corpus isn't all pre-assigned,
        # making claim a meaningful "pull this one in" action.
        config_file = create_test_config(
            test_dir, _SCHEMES, data_files=[data_file],
            require_password=False, max_annotations_per_user=1,
            additional_config={"search": {"annotator_claim": True}})
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_search_requires_auth(self):
        r = requests.get(f"{self.server.base_url}/api/search?q=swan")
        assert r.status_code == 401

    def test_annotator_search_and_claim_flow(self):
        s = _login(self.server, "claimer")
        r = s.get(f"{self.server.base_url}/api/search?q=swan")
        assert r.status_code == 200
        ids = {h["instance_id"] for h in r.json()["results"]}
        assert ids == {"i2", "i4"}

        r = s.post(f"{self.server.base_url}/api/search/claim",
                   json={"instance_id": "i2"})
        assert r.status_code == 200
        body = r.json()
        assert body["claimed"] == "i2" and body["already_assigned"] is False

        # idempotent: second claim reports already assigned
        r = s.post(f"{self.server.base_url}/api/search/claim",
                   json={"instance_id": "i2"})
        assert r.status_code == 200 and r.json()["already_assigned"] is True

    def test_claim_unknown_instance_404(self):
        s = _login(self.server, "claimer2")
        r = s.post(f"{self.server.base_url}/api/search/claim",
                   json={"instance_id": "nope"})
        assert r.status_code == 404

    def test_search_missing_q_400(self):
        s = _login(self.server, "claimer3")
        assert s.get(
            f"{self.server.base_url}/api/search").status_code == 400


class TestAnnotatorClaimDisabledByDefault:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("search_claim_off")
        data_file = create_test_data_file(test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            test_dir, _SCHEMES, data_files=[data_file],
            require_password=False)  # no search.annotator_claim
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_annotator_search_403_when_claim_off(self):
        s = _login(self.server, "u")
        r = s.get(f"{self.server.base_url}/api/search?q=x")
        assert r.status_code == 403
        assert "annotator search-and-claim" in r.json()["error"].lower()

    def test_claim_403_when_off(self):
        s = _login(self.server, "u2")
        r = s.post(f"{self.server.base_url}/api/search/claim",
                   json={"instance_id": "i1"})
        assert r.status_code == 403


class TestSearchDisabled:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("search_api_disabled")
        data_file = create_test_data_file(test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            test_dir, _SCHEMES, data_files=[data_file],
            require_password=False, admin_api_key=_ADMIN_KEY,
            additional_config={"search": {"enabled": False}})
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_disabled_returns_503(self):
        r = requests.get(f"{self.server.base_url}/admin/api/search?q=x",
                          headers={"X-API-Key": _ADMIN_KEY})
        assert r.status_code == 503
        assert "not enabled" in r.json()["error"].lower()
