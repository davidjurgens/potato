"""
Refused cases for account creation and admin access, driven through a real
server. The existing tests checked that allowed callers get in; these check
that the others are kept out.
"""

import json
import os
import unicodedata

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

SCHEMES = [{"name": "s", "annotation_type": "radio", "description": "d", "labels": ["a", "b"]}]


def _output_dir():
    from potato.server_utils.config_module import config
    return config["output_annotation_dir"]


class TestUsernamesAreNotPaths:
    @pytest.fixture(scope="class")
    def server(self):
        with TestConfigManager("tg2_usernames", SCHEMES, num_instances=2,
                               require_password=True) as tc:
            srv = FlaskTestServer(port=9800, config_file=tc.config_path)
            assert srv.start()
            yield srv
            srv.stop()

    def _register(self, server, name):
        s = requests.Session()
        r = s.post(server.base_url + "/register", data={"email": name, "pass": "pw"})
        return s, r

    def test_a_dotdot_name_cannot_overwrite_another_account(self, server):
        alice, _ = self._register(server, "alice")
        alice.get(server.base_url + "/annotate")
        alice.post(server.base_url + "/updateinstance",
                   json={"instance_id": "1", "annotations": {"s:::a": "true"}})
        state_file = os.path.join(_output_dir(), "alice", "user_state.json")
        assert json.load(open(state_file))["user_id"] == "alice"

        intruder, r = self._register(server, "zz/../alice")
        assert "cannot contain" in r.text
        intruder.post(server.base_url + "/updateinstance",
                      json={"instance_id": "2", "annotations": {"s:::b": "true"}})
        assert json.load(open(state_file))["user_id"] == "alice"

    def test_a_name_cannot_leave_the_output_directory(self, server):
        s, r = self._register(server, "../escaped_user")
        assert "cannot" in r.text
        s.get(server.base_url + "/annotate")
        s.post(server.base_url + "/updateinstance",
               json={"instance_id": "1", "annotations": {"s:::a": "true"}})
        assert not os.path.exists(os.path.join(os.path.dirname(_output_dir()), "escaped_user"))

    def test_a_case_variant_of_an_existing_name_is_refused(self, server):
        self._register(server, "bob")
        _, r = self._register(server, "Bob")
        assert "already in use" in r.text

    def test_the_other_unicode_spelling_of_an_existing_name_is_refused(self, server):
        nfc = unicodedata.normalize("NFC", "José")
        nfd = unicodedata.normalize("NFD", "José")
        assert nfc != nfd
        self._register(server, nfc)
        _, r = self._register(server, nfd)
        assert "already in use" in r.text


class TestDebugOnAPublicBind:
    """`debug: true` on 0.0.0.0 must not open the admin API to anyone."""

    @pytest.fixture(scope="class")
    def server(self):
        with TestConfigManager("tg2_debug_bind", SCHEMES, num_instances=2,
                               admin_api_key="real-key-xyz", require_password=True,
                               debug=True) as tc:
            srv = FlaskTestServer(port=9801, debug=True, config_file=tc.config_path)
            assert srv.start()
            # The harness binds loopback; tell the server it is on every
            # interface, which is what a Docker or LAN deployment reports.
            from potato.server_utils.config_module import config
            config["host"] = "0.0.0.0"
            requests.post(srv.base_url + "/register", data={"email": "alice", "pass": "alicepw"})
            yield srv
            config["host"] = "127.0.0.1"
            srv.stop()

    @pytest.mark.parametrize("path", ["/admin/api/config", "/admin/user_state/alice"])
    def test_anonymous_admin_reads_are_refused(self, server, path):
        assert requests.get(server.base_url + path).status_code in (401, 403)

    def test_anonymous_password_reset_is_refused(self, server):
        r = requests.post(server.base_url + "/admin/reset_password",
                          json={"username": "alice", "new_password": "pwned"})
        assert r.status_code == 403
        from potato.authentication import UserAuthenticator
        assert not UserAuthenticator.authenticate("alice", "pwned")

    def test_the_admin_key_still_works(self, server):
        r = requests.get(server.base_url + "/admin/api/config",
                         headers={"X-API-Key": "real-key-xyz"})
        assert r.status_code == 200


class TestDashboardViewerCannotTakeOverAccounts:
    @pytest.fixture(scope="class")
    def server(self):
        extra = {"rbac": {"enabled": True,
                          "roles": {"viewer": ["view_admin_dashboard"]},
                          "user_role_assignments": {"vic": "viewer"}}}
        with TestConfigManager("tg2_viewer", SCHEMES, num_instances=2,
                               admin_api_key="real-key-xyz", require_password=True,
                               additional_config=extra) as tc:
            srv = FlaskTestServer(port=9802, config_file=tc.config_path)
            assert srv.start()
            for u in ("vic", "adj"):
                requests.post(srv.base_url + "/register", data={"email": u, "pass": u + "pw"})
            vic = requests.Session()
            vic.post(srv.base_url + "/auth", data={"email": "vic", "pass": "vicpw"})
            srv.vic = vic
            yield srv
            srv.stop()

    def test_the_viewer_can_read_the_dashboard_api(self, server):
        assert server.vic.get(server.base_url + "/admin/api/config").status_code == 200

    @pytest.mark.parametrize("path,body", [
        ("/admin/reset_password", {"username": "adj", "new_password": "taken"}),
        ("/admin/create_reset_token", {"username": "adj"}),
        ("/admin/api/config", {"max_annotations_per_user": 1}),
    ])
    def test_the_viewer_cannot_change_accounts_or_settings(self, server, path, body):
        assert server.vic.post(server.base_url + path, json=body).status_code == 403
        from potato.authentication import UserAuthenticator
        assert UserAuthenticator.authenticate("adj", "adjpw")


class TestCrossSiteWrites:
    @pytest.fixture(scope="class")
    def server(self):
        with TestConfigManager("tg2_crowd_csrf", SCHEMES, num_instances=2,
                               admin_api_key="real-key-xyz") as tc:
            srv = FlaskTestServer(port=9803, config_file=tc.config_path)
            assert srv.start()
            yield srv
            srv.stop()

    def _admin(self, server):
        s = requests.Session()
        s.get(server.base_url + "/admin", headers={"X-API-Key": "real-key-xyz"})
        assert "session" in s.cookies
        return s

    @pytest.mark.parametrize("origin", [
        "http://evil.example",
        # The old check was a string prefix, which this passes.
        "{base}.evil.example",
    ])
    def test_a_cross_site_payment_request_is_refused(self, server, origin):
        r = self._admin(server).post(
            server.base_url + "/admin/api/crowd/study/S1/bonus",
            headers={"Origin": origin.format(base=server.base_url), "Content-Type": "text/plain"},
            data='{"bonuses": [["attacker", 99.0]]}')
        assert r.status_code == 403

    def test_a_same_origin_request_reaches_the_route(self, server):
        r = self._admin(server).post(
            server.base_url + "/admin/api/crowd/study/S1/bonus",
            headers={"Origin": server.base_url}, json={"bonuses": []})
        assert r.status_code != 403

    def test_the_session_cookie_is_samesite_lax(self, server):
        r = requests.post(server.base_url + "/register", data={"email": "carol", "pass": "pw"},
                          allow_redirects=False)
        cookie = r.headers.get("Set-Cookie", "")
        assert "session=" in cookie and "SameSite=Lax" in cookie
