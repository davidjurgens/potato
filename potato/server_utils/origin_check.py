"""Same-origin check for state-changing routes (a CSRF defence).

Browsers attach ``Origin`` (and usually ``Referer``) to a cross-site POST, and a
page on another site cannot forge either. A request is same-origin when the
scheme, host and port of that header equal the ones this request was served
on. The comparison is on the parsed origin, never a string prefix: a prefix
test lets ``http://localhost:8000.evil.example`` through as ``http://localhost:8000``.

Requests with neither header are allowed. They come from scripts and the
command line (an admin with ``X-API-Key``), which a browser cannot be tricked
into sending on someone else's behalf.
"""

from functools import wraps
from urllib.parse import urlsplit

from flask import jsonify, request

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_tuple(url):
    """``(scheme, host, port)`` of a URL, or None when it has no host."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    scheme = parts.scheme.lower()
    return scheme, parts.hostname.lower(), port or _DEFAULT_PORTS.get(scheme)


def is_same_origin(req=None) -> bool:
    """True unless the request's Origin or Referer names a different origin."""
    req = req or request
    origin = req.headers.get("Origin")
    referer = req.headers.get("Referer")
    if not origin and not referer:
        return True
    ours = _origin_tuple(req.host_url)
    # "Origin: null" (sandboxed frames, some redirects) is not our origin.
    if origin and _origin_tuple(origin) != ours:
        return False
    if referer and _origin_tuple(referer) != ours:
        return False
    return True


def same_origin_required(f):
    """Refuse a cross-origin request with 403 before the view runs."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_same_origin():
            return jsonify({"error": "Cross-origin request rejected"}), 403
        return f(*args, **kwargs)

    return decorated_function
