"""Server integration tests for /api/codebook and /api/cases."""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)


def _login(server, email):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": email, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": email, "pass": "pw"})
    return s


_CB_SCHEME = [{
    "name": "code", "description": "Codebook scheme",
    "annotation_type": "radio", "codebook": True,
    "labels": ["seed-a", "seed-b"],
}]


class TestCodebookOpenMode:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("codebook_api_open")
        data_file = create_test_data_file(
            test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            test_dir, _CB_SCHEME, data_files=[data_file],
            require_password=False,
            additional_config={"codebook_mode": "open"},
        )
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_requires_auth(self):
        r = requests.get(f"{self.server.base_url}/api/codebook")
        assert r.status_code == 401

    def test_get_seeded_codebook(self):
        s = _login(self.server, "alice")
        r = s.get(f"{self.server.base_url}/api/codebook")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "open"
        assert set(body["labels"]) >= {"seed-a", "seed-b"}
        assert body["can_add"] and body["can_edit"]

    def test_add_rename_delete_cycle(self):
        s = _login(self.server, "bob")
        r = s.post(f"{self.server.base_url}/api/codebook",
                   json={"name": "Runtime Code"})
        assert r.status_code == 200, r.text
        cid = r.json()["code"]["id"]
        # duplicate -> 409
        assert s.post(f"{self.server.base_url}/api/codebook",
                      json={"name": "Runtime Code"}).status_code == 409
        # rename
        r2 = s.request(
            "PATCH", f"{self.server.base_url}/api/codebook/{cid}",
            json={"name": "Renamed"})
        assert r2.status_code == 200
        assert r2.json()["code"]["name"] == "Renamed"
        # delete
        r3 = s.delete(f"{self.server.base_url}/api/codebook/{cid}")
        assert r3.status_code == 200 and r3.json()["deleted"] == 1

    def test_add_empty_name_400(self):
        s = _login(self.server, "carol")
        assert s.post(f"{self.server.base_url}/api/codebook",
                      json={"name": "  "}).status_code == 400


class TestCodebookFixedMode:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("codebook_api_fixed")
        data_file = create_test_data_file(
            test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            test_dir, _CB_SCHEME, data_files=[data_file],
            require_password=False,
            additional_config={"codebook_mode": "fixed"},
        )
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_fixed_mode_blocks_add(self):
        s = _login(self.server, "alice")
        body = s.get(f"{self.server.base_url}/api/codebook").json()
        assert body["mode"] == "fixed"
        assert body["can_add"] is False
        r = s.post(f"{self.server.base_url}/api/codebook",
                   json={"name": "Nope"})
        assert r.status_code == 403


class TestCasesAutoDetect:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("cases_api")
        data_file = create_test_data_file(test_dir, [
            {"id": "1", "text": "a", "participant_id": "P01",
             "condition": "treatment"},
            {"id": "2", "text": "b", "participant_id": "P01"},
            {"id": "3", "text": "c", "participant_id": "P02"},
        ])
        config_file = create_test_config(
            test_dir, [{"name": "l", "description": "d",
                        "annotation_type": "radio", "labels": ["x", "y"]}],
            data_files=[data_file], require_password=False,
            additional_config={
                "cases": {"enabled": True,
                          "attributes": ["condition"]}},
        )
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_requires_auth(self):
        assert requests.get(
            f"{self.server.base_url}/api/cases").status_code == 401

    def test_autodetected_cases_listed(self):
        s = _login(self.server, "alice")
        r = s.get(f"{self.server.base_url}/api/cases")
        assert r.status_code == 200
        names = sorted(c["name"] for c in r.json()["cases"])
        assert names == ["P01", "P02"]

    def test_case_for_instance_with_attributes(self):
        s = _login(self.server, "alice")
        r = s.get(f"{self.server.base_url}/api/cases/instance/1")
        assert r.status_code == 200
        case = r.json()["case"]
        assert case["name"] == "P01"
        assert case["attributes"].get("condition") == "treatment"
