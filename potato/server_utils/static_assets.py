"""Content-addressed caching for the app's /static assets.

Every annotation page loads ~40 scripts and stylesheets from /static. They were
served ``Cache-Control: no-cache``, so each page load asked the server about
every one of them again. Each answer was a 304, but each question still cost a
round trip -- on an 80 ms link that was most of the "Loading annotation
interface" time between instances.

Long-lived caching was unsafe as long as a URL did not change when its file
did: the templates carry hand-bumped ``?v=N`` numbers, and a forgotten bump
would have pinned annotators to stale JavaScript for a year. So the cache is
keyed on content instead:

- rendered HTML gets ``h=<content hash>`` added to every ``<script src>`` and
  ``<link href>`` that points into the app's static folder;
- the static route answers ``immutable`` with a year's max-age only when the
  request's ``h`` matches the file's current hash. A stale or missing ``h``
  gets today's ``no-cache``, so an edited file is never served from cache.

Pages are ``no-store``, so every navigation fetches fresh HTML with the current
hashes, and an edit shows up on the next page load.
"""

import hashlib
import logging
import os
import posixpath
import re
import threading
from urllib.parse import unquote

from werkzeug.security import safe_join

logger = logging.getLogger(__name__)

#: One year: the longest max-age browsers honour. Safe because the URL changes
#: whenever the content does.
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"

#: Query parameter carrying the content hash. Separate from the templates' own
#: ``v=`` so neither scheme has to know about the other.
HASH_PARAM = "h"

#: HTML larger than this is left alone; no template renders anything near it.
_MAX_REWRITE_BYTES = 5 * 1024 * 1024

# A <script ... src="..."> or <link ... href="..."> tag. Only these two tags:
# they are what a page load waits on, and matching bare `src=` anywhere would
# also rewrite URL strings inside inline JavaScript that the code then
# concatenates onto.
_TAG_RE = re.compile(
    r"""(<(?:script|link)\b[^<>]*?\s(?:src|href)=)(["'])([^"'<>]*)\2""",
    re.IGNORECASE,
)

# A relative reference inside a stylesheet: `@import url('x.css')`,
# `@import 'x.css'`, or `url(x.woff2)`. Group 3 is the reference itself.
# Comments are matched as the first alternative so the reference pattern never
# runs inside one: prose like "an @import is invisible" in a comment would
# otherwise read as a reference to a file called `is`. A comment match has
# group 3 unset. An unterminated comment runs to the end of the file, as it
# does for the browser.
_CSS_REF_RE = re.compile(
    r"""/\*.*?(?:\*/|\Z)|(@import\s+(?:url\(\s*)?|url\(\s*)(["']?)([^"')\s]+)\2""",
    re.IGNORECASE | re.DOTALL,
)

#: path -> ((mtime_ns, size), content_hash, css_refs)
_file_digests = {}
_digest_lock = threading.Lock()


def _file_digest(path):
    """(content hash, static-relative refs if a stylesheet), cached on mtime+size."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not os.path.isfile(path):
        return None
    key = (st.st_mtime_ns, st.st_size)
    with _digest_lock:
        cached = _file_digests.get(path)
        if cached and cached[0] == key:
            return cached[1], cached[2]
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    refs = ()
    if path.endswith(".css"):
        text = data.decode("utf-8", errors="replace")
        refs = tuple(m.group(3) for m in _CSS_REF_RE.finditer(text) if m.group(3))
    value = hashlib.sha1(data).hexdigest()
    with _digest_lock:
        _file_digests[path] = (key, value, refs)
    return value, refs


def _resolve_css_ref(filename, ref):
    """Static-relative path a stylesheet's relative reference points at, or None."""
    if not ref or ref.startswith(("data:", "#", "/")) or "://" in ref or ref.startswith("//"):
        return None
    ref_path = ref.split("#", 1)[0].split("?", 1)[0]
    if not ref_path:
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(filename), unquote(ref_path)))
    if joined.startswith("../") or joined == "..":
        return None
    return joined


def fingerprint(static_folder, filename, _seen=None):
    """Short content hash of ``static_folder/filename``, or None.

    None for anything that is not a regular file inside the static folder,
    including traversal attempts. An edited file gets a new hash on the next
    page render without a restart.

    A stylesheet's hash also covers the files it references with ``@import``
    and ``url()``, because it is served with those references hashed (see
    :func:`hash_css_references`). Without that, a changed font would leave the
    stylesheet's URL unchanged and browsers would keep the old one for a year.
    """
    if not static_folder or not filename:
        return None
    path = safe_join(static_folder, filename)
    if path is None:
        return None
    digest = _file_digest(path)
    if digest is None:
        return None
    content_hash, refs = digest
    if not refs:
        return content_hash[:12]
    seen = (_seen or set()) | {filename}
    combined = hashlib.sha1(content_hash.encode())
    for ref in refs:
        target = _resolve_css_ref(filename, ref)
        if target is None or target in seen:
            continue
        combined.update(b"\0" + target.encode() + b"=" +
                        (fingerprint(static_folder, target, seen) or "-").encode())
    return combined.hexdigest()[:12]


def hash_css_references(css, static_folder, filename):
    """Add ``h=<hash>`` to a stylesheet's relative ``@import``/``url()`` references."""

    def replace(match):
        prefix, quote, ref = match.group(1), match.group(2), match.group(3)
        if ref is None:  # a comment
            return match.group(0)
        target = _resolve_css_ref(filename, ref)
        if target is None:
            return match.group(0)
        base, _, fragment = ref.partition("#")
        path, _, query = base.partition("?")
        params = [p for p in query.split("&") if p] if query else []
        if any(p.split("=", 1)[0] == HASH_PARAM for p in params):
            return match.group(0)
        fp = fingerprint(static_folder, target)
        if fp is None:
            return match.group(0)
        params.append(f"{HASH_PARAM}={fp}")
        new_ref = path + "?" + "&".join(params) + (("#" + fragment) if fragment else "")
        return f"{prefix}{quote}{new_ref}{quote}"

    return _CSS_REF_RE.sub(replace, css)


def _static_filename(url, static_prefixes):
    """The static-folder-relative filename a URL points at, or None."""
    path = url.split("#", 1)[0].split("?", 1)[0]
    for prefix in static_prefixes:
        if path.startswith(prefix):
            return unquote(path[len(prefix):])
    return None


def add_fingerprints(html, static_folder, static_prefixes):
    """Add ``h=<hash>`` to static script/stylesheet URLs in ``html``.

    ``static_prefixes`` are the URL path prefixes that mean "the app's static
    folder" (``/static/``, and the deployment prefix form of it). URLs under any
    other path -- a blueprint's own static folder, a CDN -- are left alone, as
    are files that do not exist and URLs that already carry an ``h``.
    """
    if not html or "static/" not in html:
        return html

    def replace(match):
        head, quote, url = match.group(1), match.group(2), match.group(3)
        filename = _static_filename(url, static_prefixes)
        if filename is None:
            return match.group(0)
        base, _, fragment = url.partition("#")
        path, _, query = base.partition("?")
        params = [p for p in query.split("&") if p] if query else []
        if any(p.split("=", 1)[0] == HASH_PARAM for p in params):
            return match.group(0)
        fp = fingerprint(static_folder, filename)
        if fp is None:
            return match.group(0)
        params.append(f"{HASH_PARAM}={fp}")
        new_url = path + "?" + "&".join(params) + (("#" + fragment) if fragment else "")
        return f"{head}{quote}{new_url}{quote}"

    return _TAG_RE.sub(replace, html)


def _static_prefixes(app, script_root):
    static_url_path = (app.static_url_path or "/static").rstrip("/") + "/"
    prefixes = [static_url_path]
    if script_root:
        prefixes.insert(0, script_root.rstrip("/") + static_url_path)
    return prefixes


def register_static_asset_caching(app):
    """Install the HTML rewrite and the static-route cache headers on ``app``.

    Idempotent: ``configure_routes`` can run more than once on one app in the
    test harness, and a second hook would hash every URL twice.
    """
    if getattr(app, "_potato_static_caching", False):
        return
    app._potato_static_caching = True

    from flask import request

    _skip_session_cookie_on_static(app)

    @app.after_request
    def _potato_static_asset_caching(response):
        try:
            if request.endpoint == "static":
                _apply_static_cache_headers(app, response)
            elif _should_rewrite(response):
                html = response.get_data(as_text=True)
                rewritten = add_fingerprints(
                    html, app.static_folder,
                    _static_prefixes(app, request.script_root))
                if rewritten != html:
                    response.set_data(rewritten)
        except Exception:  # pragma: no cover - never break a response over caching
            logger.debug("static asset caching skipped", exc_info=True)
        return response


def _skip_session_cookie_on_static(app):
    """Leave the session cookie off static responses.

    Logins mark the session permanent, and Flask re-signs a permanent session's
    cookie on every response (``SESSION_REFRESH_EACH_REQUEST``). So a year-long
    ``public, immutable`` stylesheet also carried ``Set-Cookie`` with that
    user's session and ``Vary: Cookie``. The Vary made browsers drop the cached
    copy whenever the cookie changed, which it did on every response, so after
    a browser restart 24 of 28 assets came back over the network. A shared
    cache that ignored Vary would have stored one user's session under a public
    URL.

    The page request that loads the assets refreshes the cookie anyway, so
    nothing is lost by not doing it again for each asset. Flask's default
    interface is extended, and so is one Potato installed itself --
    ``configure_session`` scopes the cookie to the deployment prefix before this
    runs, and both overrides have to survive. An interface the deployment
    supplied is left as it is.
    """
    from flask import request
    from flask.sessions import SecureCookieSessionInterface

    installed = app.session_interface
    if type(installed) is not SecureCookieSessionInterface and not getattr(
            installed, "_potato_owned", False):
        return

    class _StaticSkippingSessionInterface(type(installed)):
        _potato_owned = True

        def save_session(self, app, session, response):
            if request.endpoint == "static":
                return None
            return super().save_session(app, session, response)

    app.session_interface = _StaticSkippingSessionInterface()


def _should_rewrite(response):
    return (
        response.mimetype == "text/html"
        and not response.direct_passthrough
        and not response.is_streamed
        and "Content-Encoding" not in response.headers
        and (response.content_length or 0) <= _MAX_REWRITE_BYTES
    )


def _apply_static_cache_headers(app, response):
    from flask import request

    if response.status_code not in (200, 206, 304, 416):
        return
    requested = request.args.get(HASH_PARAM)
    if not requested:
        return
    filename = (request.view_args or {}).get("filename")
    if requested != fingerprint(app.static_folder, filename):
        return
    if response.status_code in (200, 206, 416) and filename.endswith(".css"):
        path = safe_join(app.static_folder, filename)
        with open(path, "rb") as f:
            css = f.read().decode("utf-8", errors="replace")
        rewritten = hash_css_references(css, app.static_folder, filename)
        if rewritten != css:
            # send_file handed over an open file; release it before replacing it.
            close = getattr(response.response, "close", None)
            if close is not None:
                close()
            response.direct_passthrough = False
            # A byte range was computed against the file on disk, which is not
            # the body served here: a range past the file's end got 416 though
            # the rewritten body is longer. Ignoring Range and answering 200
            # with the whole body is always allowed.
            if response.status_code in (206, 416):
                response.status_code = 200
                response.headers.pop("Content-Range", None)
                response.mimetype = "text/css"  # a 416 arrives as an error page
            response.headers.pop("Accept-Ranges", None)
            response.set_data(rewritten)
            # The file's ETag no longer describes this body. Nothing
            # revalidates an immutable response, so drop it rather than lie.
            response.headers.pop("ETag", None)
    if response.status_code == 416:
        return  # a genuine out-of-range request; not a cacheable body
    response.headers["Cache-Control"] = IMMUTABLE_CACHE_CONTROL
