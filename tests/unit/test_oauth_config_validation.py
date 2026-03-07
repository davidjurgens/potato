"""Unit tests for OAuth config validation in config_module.py."""

import pytest
from unittest.mock import patch

from potato.server_utils.config_module import (
    validate_authentication_config,
    ConfigValidationError,
)


class TestOAuthConfigValidation:
    """Config validation catches errors at startup, not at login time."""

    def _base_config(self, **overrides):
        """Build a minimal valid config with authentication section."""
        config = {
            "authentication": {
                "method": "oauth",
                "providers": {
                    "google": {
                        "client_id": "fake-id",
                        "client_secret": "fake-secret",
                    }
                },
            },
            "secret_key": "test-secret",
        }
        config.update(overrides)
        return config

    # --- Valid configs ---

    def test_valid_google_config_passes(self):
        validate_authentication_config(self._base_config())

    def test_valid_github_config_passes(self):
        config = self._base_config()
        config["authentication"]["providers"] = {
            "github": {"client_id": "fake-id", "client_secret": "fake-secret"}
        }
        validate_authentication_config(config)

    def test_valid_oidc_config_passes(self):
        config = self._base_config()
        config["authentication"]["providers"] = {
            "oidc": {
                "client_id": "fake-id",
                "client_secret": "fake-secret",
                "discovery_url": "https://sso.example.com/.well-known/openid-configuration",
            }
        }
        validate_authentication_config(config)

    def test_no_authentication_section_passes(self):
        """Missing authentication section is fine — uses default in_memory."""
        validate_authentication_config({})

    def test_in_memory_method_passes(self):
        validate_authentication_config(
            {"authentication": {"method": "in_memory"}}
        )

    def test_multiple_providers_passes(self):
        config = self._base_config()
        config["authentication"]["providers"]["github"] = {
            "client_id": "gh-id",
            "client_secret": "gh-secret",
        }
        validate_authentication_config(config)

    # --- Invalid configs ---

    def test_invalid_method_fails(self):
        with pytest.raises(ConfigValidationError, match="must be one of"):
            validate_authentication_config(
                {"authentication": {"method": "magic"}}
            )

    def test_oauth_without_providers_fails(self):
        with pytest.raises(ConfigValidationError, match="providers is required"):
            validate_authentication_config(
                {"authentication": {"method": "oauth"}}
            )

    def test_empty_providers_dict_fails(self):
        with pytest.raises(ConfigValidationError, match="at least one provider"):
            validate_authentication_config(
                {"authentication": {"method": "oauth", "providers": {}}}
            )

    def test_providers_not_dict_fails(self):
        with pytest.raises(ConfigValidationError, match="providers is required"):
            validate_authentication_config(
                {"authentication": {"method": "oauth", "providers": ["google"]}}
            )

    def test_missing_client_id_fails(self):
        with pytest.raises(ConfigValidationError, match="client_id is required"):
            validate_authentication_config({
                "authentication": {
                    "method": "oauth",
                    "providers": {
                        "google": {"client_secret": "secret"}
                    },
                }
            })

    def test_missing_client_secret_fails(self):
        with pytest.raises(ConfigValidationError, match="client_secret is required"):
            validate_authentication_config({
                "authentication": {
                    "method": "oauth",
                    "providers": {
                        "google": {"client_id": "id"}
                    },
                }
            })

    def test_oidc_missing_discovery_url_fails(self):
        with pytest.raises(ConfigValidationError, match="requires 'discovery_url'"):
            validate_authentication_config({
                "authentication": {
                    "method": "oauth",
                    "providers": {
                        "custom_sso": {
                            "client_id": "id",
                            "client_secret": "secret",
                        }
                    },
                }
            })

    def test_google_without_discovery_url_passes(self):
        """Google has built-in discovery URL — doesn't need one in config."""
        validate_authentication_config(self._base_config())

    def test_github_without_discovery_url_passes(self):
        """GitHub has built-in endpoints — doesn't need discovery_url."""
        config = self._base_config()
        config["authentication"]["providers"] = {
            "github": {"client_id": "id", "client_secret": "secret"}
        }
        validate_authentication_config(config)

    # --- user_identity_field ---

    def test_valid_identity_fields(self):
        for field in ("email", "username", "sub", "name"):
            config = self._base_config()
            config["authentication"]["user_identity_field"] = field
            validate_authentication_config(config)

    def test_invalid_identity_field_fails(self):
        config = self._base_config()
        config["authentication"]["user_identity_field"] = "avatar_url"
        with pytest.raises(ConfigValidationError, match="user_identity_field"):
            validate_authentication_config(config)

    # --- Optional field validation ---

    def test_empty_allowed_domain_fails(self):
        config = self._base_config()
        config["authentication"]["providers"]["google"]["allowed_domain"] = ""
        with pytest.raises(ConfigValidationError, match="allowed_domain"):
            validate_authentication_config(config)

    def test_empty_allowed_org_fails(self):
        config = self._base_config()
        config["authentication"]["providers"] = {
            "github": {
                "client_id": "id",
                "client_secret": "secret",
                "allowed_org": "",
            }
        }
        with pytest.raises(ConfigValidationError, match="allowed_org"):
            validate_authentication_config(config)

    def test_scopes_must_be_list(self):
        config = self._base_config()
        config["authentication"]["providers"] = {
            "oidc": {
                "client_id": "id",
                "client_secret": "secret",
                "discovery_url": "https://sso.example.com/.well-known/openid-configuration",
                "scopes": "openid email",  # Should be a list
            }
        }
        with pytest.raises(ConfigValidationError, match="scopes must be a list"):
            validate_authentication_config(config)

    # --- secret_key warning ---

    def test_no_secret_key_logs_warning(self):
        """OAuth without secret_key should warn but not fail."""
        config = {
            "authentication": {
                "method": "oauth",
                "providers": {
                    "google": {"client_id": "id", "client_secret": "secret"}
                },
            }
            # No secret_key
        }
        with patch.dict("os.environ", {}, clear=True):
            # Should not raise, just warn
            validate_authentication_config(config)

    def test_authentication_not_dict_fails(self):
        with pytest.raises(ConfigValidationError, match="must be a dictionary"):
            validate_authentication_config({"authentication": "oauth"})

    def test_provider_not_dict_fails(self):
        with pytest.raises(ConfigValidationError, match="must be a dictionary"):
            validate_authentication_config({
                "authentication": {
                    "method": "oauth",
                    "providers": {"google": "invalid"},
                }
            })
