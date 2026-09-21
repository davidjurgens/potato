"""Flask session configuration — signing key and cookie lifetime.

Split out of ``flask_server.configure_app`` and ``routes.configure_routes``, which
carried byte-identical copies of this logic with two different
``session_lifetime_days`` defaults (2 and 7). Because ``configure_app`` calls
``configure_routes`` and then overwrites the lifetime, the live server got 2 and
the in-process test harness — which builds the app through ``configure_routes``
alone — got 7. Both now go through here.
"""

import logging
import os
import secrets
from datetime import timedelta

logger = logging.getLogger(__name__)

DEFAULT_SESSION_LIFETIME_DAYS = 2


def resolve_secret_key(config: dict):
    """Return the configured Flask signing key, or None to use an ephemeral one.

    Resolution order is ``config["secret_key"]`` then ``POTATO_SECRET_KEY``.

    An explicitly supplied key is honoured whether or not ``persist_sessions`` is
    set. Previously the key was read *only* under ``persist_sessions``, so a
    deployment that set ``POTATO_SECRET_KEY`` and nothing else silently got a
    random per-process key instead — which under more than one server process
    means a session cookie signed by one process is rejected by the others, and
    users get logged out at random.
    """
    return config.get("secret_key") or os.environ.get("POTATO_SECRET_KEY") or None


def configure_session(app, config: dict) -> None:
    """Set ``app.secret_key`` and the permanent-session lifetime from config."""
    secret_key = resolve_secret_key(config)

    if secret_key:
        app.secret_key = secret_key
    elif config.get("persist_sessions", False):
        raise ValueError(
            "persist_sessions is enabled but no secret_key is configured. "
            "Set 'secret_key' in your config file or POTATO_SECRET_KEY environment variable."
        )
    else:
        # No key configured and sessions need not survive a restart: a fresh
        # random key per process is the safe default.
        app.secret_key = secrets.token_hex(32)

    lifetime_days = config.get("session_lifetime_days", DEFAULT_SESSION_LIFETIME_DAYS)
    app.permanent_session_lifetime = timedelta(days=lifetime_days)

    scope_session_cookie_to_prefix(app)


def scope_session_cookie_to_prefix(app) -> None:
    """Scope the session cookie to the deployment prefix.

    Two studies behind one nginx -- ``/app1`` and ``/app2`` on one host -- each
    sign the ``session`` cookie with their own key. Flask scopes that cookie to
    ``SESSION_COOKIE_PATH`` or ``APPLICATION_ROOT``, and both default to ``/``.
    So the browser keeps one cookie for the whole host, each login overwrites
    the other study's cookie, and neither process can verify the other's
    signature. The victim study bounces the annotator back to its login page.
    One study alone never shows this. Adding the second breaks both.

    The prefix reaches Flask as the WSGI ``SCRIPT_NAME``, which both proxy
    mechanisms converge on: ``POTATO_URL_PREFIX`` sets it directly and ProxyFix
    derives it from ``X-Forwarded-Prefix``. ``request.script_root`` surfaces the
    value, so one read covers both. An explicit ``SESSION_COOKIE_PATH`` still
    wins, and a deployment without a prefix keeps ``/``.
    """
    from flask import has_request_context, request
    from flask.sessions import SecureCookieSessionInterface

    # Idempotent: ``configure_routes`` can run more than once on one app in the
    # test harness, and a second wrap would nest the subclass again.
    if getattr(app, "_potato_prefix_scoped_session", False):
        return

    # A deployment that installs a session backend of its own (server-side
    # sessions, for example) owns its own cookie path. So does a stub app that
    # has no session interface at all, which is what the unit tests for key
    # resolution pass in.
    installed = getattr(app, "session_interface", None)
    if installed is None:
        return
    if type(installed) is not SecureCookieSessionInterface and not getattr(
            installed, "_potato_owned", False):
        return

    class _PrefixScopedSessionInterface(type(installed)):
        # Lets Potato's other session override extend this one instead of
        # mistaking it for an interface the deployment supplied.
        _potato_owned = True

        def get_cookie_path(self, app):
            configured = app.config.get("SESSION_COOKIE_PATH")
            if configured:
                return configured
            if has_request_context() and request.script_root:
                return request.script_root
            return super().get_cookie_path(app)

    app.session_interface = _PrefixScopedSessionInterface()
    app._potato_prefix_scoped_session = True
