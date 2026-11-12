"""Tests that the `user_config` block actually gates registration.

`user_config.allow_all_users` and `user_config.users` were validated by the
config loader but never read by the authenticator: `UserAuthenticator.__init__`
hardcoded `allow_all_users = True` and `authorized_users = []`, and nothing ever
populated them from config. The roster checks in `add_user` were therefore
unreachable and `POST /register` accepted anyone who could reach the login page.

These tests cover the wiring end of that fix. The policy end (that `add_user`
enforces the roster regardless of password mode) lives in
`tests/unit/test_auth.py::TestUserAuthenticatorAuthorization`.
"""

import json
import os

import pytest

import potato.authentication as auth_mod
from potato.authentication import UserAuthenticator, _parse_authorized_users


@pytest.fixture(autouse=True)
def reset_singleton():
    """init_from_config is a singleton factory; clear it between tests."""
    auth_mod.USER_AUTHENTICATOR_SINGLETON = None
    yield
    auth_mod.USER_AUTHENTICATOR_SINGLETON = None


def _config(tmp_path, **overrides):
    cfg = {
        "output_annotation_dir": str(tmp_path / "annotation_output") + os.sep,
        "authentication": {"method": "in_memory"},
    }
    cfg.update(overrides)
    return cfg


# =====================================================================
# _parse_authorized_users
# =====================================================================


class TestParseAuthorizedUsers:
    def test_empty_block_yields_empty_roster(self):
        assert _parse_authorized_users({}) == []

    def test_plain_string_list(self):
        assert _parse_authorized_users({"users": ["alice", "bob"]}) == ["alice", "bob"]

    def test_dict_entries_use_username_field(self):
        block = {"users": [{"username": "alice", "password": "x"}, {"username": "bob"}]}
        assert _parse_authorized_users(block) == ["alice", "bob"]

    def test_mixed_shapes(self):
        block = {"users": ["alice", {"username": "bob"}]}
        assert _parse_authorized_users(block) == ["alice", "bob"]

    def test_bare_string_is_treated_as_one_user(self):
        assert _parse_authorized_users({"users": "alice"}) == ["alice"]

    def test_duplicates_collapse(self):
        block = {"users": ["alice", {"username": "alice"}]}
        assert _parse_authorized_users(block) == ["alice"]

    def test_unrecognized_entry_is_skipped_not_fatal(self):
        block = {"users": ["alice", 42, None]}
        assert _parse_authorized_users(block) == ["alice"]


# =====================================================================
# init_from_config wiring
# =====================================================================


class TestInitFromConfigWiring:
    def test_default_is_open_enrolment(self, tmp_path):
        """No user_config block at all must keep today's open behaviour."""
        authenticator = UserAuthenticator.init_from_config(_config(tmp_path))
        assert authenticator.allow_all_users is True
        assert authenticator.add_user("anyone", "pw") == "Success"

    def test_explicit_allow_all_users_true(self, tmp_path):
        cfg = _config(tmp_path, user_config={"allow_all_users": True})
        authenticator = UserAuthenticator.init_from_config(cfg)
        assert authenticator.add_user("anyone", "pw") == "Success"

    def test_allow_all_users_false_blocks_unlisted(self, tmp_path):
        cfg = _config(tmp_path, user_config={
            "allow_all_users": False,
            "users": ["alice"],
        })
        authenticator = UserAuthenticator.init_from_config(cfg)
        assert authenticator.allow_all_users is False
        assert authenticator.authorized_users == ["alice"]
        assert authenticator.add_user("mallory", "pw") == "Unauthorized user"

    def test_allow_all_users_false_admits_listed(self, tmp_path):
        cfg = _config(tmp_path, user_config={
            "allow_all_users": False,
            "users": ["alice"],
        })
        authenticator = UserAuthenticator.init_from_config(cfg)
        assert authenticator.add_user("alice", "pw") == "Success"

    def test_passwordless_config_still_enforces_roster(self, tmp_path):
        """require_password: false must not reopen enrolment.

        This is the combination that matters in practice: url_direct and
        prolific login both force require_password off.
        """
        cfg = _config(tmp_path, require_password=False, user_config={
            "allow_all_users": False,
            "users": ["alice"],
        })
        authenticator = UserAuthenticator.init_from_config(cfg)
        assert authenticator.require_password is False
        assert authenticator.add_user("mallory", None) == "Unauthorized user"
        assert authenticator.add_user("alice", None) == "Success"


# =====================================================================
# Interaction with authentication.user_config_path
# =====================================================================


class TestUserFileProvisioning:
    def _write_user_file(self, tmp_path, rows):
        path = tmp_path / "user_config.json"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return str(path)

    def test_file_users_are_implicitly_authorized(self, tmp_path):
        """A provisioned roster must not lock itself out.

        `allow_all_users: false` with a user file but no `user_config.users`
        list would otherwise reject every row it just loaded.
        """
        user_file = self._write_user_file(tmp_path, [
            {"username": "alice", "password": "pw1"},
            {"username": "bob", "password": "pw2"},
        ])
        cfg = _config(tmp_path, user_config={"allow_all_users": False})
        cfg["authentication"]["user_config_path"] = user_file

        authenticator = UserAuthenticator.init_from_config(cfg)
        assert set(authenticator.authorized_users) == {"alice", "bob"}
        assert authenticator.is_valid_username("alice")
        assert authenticator.add_user("mallory", "pw") == "Unauthorized user"

    def test_passwordless_user_file_loads_bare_usernames(self, tmp_path):
        """require_password reached the constructor too late to affect the load.

        `init_from_config` used to assign `require_password` *after* building the
        authenticator, so the user-file load ran under the default (True) and
        rejected every password-less row with "Missing password in user info".
        """
        user_file = self._write_user_file(tmp_path, [
            {"username": "alice"},
            {"username": "bob"},
        ])
        cfg = _config(tmp_path, require_password=False)
        cfg["authentication"]["user_config_path"] = user_file

        authenticator = UserAuthenticator.init_from_config(cfg)
        assert authenticator.users_loaded_from_file == 2
        assert authenticator.is_valid_username("alice")

    def test_file_roster_unions_with_config_roster(self, tmp_path):
        user_file = self._write_user_file(tmp_path, [{"username": "alice", "password": "pw"}])
        cfg = _config(tmp_path, user_config={
            "allow_all_users": False,
            "users": ["carol"],
        })
        cfg["authentication"]["user_config_path"] = user_file

        authenticator = UserAuthenticator.init_from_config(cfg)
        assert set(authenticator.authorized_users) == {"alice", "carol"}
        assert authenticator.add_user("carol", "pw") == "Success"

    def test_closed_enrolment_without_roster_warns(self, tmp_path, caplog):
        cfg = _config(tmp_path, user_config={"allow_all_users": False})
        with caplog.at_level("WARNING"):
            UserAuthenticator.init_from_config(cfg)
        assert any("no roster was given" in r.message for r in caplog.records)
