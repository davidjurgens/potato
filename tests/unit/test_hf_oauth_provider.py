"""Tests for HuggingFace OAuth provider configuration."""

import pytest


class TestHuggingFaceOAuthProvider:
    def test_provider_in_configs(self):
        """HuggingFace should be a recognized OAuth provider."""
        from potato.auth_backends.oauth_backend import PROVIDER_CONFIGS
        assert "huggingface" in PROVIDER_CONFIGS

    def test_oidc_discovery_url(self):
        """Provider should have a valid OIDC discovery URL."""
        from potato.auth_backends.oauth_backend import PROVIDER_CONFIGS
        hf = PROVIDER_CONFIGS["huggingface"]
        assert "server_metadata_url" in hf
        assert hf["server_metadata_url"].startswith("https://huggingface.co/")
        assert ".well-known/openid-configuration" in hf["server_metadata_url"]

    def test_display_name(self):
        from potato.auth_backends.oauth_backend import PROVIDER_CONFIGS
        hf = PROVIDER_CONFIGS["huggingface"]
        assert hf["display_name"] == "HuggingFace"

    def test_button_class(self):
        from potato.auth_backends.oauth_backend import PROVIDER_CONFIGS
        hf = PROVIDER_CONFIGS["huggingface"]
        assert hf["button_class"] == "oauth-btn-huggingface"

    def test_icon_class(self):
        from potato.auth_backends.oauth_backend import PROVIDER_CONFIGS
        hf = PROVIDER_CONFIGS["huggingface"]
        assert "icon_class" in hf

    def test_scopes_include_openid(self):
        """OIDC requires openid scope."""
        from potato.auth_backends.oauth_backend import PROVIDER_CONFIGS
        hf = PROVIDER_CONFIGS["huggingface"]
        scopes = hf["client_kwargs"]["scope"]
        assert "openid" in scopes

    def test_scopes_include_email(self):
        """Email scope needed for user identity."""
        from potato.auth_backends.oauth_backend import PROVIDER_CONFIGS
        hf = PROVIDER_CONFIGS["huggingface"]
        scopes = hf["client_kwargs"]["scope"]
        assert "email" in scopes
