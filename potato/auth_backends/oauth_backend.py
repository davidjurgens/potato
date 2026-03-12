"""
OAuth 2.0 / OpenID Connect Authentication Backend

Supports Google, GitHub, and generic OIDC providers for single sign-on.
Uses Authlib for OAuth flow management, token exchange, and OIDC discovery.
"""

import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from authlib.integrations.flask_client import OAuth

from potato.authentication import AuthBackend

logger = logging.getLogger(__name__)

# Well-known OAuth provider configurations
PROVIDER_CONFIGS = {
    "google": {
        "display_name": "Google",
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile"},
        "icon_class": "fab fa-google",
        "button_class": "oauth-btn-google",
    },
    "github": {
        "display_name": "GitHub",
        "api_base_url": "https://api.github.com/",
        "access_token_url": "https://github.com/login/oauth/access_token",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "client_kwargs": {"scope": "user:email"},
        "icon_class": "fab fa-github",
        "button_class": "oauth-btn-github",
    },
}


class OAuthBackend(AuthBackend):
    """Authentication backend using OAuth 2.0 / OIDC providers.

    This backend delegates authentication to external identity providers
    (Google, GitHub, or any OIDC-compliant provider). After a user
    authenticates with the provider, they are mapped to a Potato user
    identity based on the configured identity field (email, username, etc.).
    """

    def __init__(self, auth_config: Dict[str, Any]):
        """Initialize the OAuth backend from authentication config.

        Args:
            auth_config: The 'authentication' section of the Potato YAML config.
                Must contain 'providers' dict with at least one provider.
        """
        self.users = {}  # username -> user profile data
        self.providers_config = auth_config.get("providers", {})
        self.user_identity_field = auth_config.get("user_identity_field", "email")
        self.auto_register = auth_config.get("auto_register", True)
        self.allow_local_login = auth_config.get("allow_local_login", False)
        self._oauth = None  # Initialized later via init_oauth()
        self._provider_metadata = {}  # Cached display info per provider

        if not self.providers_config:
            raise ValueError(
                "OAuth authentication requires at least one provider in "
                "'authentication.providers'"
            )

        # Build provider metadata for login page rendering
        for name, pconfig in self.providers_config.items():
            well_known = PROVIDER_CONFIGS.get(name, {})
            self._provider_metadata[name] = {
                "name": name,
                "display_name": pconfig.get(
                    "display_name", well_known.get("display_name", name.title())
                ),
                "icon_class": well_known.get("icon_class", "fas fa-sign-in-alt"),
                "button_class": well_known.get("button_class", "oauth-btn-generic"),
            }

        logger.info(
            "OAuth backend initialized with %d provider(s)",
            len(self.providers_config),
        )

    def init_oauth(self, app):
        """Register OAuth providers with the Flask app.

        Must be called after the Flask app is created but before any
        OAuth routes are used.

        Args:
            app: The Flask application instance.
        """
        self._oauth = OAuth(app)

        for name, pconfig in self.providers_config.items():
            well_known = PROVIDER_CONFIGS.get(name, {})

            # Build the registration kwargs
            reg_kwargs = {
                "client_id": self._resolve_env(pconfig.get("client_id", "")),
                "client_secret": self._resolve_env(pconfig.get("client_secret", "")),
            }

            # For well-known providers, use built-in config
            if name == "google":
                reg_kwargs["server_metadata_url"] = well_known["server_metadata_url"]
                reg_kwargs["client_kwargs"] = well_known["client_kwargs"]
            elif name == "github":
                reg_kwargs["api_base_url"] = well_known["api_base_url"]
                reg_kwargs["access_token_url"] = well_known["access_token_url"]
                reg_kwargs["authorize_url"] = well_known["authorize_url"]
                # GitHub needs read:org scope if allowed_org is set
                scope = "user:email"
                if pconfig.get("allowed_org"):
                    scope = "user:email read:org"
                reg_kwargs["client_kwargs"] = {"scope": scope}
            elif name == "oidc" or "discovery_url" in pconfig:
                # Generic OIDC provider
                discovery_url = pconfig.get("discovery_url", "")
                if not discovery_url:
                    raise ValueError(
                        f"OIDC provider '{name}' requires 'discovery_url'"
                    )
                reg_kwargs["server_metadata_url"] = discovery_url
                scopes = pconfig.get("scopes", ["openid", "email", "profile"])
                reg_kwargs["client_kwargs"] = {"scope": " ".join(scopes)}

            self._oauth.register(name, **reg_kwargs)
            logger.info("Registered OAuth provider: %s", name)

    def get_oauth_client(self, provider_name: str):
        """Get the Authlib OAuth client for a provider.

        Args:
            provider_name: The provider key (e.g. 'google', 'github', 'oidc').

        Returns:
            The Authlib OAuth client, or None if provider not found.
        """
        if self._oauth is None:
            logger.error("OAuth not initialized — call init_oauth(app) first")
            return None
        client = getattr(self._oauth, provider_name, None)
        if client is None:
            logger.error("Unknown OAuth provider: %s", provider_name)
        return client

    def get_login_providers(self) -> List[Dict[str, str]]:
        """Return display metadata for all configured providers.

        Used by the login template to render SSO buttons.

        Returns:
            List of dicts with keys: name, display_name, icon_class, button_class, login_url
        """
        providers = []
        for name, meta in self._provider_metadata.items():
            providers.append({
                **meta,
                "login_url": f"/auth/login/{name}",
            })
        return providers

    def extract_user_id(self, profile: Dict[str, Any], provider_name: str = None) -> str:
        """Extract the Potato user identity from an OAuth profile.

        Args:
            profile: The user profile dict from the OAuth provider.
            provider_name: The provider name (for fallback logic).

        Returns:
            The user identity string.

        Raises:
            ValueError: If no usable identity field is found.
        """
        field = self.user_identity_field

        # Try the configured field first
        if field == "email" and profile.get("email"):
            return profile["email"]
        if field == "username":
            # GitHub uses 'login', others may use 'preferred_username'
            for key in ("login", "preferred_username", "username"):
                if profile.get(key):
                    return profile[key]
        if field == "sub" and profile.get("sub"):
            return str(profile["sub"])
        if field == "name" and profile.get("name"):
            return profile["name"]

        # Fallback chain: email -> login -> sub
        if profile.get("email"):
            return profile["email"]
        if profile.get("login"):
            return profile["login"]
        if profile.get("sub"):
            return str(profile["sub"])

        raise ValueError(
            f"Cannot extract user identity from OAuth profile. "
            f"Configured field '{field}' not found, and no fallback available. "
            f"Profile keys: {list(profile.keys())}"
        )

    def check_restrictions(self, provider_name: str, profile: Dict[str, Any]) -> tuple:
        """Check domain/org restrictions for a provider.

        Args:
            provider_name: The provider key.
            profile: The user profile dict.

        Returns:
            Tuple of (allowed: bool, reason: str). reason is empty if allowed.
        """
        pconfig = self.providers_config.get(provider_name, {})

        # Check Google domain restriction
        allowed_domain = pconfig.get("allowed_domain")
        if allowed_domain:
            email = profile.get("email", "")
            domain = email.split("@")[-1] if "@" in email else ""
            if domain.lower() != allowed_domain.lower():
                return False, (
                    f"Access restricted to {allowed_domain} accounts. "
                    f"Your email domain ({domain}) is not allowed."
                )

        # GitHub org restriction is checked separately via API (see routes)
        # We store the config here for routes to use
        # Note: allowed_org check requires an API call with the user's token,
        # which happens in the route handler, not here.

        return True, ""

    # --- AuthBackend interface ---

    def authenticate(self, username: str, password: Optional[str]) -> bool:
        """Authenticate an OAuth user.

        For OAuth, authentication happens via the provider redirect flow,
        not via username/password. This method returns True if the user
        exists (was previously authenticated via OAuth).
        """
        return username in self.users

    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        """Register an OAuth-authenticated user."""
        if username in self.users:
            # Update profile data
            self.users[username].update(kwargs)
            return "Success"
        self.users[username] = kwargs
        return "Success"

    def is_valid_username(self, username: str) -> bool:
        """Check if a username was registered via OAuth."""
        return username in self.users

    def update_password(self, username: str, new_password: str) -> bool:
        """Not supported for OAuth - passwords are managed by providers."""
        raise NotImplementedError("Password management is handled by OAuth providers")

    def get_all_users(self) -> list:
        """Return all registered OAuth usernames."""
        return list(self.users.keys())

    def get_allowed_org(self, provider_name: str) -> Optional[str]:
        """Get the allowed_org restriction for a provider, if any."""
        return self.providers_config.get(provider_name, {}).get("allowed_org")

    # --- Helpers ---

    @staticmethod
    def _resolve_env(value: str) -> str:
        """Resolve ${ENV_VAR} references in a config value."""
        if not isinstance(value, str):
            return value
        if value.startswith("${") and value.endswith("}"):
            env_name = value[2:-1]
            resolved = os.environ.get(env_name, "")
            if not resolved:
                logger.warning(
                    "Environment variable referenced in OAuth config is not set"
                )
            return resolved
        return value
