"""
Unit tests for password management features:
- Per-user salt hashing
- update_password
- Backward compatibility (salt$hash vs plaintext loading)
- Token management (create/validate/consume/expiry)
- save_user_config behavior
- DatabaseAuthBackend (SQLite)
"""

import os
import json
import time
import tempfile
import pytest

from potato.authentication import (
    InMemoryAuthBackend,
    DatabaseAuthBackend,
    UserAuthenticator,
    _hash_password_with_salt,
    _is_salted_hash,
    _verify_password,
    USER_AUTHENTICATOR_SINGLETON,
    _USER_AUTHENTICATOR_LOCK,
)
import potato.authentication as auth_module


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the UserAuthenticator singleton between tests."""
    auth_module.USER_AUTHENTICATOR_SINGLETON = None
    yield
    auth_module.USER_AUTHENTICATOR_SINGLETON = None


class TestPerUserSalt:
    """Test per-user salt hashing."""

    def test_two_users_same_password_different_hashes(self):
        backend = InMemoryAuthBackend()
        backend.add_user("alice", "password123")
        backend.add_user("bob", "password123")
        assert backend.users["alice"] != backend.users["bob"]

    def test_hash_format_is_salt_dollar_hash(self):
        backend = InMemoryAuthBackend()
        backend.add_user("alice", "password123")
        stored = backend.users["alice"]
        assert "$" in stored
        parts = stored.split("$", 1)
        assert len(parts[0]) == 32  # salt is 32 hex chars
        assert len(parts[1]) == 64  # sha256 hash is 64 hex chars

    def test_authenticate_correct_password(self):
        backend = InMemoryAuthBackend()
        backend.add_user("alice", "correct_password")
        assert backend.authenticate("alice", "correct_password") is True

    def test_authenticate_wrong_password(self):
        backend = InMemoryAuthBackend()
        backend.add_user("alice", "correct_password")
        assert backend.authenticate("alice", "wrong_password") is False

    def test_authenticate_nonexistent_user(self):
        backend = InMemoryAuthBackend()
        assert backend.authenticate("nobody", "password") is False

    def test_authenticate_passwordless(self):
        backend = InMemoryAuthBackend()
        backend.add_user("alice", "password123")
        assert backend.authenticate("alice", None) is True

    def test_is_salted_hash_recognizes_valid_format(self):
        hashed = _hash_password_with_salt("test")
        assert _is_salted_hash(hashed) is True

    def test_is_salted_hash_rejects_plaintext(self):
        assert _is_salted_hash("plaintext_password") is False
        assert _is_salted_hash("") is False
        assert _is_salted_hash(None) is False

    def test_verify_password_works(self):
        hashed = _hash_password_with_salt("mypassword")
        assert _verify_password("mypassword", hashed) is True
        assert _verify_password("wrong", hashed) is False

    def test_duplicate_user_rejected(self):
        backend = InMemoryAuthBackend()
        assert backend.add_user("alice", "pass1") == "Success"
        assert backend.add_user("alice", "pass2") == "Duplicate user"


class TestUpdatePassword:
    """Test password update functionality."""

    def test_update_password_changes_hash(self):
        backend = InMemoryAuthBackend()
        backend.add_user("alice", "old_password")
        old_hash = backend.users["alice"]
        result = backend.update_password("alice", "new_password")
        assert result is True
        assert backend.users["alice"] != old_hash

    def test_update_password_old_fails_new_works(self):
        backend = InMemoryAuthBackend()
        backend.add_user("alice", "old_password")
        backend.update_password("alice", "new_password")
        assert backend.authenticate("alice", "old_password") is False
        assert backend.authenticate("alice", "new_password") is True

    def test_update_password_nonexistent_user(self):
        backend = InMemoryAuthBackend()
        assert backend.update_password("nobody", "pass") is False

    def test_get_all_users(self):
        backend = InMemoryAuthBackend()
        backend.add_user("alice", "pass1")
        backend.add_user("bob", "pass2")
        users = backend.get_all_users()
        assert sorted(users) == ["alice", "bob"]


class TestPrehashed:
    """Test loading pre-hashed passwords."""

    def test_add_user_prehashed(self):
        backend = InMemoryAuthBackend()
        hashed = _hash_password_with_salt("secret")
        result = backend.add_user_prehashed("alice", hashed)
        assert result == "Success"
        assert backend.authenticate("alice", "secret") is True

    def test_add_user_prehashed_duplicate(self):
        backend = InMemoryAuthBackend()
        hashed = _hash_password_with_salt("secret")
        backend.add_user_prehashed("alice", hashed)
        assert backend.add_user_prehashed("alice", hashed) == "Duplicate user"


class TestBackwardCompatibility:
    """Test loading user_config.json with both salt$hash and plaintext passwords."""

    def test_load_salted_hash_from_file(self, tmp_path):
        """Users with salt$hash passwords should be loaded via add_user_prehashed."""
        hashed = _hash_password_with_salt("mypassword")
        user_file = tmp_path / "user_config.json"
        user_file.write_text(
            json.dumps({"username": "alice", "password": hashed}) + "\n"
        )

        authenticator = UserAuthenticator(str(user_file))
        authenticator.require_password = True
        assert authenticator.is_valid_username("alice")
        # The prehashed password should authenticate correctly
        assert authenticator.auth_backend.authenticate("alice", "mypassword")

    def test_load_plaintext_from_file(self, tmp_path):
        """Users with plaintext passwords should be loaded via add_single_user (re-hashed)."""
        user_file = tmp_path / "user_config.json"
        user_file.write_text(
            json.dumps({"username": "bob", "password": "plaintext123"}) + "\n"
        )

        authenticator = UserAuthenticator(str(user_file))
        authenticator.require_password = True
        assert authenticator.is_valid_username("bob")
        # Plaintext is re-hashed via add_single_user → add_user
        assert authenticator.auth_backend.authenticate("bob", "plaintext123")


class TestTokenManagement:
    """Test password reset token management."""

    def test_create_token_for_existing_user(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file))
        authenticator.add_user("alice", "password")
        token = authenticator.create_reset_token("alice")
        assert token is not None

    def test_create_token_for_nonexistent_user(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file))
        token = authenticator.create_reset_token("nobody")
        assert token is None

    def test_validate_token(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file))
        authenticator.add_user("alice", "password")
        token = authenticator.create_reset_token("alice")
        username = authenticator.validate_reset_token(token)
        assert username == "alice"

    def test_consume_token_single_use(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file))
        authenticator.add_user("alice", "password")
        token = authenticator.create_reset_token("alice")

        # First consume should work
        username = authenticator.consume_reset_token(token)
        assert username == "alice"

        # Second consume should fail (single-use)
        username = authenticator.consume_reset_token(token)
        assert username is None

    def test_expired_token(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file))
        authenticator.add_user("alice", "password")

        # Create token with very short TTL
        token = authenticator.create_reset_token("alice", ttl_hours=0)
        # Token should be expired immediately
        # The ttl_hours=0 means expires = time.time() + 0 = now
        time.sleep(0.1)
        username = authenticator.validate_reset_token(token)
        assert username is None

    def test_new_token_invalidates_old(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file))
        authenticator.add_user("alice", "password")

        old_token = authenticator.create_reset_token("alice")
        new_token = authenticator.create_reset_token("alice")

        assert authenticator.validate_reset_token(old_token) is None
        assert authenticator.validate_reset_token(new_token) == "alice"

    def test_invalid_token(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file))
        assert authenticator.validate_reset_token("bogus_token") is None


class TestSaveUserConfig:
    """Test save_user_config behavior."""

    def test_saves_when_explicit_path_in_memory(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file), auth_method="in_memory")
        authenticator.user_config_path_explicit = True
        authenticator.add_user("alice", "password123")
        authenticator.save_user_config()

        # File should now contain the user with hashed password
        content = user_file.read_text().strip()
        assert content  # non-empty
        data = json.loads(content)
        assert data["username"] == "alice"
        assert _is_salted_hash(data["password"])

    def test_skips_when_default_path_in_memory(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file), auth_method="in_memory")
        authenticator.user_config_path_explicit = False  # default
        authenticator.add_user("alice", "password123")
        authenticator.save_user_config()

        # File should remain empty
        assert user_file.read_text().strip() == ""

    def test_skips_for_database_method(self, tmp_path):
        """Database backend handles its own persistence."""
        db_path = str(tmp_path / "test.db")
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(
            str(user_file),
            auth_method="database",
            auth_config={"database_url": f"sqlite:///{db_path}"}
        )
        authenticator.add_user("alice", "password123")
        authenticator.save_user_config()
        # Should not write to file
        assert user_file.read_text().strip() == ""


class TestDatabaseAuthBackend:
    """Test the real SQLite DatabaseAuthBackend."""

    def test_sqlite_table_creation(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = DatabaseAuthBackend(f"sqlite:///{db_path}")
        assert os.path.exists(db_path)
        backend.close()

    def test_add_authenticate_cycle(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = DatabaseAuthBackend(f"sqlite:///{db_path}")

        assert backend.add_user("alice", "password123") == "Success"
        assert backend.authenticate("alice", "password123") is True
        assert backend.authenticate("alice", "wrong") is False
        assert backend.is_valid_username("alice") is True
        assert backend.is_valid_username("nobody") is False
        backend.close()

    def test_per_user_salt(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = DatabaseAuthBackend(f"sqlite:///{db_path}")

        backend.add_user("alice", "same_password")
        backend.add_user("bob", "same_password")

        # Both should authenticate independently
        assert backend.authenticate("alice", "same_password") is True
        assert backend.authenticate("bob", "same_password") is True
        backend.close()

    def test_duplicate_rejection(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = DatabaseAuthBackend(f"sqlite:///{db_path}")

        assert backend.add_user("alice", "pass1") == "Success"
        assert backend.add_user("alice", "pass2") == "Duplicate user"
        backend.close()

    def test_update_password(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = DatabaseAuthBackend(f"sqlite:///{db_path}")

        backend.add_user("alice", "old_pass")
        assert backend.update_password("alice", "new_pass") is True
        assert backend.authenticate("alice", "old_pass") is False
        assert backend.authenticate("alice", "new_pass") is True
        backend.close()

    def test_get_all_users(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = DatabaseAuthBackend(f"sqlite:///{db_path}")

        backend.add_user("alice", "pass1")
        backend.add_user("bob", "pass2")
        users = backend.get_all_users()
        assert sorted(users) == ["alice", "bob"]
        backend.close()

    def test_passwordless_auth(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = DatabaseAuthBackend(f"sqlite:///{db_path}")

        backend.add_user("alice", "pass")
        assert backend.authenticate("alice", None) is True
        backend.close()

    def test_invalid_connection_string(self):
        with pytest.raises(ValueError, match="Unsupported database URL"):
            DatabaseAuthBackend("mysql://localhost/db")

    def test_prehashed_user(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = DatabaseAuthBackend(f"sqlite:///{db_path}")

        hashed = _hash_password_with_salt("secret")
        result = backend.add_user_prehashed("alice", hashed)
        assert result == "Success"
        assert backend.authenticate("alice", "secret") is True
        backend.close()


class TestUserAuthenticatorUpdatePassword:
    """Test UserAuthenticator.update_password integration."""

    def test_update_password_via_authenticator(self, tmp_path):
        user_file = tmp_path / "user_config.json"
        user_file.write_text("")
        authenticator = UserAuthenticator(str(user_file))
        authenticator.add_user("alice", "old_pass")

        result = authenticator.update_password("alice", "new_pass")
        assert result is True
        assert authenticator.auth_backend.authenticate("alice", "new_pass") is True
        assert authenticator.auth_backend.authenticate("alice", "old_pass") is False
