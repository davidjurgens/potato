"""Server integration tests for the universal Memos API (/api/memos)."""

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


def _login(server, email):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": email, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": email, "pass": "pw"})
    return s


class TestMemosEnabled:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("memos_api_enabled")
        data_file = create_test_data_file(
            test_dir, [{"id": "i1", "text": "hello world"},
                       {"id": "i2", "text": "second"}])
        config_file = create_test_config(
            test_dir, _SCHEMES, data_files=[data_file],
            require_password=False,
            additional_config={"annotation_ui": {"memos": True}},
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
        r = requests.get(f"{self.server.base_url}/api/memos?instance_id=i1")
        assert r.status_code == 401

    def test_create_list_patch_delete(self):
        s = _login(self.server, "alice")
        # missing instance_id -> 400
        assert s.post(f"{self.server.base_url}/api/memos",
                      json={"body": "x"}).status_code == 400
        # create
        r = s.post(f"{self.server.base_url}/api/memos",
                   json={"instance_id": "i1", "body": "interesting case"})
        assert r.status_code == 200
        mid = r.json()["memo"]["id"]
        assert r.json()["memo"]["visibility"] == "private"
        # list
        r = s.get(f"{self.server.base_url}/api/memos?instance_id=i1")
        assert r.status_code == 200 and len(r.json()["memos"]) == 1
        # patch
        r = s.patch(f"{self.server.base_url}/api/memos/{mid}",
                    json={"body": "edited", "visibility": "shared"})
        assert r.status_code == 200 and r.json()["memo"]["body"] == "edited"
        # delete
        assert s.delete(
            f"{self.server.base_url}/api/memos/{mid}").status_code == 200
        assert s.get(
            f"{self.server.base_url}/api/memos?instance_id=i1"
        ).json()["memos"] == []

    def test_patch_missing_is_404(self):
        s = _login(self.server, "alice2")
        assert s.patch(f"{self.server.base_url}/api/memos/nope",
                       json={"body": "y"}).status_code == 404

    def test_visibility_isolation_between_users(self):
        alice = _login(self.server, "vis_alice")
        bob = _login(self.server, "vis_bob")
        # alice private memo on i2
        alice.post(f"{self.server.base_url}/api/memos",
                   json={"instance_id": "i2", "body": "priv"})
        # alice shared memo on i2
        alice.post(f"{self.server.base_url}/api/memos",
                   json={"instance_id": "i2", "body": "shared",
                         "visibility": "shared"})
        bob_view = bob.get(
            f"{self.server.base_url}/api/memos?instance_id=i2").json()["memos"]
        assert [m["body"] for m in bob_view] == ["shared"]
        # peer cannot edit alice's shared memo
        sid = bob_view[0]["id"]
        assert bob.patch(f"{self.server.base_url}/api/memos/{sid}",
                         json={"body": "hax"}).status_code == 403


class TestMemosDisabled:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("memos_api_disabled")
        data_file = create_test_data_file(test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            test_dir, _SCHEMES, data_files=[data_file],
            require_password=False)  # no annotation_ui -> memos off
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_endpoint_exists_but_503_when_disabled(self):
        s = _login(self.server, "carol")
        r = s.get(f"{self.server.base_url}/api/memos?instance_id=i1")
        assert r.status_code == 503
        assert "not enabled" in r.json()["error"].lower()
