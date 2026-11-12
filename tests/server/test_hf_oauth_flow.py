"""
Sign in with Hugging Face, through the real routes, as a Space runs it.

The provider was listed but never registered with its OpenID metadata, so
/auth/login/huggingface failed before reaching Hugging Face. Here the server
starts with the environment a Space with `hf_oauth: true` gets
(OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OAUTH_SCOPES, OPENID_PROVIDER_URL,
SPACE_HOST) and a provider entry with nothing in it.

The server runs in-process, so Authlib's two network calls are replaced: the
discovery document fetch and the code-for-token exchange. Everything between
them (registration, the redirect it builds, the callback, the session) is
the code under test.
"""

import os
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from authlib.integrations.base_client.sync_app import OAuth2Mixin
from authlib.integrations.flask_client.apps import FlaskOAuth2App

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.oauth_test_utils import make_oauth_config
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

SPACE_ENV = {
    "OAUTH_CLIENT_ID": "space-client-id",
    "OAUTH_CLIENT_SECRET": "space-client-secret",
    "OAUTH_SCOPES": "openid profile",
    "OPENID_PROVIDER_URL": "https://hf.example",
    "SPACE_HOST": "lab-pilot.hf.space",
}
METADATA = {
    "issuer": "https://hf.example",
    "authorization_endpoint": "https://hf.example/oauth/authorize",
    "token_endpoint": "https://hf.example/oauth/token",
    "userinfo_endpoint": "https://hf.example/oauth/userinfo",
    "jwks_uri": "https://hf.example/oauth/jwks",
}
SCHEMES = [{"annotation_type": "radio", "name": "sentiment",
            "description": "Sentiment", "labels": ["positive", "negative"]}]


@pytest.fixture
def hub(monkeypatch):
    """Stand in for huggingface.co: record the discovery URL, answer tokens."""
    seen = {"metadata_urls": [], "userinfo": None}

    def load_server_metadata(self):
        seen["metadata_urls"].append(self._server_metadata_url)
        self.server_metadata.update(METADATA)
        return self.server_metadata

    def authorize_access_token(self, **kwargs):
        return {"access_token": "hf_oauth_x", "token_type": "bearer",
                "userinfo": seen["userinfo"]}

    monkeypatch.setattr(OAuth2Mixin, "load_server_metadata", load_server_metadata)
    monkeypatch.setattr(FlaskOAuth2App, "authorize_access_token", authorize_access_token)
    return seen


def _server(name, provider_entry):
    for key, value in SPACE_ENV.items():
        os.environ[key] = value
    test_dir = create_test_directory(name)
    data = create_test_data_file(test_dir, [{"id": "a", "text": "One."},
                                            {"id": "b", "text": "Two."}])
    config = create_test_config(
        test_dir, SCHEMES, data_files=[data],
        authentication=make_oauth_config({"huggingface": provider_entry},
                                         user_identity_field="sub"),
        require_password=False, secret_key="hf-oauth-test")
    server = FlaskTestServer(config_file=config)
    if not server.start():
        pytest.fail("server did not start")
    return server, test_dir


@pytest.fixture
def space(hub):
    server, test_dir = _server("hf_oauth_space", {})
    yield server
    server.stop()
    cleanup_test_directory(test_dir)
    for key in SPACE_ENV:
        os.environ.pop(key, None)


@pytest.fixture
def org_space(hub):
    server, test_dir = _server("hf_oauth_org", {"allowed_org": "lab"})
    yield server
    server.stop()
    cleanup_test_directory(test_dir)
    for key in SPACE_ENV:
        os.environ.pop(key, None)


def _start_sign_in(server):
    s = requests.Session()
    r = s.get(f"{server.base_url}/auth/login/huggingface", allow_redirects=False,
              timeout=10)
    assert r.status_code == 302, r.text[:300]
    return s, urlparse(r.headers["Location"])


def test_the_sign_in_goes_to_hugging_face_with_the_spaces_app(space, hub):
    _s, location = _start_sign_in(space)
    query = parse_qs(location.query)
    assert f"{location.scheme}://{location.netloc}{location.path}" == \
        "https://hf.example/oauth/authorize"
    assert query["client_id"] == ["space-client-id"]
    assert query["redirect_uri"] == ["https://lab-pilot.hf.space/auth/callback/huggingface"]
    assert query["scope"] == ["openid profile"]
    assert hub["metadata_urls"][-1] == "https://hf.example/.well-known/openid-configuration"


def test_the_callback_signs_the_annotator_in_by_account_id(space, hub):
    s, _location = _start_sign_in(space)
    hub["userinfo"] = {"sub": "64f0c0ffee", "preferred_username": "ada",
                       "name": "Ada L."}
    r = s.get(f"{space.base_url}/auth/callback/huggingface?code=c&state=x",
              allow_redirects=True, timeout=10)
    assert r.status_code == 200
    page = s.get(f"{space.base_url}/annotate", timeout=10)
    assert page.status_code == 200
    assert 'id="instance_id"' in page.text
    from potato.user_state_management import get_user_state_manager
    assert get_user_state_manager().has_user("64f0c0ffee")
    assert not get_user_state_manager().has_user("ada")


def test_an_organization_limit_asks_for_memberships_and_refuses_outsiders(org_space, hub):
    _s, location = _start_sign_in(org_space)
    assert parse_qs(location.query)["scope"] == ["openid profile read-memberships"]

    outsider, _ = _start_sign_in(org_space)
    hub["userinfo"] = {"sub": "1", "preferred_username": "eve",
                       "orgs": [{"preferred_username": "x123", "name": "lab"}]}
    r = outsider.get(f"{org_space.base_url}/auth/callback/huggingface?code=c&state=x",
                     timeout=10)
    assert r.status_code == 403
    assert "lab" in r.text

    member, _ = _start_sign_in(org_space)
    hub["userinfo"] = {"sub": "2", "preferred_username": "grace",
                       "orgs": [{"preferred_username": "Lab", "name": "The Lab"}]}
    r = member.get(f"{org_space.base_url}/auth/callback/huggingface?code=c&state=x",
                   timeout=10)
    assert r.status_code == 200
    assert 'id="instance_id"' in member.get(f"{org_space.base_url}/annotate",
                                            timeout=10).text
