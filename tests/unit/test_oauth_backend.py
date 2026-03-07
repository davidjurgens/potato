"""Unit tests for OAuthBackend — no network, no Flask server."""

import os
import pytest
from unittest.mock import patch

from potato.auth_backends.oauth_backend import OAuthBackend
from tests.helpers.oauth_test_utils import (
    make_oauth_config,
    google_provider,
    github_provider,
    oidc_provider,
)


class TestOAuthProviderRegistration:
    """Test that providers are correctly registered from config."""

    def test_registers_google_provider(self):
        config = make_oauth_config(providers={"google": google_provider()})
        backend = OAuthBackend(config)
        assert "google" in backend.providers_config

    def test_registers_github_provider(self):
        config = make_oauth_config(providers={"github": github_provider()})
        backend = OAuthBackend(config)
        assert "github" in backend.providers_config

    def test_registers_generic_oidc_provider(self):
        config = make_oauth_config(providers={"oidc": oidc_provider()})
        backend = OAuthBackend(config)
        assert "oidc" in backend.providers_config

    def test_registers_multiple_providers(self):
        config = make_oauth_config(
            providers={
                "google": google_provider(),
                "github": github_provider(),
            }
        )
        backend = OAuthBackend(config)
        assert len(backend.providers_config) == 2

    def test_no_providers_raises_error(self):
        config = make_oauth_config(providers={})
        with pytest.raises(ValueError, match="at least one provider"):
            OAuthBackend(config)

    def test_empty_providers_dict_raises_error(self):
        config = {"method": "oauth", "providers": {}}
        with pytest.raises(ValueError, match="at least one provider"):
            OAuthBackend(config)


class TestUserIdentityMapping:
    """Test extract_user_id with different identity fields and profiles."""

    def _backend(self, field="email"):
        config = make_oauth_config(
            providers={"google": google_provider()},
            user_identity_field=field,
        )
        return OAuthBackend(config)

    def test_email_extraction(self):
        backend = self._backend("email")
        profile = {"email": "alice@umich.edu", "sub": "12345", "name": "Alice"}
        assert backend.extract_user_id(profile) == "alice@umich.edu"

    def test_sub_extraction(self):
        backend = self._backend("sub")
        profile = {"email": "alice@umich.edu", "sub": "12345"}
        assert backend.extract_user_id(profile) == "12345"

    def test_username_extraction_github_login(self):
        backend = self._backend("username")
        profile = {"login": "alice123", "email": "alice@umich.edu"}
        assert backend.extract_user_id(profile) == "alice123"

    def test_username_extraction_preferred_username(self):
        backend = self._backend("username")
        profile = {"preferred_username": "alice_oidc", "email": "alice@umich.edu"}
        assert backend.extract_user_id(profile) == "alice_oidc"

    def test_name_extraction(self):
        backend = self._backend("name")
        profile = {"name": "Alice Smith", "email": "alice@umich.edu"}
        assert backend.extract_user_id(profile) == "Alice Smith"

    def test_fallback_to_email_when_field_missing(self):
        backend = self._backend("username")
        profile = {"email": "alice@umich.edu"}  # no 'login' or 'preferred_username'
        assert backend.extract_user_id(profile) == "alice@umich.edu"

    def test_fallback_to_login_when_email_missing(self):
        backend = self._backend("email")
        profile = {"login": "alice123", "sub": "12345"}  # no email
        assert backend.extract_user_id(profile) == "alice123"

    def test_fallback_to_sub_when_nothing_else(self):
        backend = self._backend("email")
        profile = {"sub": "12345"}  # no email, no login
        assert backend.extract_user_id(profile) == "12345"

    def test_no_usable_field_raises(self):
        backend = self._backend("email")
        profile = {"picture": "https://example.com/photo.jpg"}
        with pytest.raises(ValueError, match="Cannot extract user identity"):
            backend.extract_user_id(profile)


class TestDomainRestrictions:
    """Test allowed_domain restrictions for Google."""

    def _backend(self, domain):
        config = make_oauth_config(
            providers={"google": google_provider(allowed_domain=domain)}
        )
        return OAuthBackend(config)

    def test_matching_domain_passes(self):
        backend = self._backend("umich.edu")
        profile = {"email": "alice@umich.edu"}
        allowed, reason = backend.check_restrictions("google", profile)
        assert allowed is True
        assert reason == ""

    def test_case_insensitive_domain_match(self):
        backend = self._backend("UMich.EDU")
        profile = {"email": "alice@umich.edu"}
        allowed, reason = backend.check_restrictions("google", profile)
        assert allowed is True

    def test_wrong_domain_rejected(self):
        backend = self._backend("umich.edu")
        profile = {"email": "alice@gmail.com"}
        allowed, reason = backend.check_restrictions("google", profile)
        assert allowed is False
        assert "umich.edu" in reason

    def test_no_domain_restriction_allows_all(self):
        config = make_oauth_config(
            providers={"google": google_provider()}  # no allowed_domain
        )
        backend = OAuthBackend(config)
        profile = {"email": "anyone@anywhere.com"}
        allowed, reason = backend.check_restrictions("google", profile)
        assert allowed is True


class TestOrgRestrictions:
    """Test allowed_org helper for GitHub."""

    def test_get_allowed_org_returns_value(self):
        config = make_oauth_config(
            providers={"github": github_provider(allowed_org="my-lab")}
        )
        backend = OAuthBackend(config)
        assert backend.get_allowed_org("github") == "my-lab"

    def test_get_allowed_org_returns_none_when_not_set(self):
        config = make_oauth_config(
            providers={"github": github_provider()}
        )
        backend = OAuthBackend(config)
        assert backend.get_allowed_org("github") is None


class TestAutoRegister:
    """Test auto_register setting."""

    def test_auto_register_default_true(self):
        config = make_oauth_config(providers={"google": google_provider()})
        backend = OAuthBackend(config)
        assert backend.auto_register is True

    def test_auto_register_false(self):
        config = make_oauth_config(
            providers={"google": google_provider()},
            auto_register=False,
        )
        backend = OAuthBackend(config)
        assert backend.auto_register is False


class TestAuthBackendInterface:
    """Test the AuthBackend interface methods."""

    def _backend(self):
        config = make_oauth_config(providers={"google": google_provider()})
        return OAuthBackend(config)

    def test_add_user_and_authenticate(self):
        backend = self._backend()
        result = backend.add_user("alice@example.com", None, oauth_provider="google")
        assert result == "Success"
        assert backend.authenticate("alice@example.com", None) is True

    def test_authenticate_unknown_user_fails(self):
        backend = self._backend()
        assert backend.authenticate("unknown@example.com", None) is False

    def test_is_valid_username(self):
        backend = self._backend()
        backend.add_user("alice@example.com", None)
        assert backend.is_valid_username("alice@example.com") is True
        assert backend.is_valid_username("unknown@example.com") is False

    def test_add_duplicate_user_updates_data(self):
        backend = self._backend()
        backend.add_user("alice@example.com", None, oauth_provider="google")
        result = backend.add_user("alice@example.com", None, oauth_provider="github")
        assert result == "Success"
        assert backend.users["alice@example.com"]["oauth_provider"] == "github"


class TestLoginProviders:
    """Test get_login_providers() metadata generation."""

    def test_google_provider_metadata(self):
        config = make_oauth_config(providers={"google": google_provider()})
        backend = OAuthBackend(config)
        providers = backend.get_login_providers()
        assert len(providers) == 1
        assert providers[0]["name"] == "google"
        assert providers[0]["display_name"] == "Google"
        assert "google" in providers[0]["login_url"]

    def test_github_provider_metadata(self):
        config = make_oauth_config(providers={"github": github_provider()})
        backend = OAuthBackend(config)
        providers = backend.get_login_providers()
        assert providers[0]["display_name"] == "GitHub"

    def test_oidc_provider_uses_custom_display_name(self):
        config = make_oauth_config(
            providers={"oidc": oidc_provider(display_name="University SSO")}
        )
        backend = OAuthBackend(config)
        providers = backend.get_login_providers()
        assert providers[0]["display_name"] == "University SSO"

    def test_multiple_providers_returns_all(self):
        config = make_oauth_config(
            providers={
                "google": google_provider(),
                "github": github_provider(),
            }
        )
        backend = OAuthBackend(config)
        providers = backend.get_login_providers()
        assert len(providers) == 2
        names = {p["name"] for p in providers}
        assert names == {"google", "github"}


class TestEnvVarResolution:
    """Test ${ENV_VAR} resolution in config values."""

    def test_resolves_env_var(self):
        with patch.dict(os.environ, {"TEST_CLIENT_ID": "resolved-id"}):
            result = OAuthBackend._resolve_env("${TEST_CLIENT_ID}")
            assert result == "resolved-id"

    def test_unset_env_var_returns_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            result = OAuthBackend._resolve_env("${NONEXISTENT_VAR}")
            assert result == ""

    def test_plain_string_passthrough(self):
        result = OAuthBackend._resolve_env("plain-value")
        assert result == "plain-value"

    def test_non_string_passthrough(self):
        result = OAuthBackend._resolve_env(12345)
        assert result == 12345
