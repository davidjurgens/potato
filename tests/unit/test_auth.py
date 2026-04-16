"""
Unit tests for the authentication module.

Replaces a 3-line stub that provided essentially no auth coverage.
Focus is on pure-logic paths that can be tested offline without Flask:

- InMemoryAuthBackend: add/authenticate/update/dup rejection
- Password hashing: salt uniqueness, round-trip verification
- UserAuthenticator reset-token lifecycle: create, validate, consume,
  expiry, single-use enforcement, token invalidation on new create
- UserAuthenticator authorization logic: allow_all_users=False gating
"""

import time

import pytest

from potato.authentication import (
    InMemoryAuthBackend,
    UserAuthenticator,
    _hash_password_with_salt,
    _verify_password,
    _is_salted_hash,
)


# =====================================================================
# InMemoryAuthBackend
# =====================================================================


class TestInMemoryAuthBackend:
    """Tests for the in-memory authentication backend."""

    def test_add_user_success(self):
        backend = InMemoryAuthBackend()
        result = backend.add_user("alice", "secret123")
        assert result == "Success"
        assert backend.is_valid_username("alice")

    def test_add_user_duplicate_rejected(self):
        backend = InMemoryAuthBackend()
        backend.add_user("bob", "pw1")
        result = backend.add_user("bob", "pw2")
        assert result == "Duplicate user"

    def test_authenticate_correct_password(self):
        backend = InMemoryAuthBackend()
        backend.add_user("carol", "right_pw")
        assert backend.authenticate("carol", "right_pw") is True

    def test_authenticate_wrong_password(self):
        backend = InMemoryAuthBackend()
        backend.add_user("dave", "right_pw")
        assert backend.authenticate("dave", "wrong_pw") is False

    def test_authenticate_unknown_user(self):
        backend = InMemoryAuthBackend()
        assert backend.authenticate("ghost", "anything") is False

    def test_authenticate_passwordless_mode(self):
        """password=None should succeed for any existing user (passwordless)."""
        backend = InMemoryAuthBackend()
        backend.add_user("eve", None)
        assert backend.authenticate("eve", None) is True

    def test_authenticate_passwordless_unknown_user_still_fails(self):
        backend = InMemoryAuthBackend()
        assert backend.authenticate("nobody", None) is False

    def test_update_password_existing_user(self):
        backend = InMemoryAuthBackend()
        backend.add_user("frank", "old_pw")
        assert backend.update_password("frank", "new_pw") is True
        assert backend.authenticate("frank", "new_pw") is True
        assert backend.authenticate("frank", "old_pw") is False

    def test_update_password_unknown_user(self):
        backend = InMemoryAuthBackend()
        assert backend.update_password("ghost", "new_pw") is False

    def test_get_all_users_returns_registered(self):
        backend = InMemoryAuthBackend()
        backend.add_user("a", "pw")
        backend.add_user("b", "pw")
        backend.add_user("c", "pw")
        assert set(backend.get_all_users()) == {"a", "b", "c"}

    def test_is_valid_username_false_for_unknown(self):
        backend = InMemoryAuthBackend()
        assert backend.is_valid_username("missing") is False

    def test_add_user_preserves_kwargs(self):
        backend = InMemoryAuthBackend()
        backend.add_user("grace", "pw", role="admin", email="g@test")
        assert backend.user_data["grace"]["role"] == "admin"
        assert backend.user_data["grace"]["email"] == "g@test"


# =====================================================================
# Password hashing primitives
# =====================================================================


class TestPasswordHashing:
    """Salt uniqueness and verification round-trip."""

    def test_hash_is_different_each_call_due_to_salt(self):
        """Two hashes of the same password must differ (random salt)."""
        h1 = _hash_password_with_salt("same_password")
        h2 = _hash_password_with_salt("same_password")
        assert h1 != h2

    def test_verify_password_round_trip(self):
        hashed = _hash_password_with_salt("my_secret")
        assert _verify_password("my_secret", hashed) is True

    def test_verify_password_wrong_password(self):
        hashed = _hash_password_with_salt("correct_pw")
        assert _verify_password("incorrect_pw", hashed) is False

    def test_hash_format_is_salt_hash(self):
        """Stored format should be 'salt$hash' where both are hex."""
        hashed = _hash_password_with_salt("anything")
        assert "$" in hashed
        salt, digest = hashed.split("$", 1)
        assert len(salt) == 32  # 32 hex chars = 16 bytes
        assert len(digest) == 64  # SHA-256 = 32 bytes = 64 hex
        int(salt, 16)  # must be valid hex
        int(digest, 16)

    def test_is_salted_hash_detects_format(self):
        assert _is_salted_hash(_hash_password_with_salt("x")) is True

    def test_is_salted_hash_rejects_plaintext(self):
        assert _is_salted_hash("plaintext_password") is False

    def test_is_salted_hash_rejects_empty(self):
        assert _is_salted_hash("") is False

    def test_verify_password_tolerates_malformed_hash(self):
        """A malformed stored hash should return False, not raise."""
        assert _verify_password("pw", "not_a_valid_format") is False


# =====================================================================
# UserAuthenticator reset-token lifecycle
# =====================================================================


@pytest.fixture
def authenticator(tmp_path):
    """A standalone UserAuthenticator instance backed by in-memory storage.

    We do NOT use the singleton (`init_from_config`) so tests stay isolated.
    """
    user_config_path = str(tmp_path / "nonexistent_user_config.json")
    auth = UserAuthenticator(
        user_config_path=user_config_path,
        auth_method="in_memory",
        auth_config={},
    )
    auth.add_user("alice", "alice_pw")
    auth.add_user("bob", "bob_pw")
    return auth


class TestResetTokenLifecycle:
    """Password reset token create/validate/consume/expire."""

    def test_create_reset_token_for_existing_user(self, authenticator):
        token = authenticator.create_reset_token("alice")
        assert token is not None
        assert len(token) > 20  # URL-safe base64, 32 bytes → ~43 chars

    def test_create_reset_token_for_unknown_user_returns_none(self, authenticator):
        assert authenticator.create_reset_token("ghost") is None

    def test_validate_returns_username(self, authenticator):
        token = authenticator.create_reset_token("alice")
        assert authenticator.validate_reset_token(token) == "alice"

    def test_validate_does_not_consume(self, authenticator):
        """Validation alone should not invalidate the token."""
        token = authenticator.create_reset_token("alice")
        assert authenticator.validate_reset_token(token) == "alice"
        assert authenticator.validate_reset_token(token) == "alice"

    def test_consume_is_single_use(self, authenticator):
        """consume() must delete the token — second call returns None."""
        token = authenticator.create_reset_token("alice")
        first = authenticator.consume_reset_token(token)
        second = authenticator.consume_reset_token(token)
        assert first == "alice"
        assert second is None

    def test_consume_unknown_token_returns_none(self, authenticator):
        assert authenticator.consume_reset_token("bogus_token") is None

    def test_validate_unknown_token_returns_none(self, authenticator):
        assert authenticator.validate_reset_token("bogus_token") is None

    def test_expired_token_is_rejected(self, authenticator):
        """Manually backdate a token past its expiry and verify it's rejected."""
        token = authenticator.create_reset_token("alice", ttl_hours=1)
        # Backdate the token by 2 hours
        authenticator._reset_tokens[token]["expires"] = time.time() - 3600
        assert authenticator.validate_reset_token(token) is None
        assert authenticator.consume_reset_token(token) is None

    def test_creating_new_token_invalidates_previous(self, authenticator):
        """A new token for the same user should invalidate prior tokens."""
        old_token = authenticator.create_reset_token("alice")
        new_token = authenticator.create_reset_token("alice")
        assert old_token != new_token
        assert authenticator.validate_reset_token(old_token) is None
        assert authenticator.validate_reset_token(new_token) == "alice"

    def test_token_per_user_is_independent(self, authenticator):
        """Creating a token for Bob should not affect Alice's token."""
        alice_token = authenticator.create_reset_token("alice")
        authenticator.create_reset_token("bob")
        assert authenticator.validate_reset_token(alice_token) == "alice"

    def test_ttl_zero_token_is_immediately_expired(self, authenticator):
        token = authenticator.create_reset_token("alice", ttl_hours=0)
        # With ttl=0 the token was born at or just after its expiry — sleep a
        # hair to make sure `now > expires` holds even on fast clocks.
        time.sleep(0.01)
        assert authenticator.validate_reset_token(token) is None


# =====================================================================
# UserAuthenticator authorization / allow_all_users
# =====================================================================


class TestUserAuthenticatorAuthorization:
    def test_allow_all_users_true_accepts_anyone(self, authenticator):
        authenticator.allow_all_users = True
        result = authenticator.add_user("new_random_user", "pw")
        assert result == "Success"

    def test_allow_all_users_false_blocks_unauthorized(self, authenticator):
        authenticator.allow_all_users = False
        authenticator.authorized_users = ["vip_user"]
        result = authenticator.add_user("nobody", "pw")
        assert result == "Unauthorized user"

    def test_allow_all_users_false_accepts_authorized(self, authenticator):
        authenticator.allow_all_users = False
        authenticator.authorized_users = ["vip_user"]
        result = authenticator.add_user("vip_user", "pw")
        assert result == "Success"

    def test_passwordless_mode_bypasses_authorization_check(self, authenticator):
        """In passwordless mode, add_user skips the authorized_users gate."""
        authenticator.allow_all_users = False
        authenticator.require_password = False
        authenticator.authorized_users = []
        result = authenticator.add_user("anyone", None)
        assert result == "Success"


# =====================================================================
# UserAuthenticator username/password validity helpers
# =====================================================================


class TestUserAuthenticatorValidityHelpers:
    def test_is_valid_username_reflects_backend_state(self, authenticator):
        assert authenticator.is_valid_username("alice") is True
        assert authenticator.is_valid_username("ghost") is False
