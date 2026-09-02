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
