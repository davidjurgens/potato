"""Shared utilities for OAuth testing — mock responses, config helpers."""

import responses

# --- Mock Response Data ---

GOOGLE_TOKEN_RESPONSE = {
    "access_token": "fake-google-access-token",
    "expires_in": 3600,
    "token_type": "Bearer",
    "id_token": "fake-id-token",
}

GOOGLE_USERINFO_RESPONSE = {
    "sub": "google-user-12345",
    "email": "testuser@example.com",
    "email_verified": True,
    "name": "Test User",
    "picture": "https://example.com/photo.jpg",
}

GITHUB_TOKEN_RESPONSE = {
    "access_token": "fake-github-access-token",
    "token_type": "bearer",
    "scope": "user:email",
}

GITHUB_USER_RESPONSE = {
    "login": "testuser",
    "id": 67890,
    "email": "testuser@example.com",
    "name": "Test User",
    "avatar_url": "https://avatars.githubusercontent.com/u/67890",
}

GITHUB_EMAILS_RESPONSE = [
    {"email": "testuser@example.com", "primary": True, "verified": True},
    {"email": "test@users.noreply.github.com", "primary": False, "verified": True},
]

OIDC_DISCOVERY_RESPONSE = {
    "issuer": "https://sso.example.com",
    "authorization_endpoint": "https://sso.example.com/authorize",
    "token_endpoint": "https://sso.example.com/token",
    "userinfo_endpoint": "https://sso.example.com/userinfo",
    "jwks_uri": "https://sso.example.com/.well-known/jwks.json",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
}


def mock_google_endpoints(email="testuser@example.com", name="Test User"):
    """Register mocked Google OAuth endpoints with the `responses` library."""
    userinfo = {**GOOGLE_USERINFO_RESPONSE, "email": email, "name": name}
    responses.post(
        "https://oauth2.googleapis.com/token",
        json=GOOGLE_TOKEN_RESPONSE,
        status=200,
    )
    responses.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        json=userinfo,
        status=200,
    )


def mock_github_endpoints(login="testuser", email="testuser@example.com"):
    """Register mocked GitHub OAuth endpoints."""
    user = {**GITHUB_USER_RESPONSE, "login": login, "email": email}
    responses.post(
        "https://github.com/login/oauth/access_token",
        json=GITHUB_TOKEN_RESPONSE,
        status=200,
    )
    responses.get("https://api.github.com/user", json=user, status=200)


def mock_github_emails(emails=None):
    """Register mocked GitHub emails endpoint."""
    responses.get(
        "https://api.github.com/user/emails",
        json=emails or GITHUB_EMAILS_RESPONSE,
        status=200,
    )


def mock_github_orgs(orgs=None):
    """Register mocked GitHub orgs endpoint."""
    if orgs is None:
        orgs = [{"login": "my-research-lab"}]
    responses.get("https://api.github.com/user/orgs", json=orgs, status=200)


def mock_oidc_discovery(issuer="https://sso.example.com"):
    """Register mocked OIDC discovery endpoint."""
    discovery = {**OIDC_DISCOVERY_RESPONSE, "issuer": issuer}
    responses.get(
        f"{issuer}/.well-known/openid-configuration",
        json=discovery,
        status=200,
    )


def make_oauth_config(
    providers,
    user_identity_field="email",
    allow_local_login=False,
    auto_register=True,
):
    """Build an authentication config dict for testing.

    Args:
        providers: Dict of provider configs.
        user_identity_field: Which field to use as user ID.
        allow_local_login: Whether local login is also allowed.
        auto_register: Whether new OAuth users are auto-registered.

    Returns:
        Dict suitable for passing as the 'authentication' config section.
    """
    return {
        "method": "oauth",
        "providers": providers,
        "user_identity_field": user_identity_field,
        "allow_local_login": allow_local_login,
        "auto_register": auto_register,
    }


def google_provider(client_id="fake-google-id", client_secret="fake-google-secret",
                    allowed_domain=None):
    """Build a Google provider config dict."""
    config = {"client_id": client_id, "client_secret": client_secret}
    if allowed_domain:
        config["allowed_domain"] = allowed_domain
    return config


def github_provider(client_id="fake-github-id", client_secret="fake-github-secret",
                    allowed_org=None):
    """Build a GitHub provider config dict."""
    config = {"client_id": client_id, "client_secret": client_secret}
    if allowed_org:
        config["allowed_org"] = allowed_org
    return config


def oidc_provider(
    display_name="Test SSO",
    discovery_url="https://sso.example.com/.well-known/openid-configuration",
    client_id="fake-oidc-id",
    client_secret="fake-oidc-secret",
):
    """Build a generic OIDC provider config dict."""
    return {
        "display_name": display_name,
        "discovery_url": discovery_url,
        "client_id": client_id,
        "client_secret": client_secret,
    }
