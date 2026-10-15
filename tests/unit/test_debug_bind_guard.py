"""
Tests for the debug-mode guardrails.

`debug: true` bypassing admin authentication is deliberate and documented. It
was also unconditional, so a server on the default 0.0.0.0 bind handed the
admin API to anyone who could reach the port. These pin the scoping.
"""

import pytest

from potato.server_utils.admin_key import (
    debug_grants_admin,
    is_loopback_bind,
    validate_admin_api_key,
)


class TestLoopbackDetection:
    @pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.53", "::1", "localhost"])
    def test_loopback(self, host):
        assert is_loopback_bind({"host": host}) is True

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "10.0.0.1", "::", "example.com"])
    def test_not_loopback(self, host):
        assert is_loopback_bind({"host": host}) is False

    def test_unresolvable_hostname_is_not_loopback(self):
        # Guessing wrong in the other direction leaves the admin API open.
        assert is_loopback_bind({"host": "some-host-name"}) is False

    def test_default_host_is_not_loopback(self):
        # The default bind is 0.0.0.0, which is the whole point of the report.
        assert is_loopback_bind({}) is False


class TestDebugAdminBypassScoping:
    def test_debug_on_loopback_grants_admin(self):
        assert debug_grants_admin({"debug": True, "host": "127.0.0.1"}) is True

    def test_debug_on_public_bind_does_not_grant_admin(self):
        assert debug_grants_admin({"debug": True, "host": "0.0.0.0"}) is False

    def test_debug_on_lan_bind_does_not_grant_admin(self):
        assert debug_grants_admin({"debug": True, "host": "192.168.1.5"}) is False

    def test_no_debug_never_grants(self):
        assert debug_grants_admin({"debug": False, "host": "127.0.0.1"}) is False

    def test_default_config_does_not_grant(self):
        assert debug_grants_admin({}) is False


class TestValidateAdminApiKey:
    def test_wrong_key_on_public_debug_bind_is_refused(self):
        # This is the regression: it used to return True for any key, or none.
        cfg = {"debug": True, "host": "0.0.0.0", "admin_api_key": "realkey"}
        assert validate_admin_api_key("wrong", cfg) is False
        assert validate_admin_api_key("", cfg) is False
        assert validate_admin_api_key(None, cfg) is False

    def test_right_key_still_works_on_a_public_bind(self):
        cfg = {"debug": True, "host": "0.0.0.0", "admin_api_key": "realkey"}
        assert validate_admin_api_key("realkey", cfg) is True

    def test_local_debug_workflow_is_preserved(self):
        cfg = {"debug": True, "host": "127.0.0.1", "admin_api_key": "realkey"}
        assert validate_admin_api_key(None, cfg) is True


class _Req:
    def __init__(self, remote_addr, headers=None):
        self.remote_addr = remote_addr
        self.headers = headers or {}


class TestDebugOnAPublicBind:
    """Debug servers start on 0.0.0.0 so other machines can reach them; the
    admin bypass stays with requests from this machine."""

    def test_a_request_from_this_machine_gets_the_bypass(self):
        cfg = {"debug": True, "host": "0.0.0.0"}
        assert debug_grants_admin(cfg, _Req("127.0.0.1")) is True
        assert debug_grants_admin(cfg, _Req("::1")) is True

    def test_a_request_from_another_machine_does_not(self):
        cfg = {"debug": True, "host": "0.0.0.0"}
        assert debug_grants_admin(cfg, _Req("192.168.1.20")) is False

    def test_a_forwarded_request_does_not(self):
        """Behind a local proxy every request arrives from 127.0.0.1."""
        cfg = {"debug": True, "host": "0.0.0.0"}
        assert debug_grants_admin(
            cfg, _Req("127.0.0.1", {"X-Forwarded-For": "203.0.113.7"})) is False

    def test_rbac_follows_the_same_rule(self):
        from potato.server_utils.rbac import Permission, RBACManager
        m = RBACManager({"debug": True, "host": "0.0.0.0"})
        assert m.check(Permission.VIEW_ADMIN_DASHBOARD, _Req("127.0.0.1"), {})
        assert not m.check(Permission.VIEW_ADMIN_DASHBOARD, _Req("10.0.0.4"), {})
