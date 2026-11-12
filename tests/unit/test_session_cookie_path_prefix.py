"""The session cookie must be scoped to the deployment prefix.

Two Potato studies behind one nginx (``/app1`` and ``/app2`` on one host) each
sign the ``session`` cookie with their own key. Flask scopes that cookie to
``SESSION_COOKIE_PATH`` or ``APPLICATION_ROOT``, both of which default to ``/``,
so the browser sends one jar to both studies and each login overwrites the
other. Neither process can verify the other's signature, so the victim study
bounces the annotator back to its login page.
"""

from flask import session

# These tests send requests to apps from create_app(). potato.routes registers
# its handlers with module-level @app.route, and Flask refuses that on an app
# that has already served, so a later test that first imports routes fails
# with "The setup method 'route' can no longer be called". Importing it here,
# before any app serves, keeps the invariant documented in create_app().
import potato.routes  # noqa: F401,E402


def _app_that_writes_a_session():
    from potato.flask_server import create_app

    app = create_app()
    app.secret_key = "test-key"
    app.add_url_rule("/_touch-session", "_touch_session", _touch_session)
    return app


def _touch_session():
    session["annotator"] = "user"
    return ""


def _cookie_path(response):
    header = response.headers["Set-Cookie"]
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name.lower() == "path":
            return value
    return None


def test_env_url_prefix_scopes_the_session_cookie(monkeypatch):
    monkeypatch.delenv("POTATO_PROXY_FIX", raising=False)
    monkeypatch.setenv("POTATO_URL_PREFIX", "/app1")

    app = _app_that_writes_a_session()
    response = app.test_client().get("/_touch-session")

    assert _cookie_path(response) == "/app1"


def test_forwarded_prefix_scopes_the_session_cookie(monkeypatch):
    monkeypatch.delenv("POTATO_URL_PREFIX", raising=False)
    monkeypatch.setenv("POTATO_PROXY_FIX", "1")

    app = _app_that_writes_a_session()
    response = app.test_client().get(
        "/_touch-session", headers={"X-Forwarded-Prefix": "/round1"}
    )

    assert _cookie_path(response) == "/round1"


def test_no_prefix_keeps_the_cookie_at_the_root(monkeypatch):
    monkeypatch.delenv("POTATO_PROXY_FIX", raising=False)
    monkeypatch.delenv("POTATO_URL_PREFIX", raising=False)

    app = _app_that_writes_a_session()
    response = app.test_client().get("/_touch-session")

    assert _cookie_path(response) == "/"
