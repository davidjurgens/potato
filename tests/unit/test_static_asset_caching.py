"""Content-addressed caching of /static assets.

Static files used to be served ``no-cache``: every page load revalidated all ~40
scripts and stylesheets, one round trip each, which was most of the time the
"Loading annotation interface" screen stayed up between instances on a real
network. Pages now carry a content hash on each asset URL, and the static route
answers ``immutable`` only when that hash matches the file on disk.

The property that matters is the second half: an edited file must never be
served from cache. These tests pin both halves through a real Flask app.
"""

import os
import re

import pytest
from flask import Flask, make_response

from potato.server_utils.static_assets import (
    HASH_PARAM,
    IMMUTABLE_CACHE_CONTROL,
    add_fingerprints,
    fingerprint,
    register_static_asset_caching,
)


@pytest.fixture
def static_dir(tmp_path):
    d = tmp_path / "static"
    (d / "css").mkdir(parents=True)
    (d / "app.js").write_text("console.log('one');")
    (d / "css" / "site.css").write_text("body { color: red; }")
    (d / "vendor" / "font" / "files").mkdir(parents=True)
    (d / "vendor" / "font" / "font.css").write_text(
        "@font-face { src: url(files/a.woff2) format('woff2'); }\n"
        ".x { background: url(\"data:image/png;base64,AAAA\"); }\n"
        ".y { background: url('../../../outside.png'); }\n")
    (d / "vendor" / "font" / "files" / "a.woff2").write_bytes(b"font-v1")
    (d / "main.css").write_text("@import url('vendor/font/font.css');\nbody { margin: 0; }\n")
    return d


PAGE = """<html><head>
<link rel="stylesheet" href="{prefix}/static/css/site.css?v=3">
<script src="{prefix}/static/app.js?v=44"></script>
<script src="{prefix}/static/missing.js?v=1"></script>
<script src="https://cdn.example.org/static/app.js"></script>
<script src="{prefix}/pocket/static/app.js"></script>
</head><body>
<script>var s = document.createElement('script'); s.src = "{prefix}/static/app.js" + "?v=2";</script>
</body></html>"""


@pytest.fixture
def app(static_dir):
    app = Flask(__name__, static_folder=str(static_dir))

    @app.route("/page")
    def page():
        from flask import request
        return PAGE.format(prefix=request.script_root)

    @app.route("/json")
    def json_route():
        return {"url": "/static/app.js"}

    @app.route("/download")
    def download():
        resp = make_response('<script src="/static/app.js"></script>')
        resp.mimetype = "text/html"
        resp.direct_passthrough = True
        return resp

    register_static_asset_caching(app)
    return app


def _hash_of(html, url_up_to_hash):
    """The hash that follows ``url_up_to_hash`` (e.g. ``/static/a.js?v=1&``)."""
    m = re.search(re.escape(url_up_to_hash) + HASH_PARAM + r"=([0-9a-f]+)", html)
    return m.group(1) if m else None


class TestFingerprint:

    def test_changes_when_the_file_changes(self, static_dir):
        before = fingerprint(str(static_dir), "app.js")
        path = static_dir / "app.js"
        path.write_text("console.log('two, a longer body');")
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10_000_000))
        assert fingerprint(str(static_dir), "app.js") != before

    def test_stable_for_unchanged_content(self, static_dir):
        assert fingerprint(str(static_dir), "app.js") == fingerprint(str(static_dir), "app.js")

    @pytest.mark.parametrize("name", ["missing.js", "../static/app.js", "../../etc/passwd", "css", ""])
    def test_none_for_anything_but_a_file_in_the_folder(self, static_dir, name):
        assert fingerprint(str(static_dir), name) is None


class TestRewrite:

    def test_static_tags_get_the_hash_and_keep_their_version(self, app, static_dir):
        html = app.test_client().get("/page").get_data(as_text=True)
        assert _hash_of(html, "/static/app.js?v=44&") == fingerprint(str(static_dir), "app.js")
        assert _hash_of(html, "/static/css/site.css?v=3&") == fingerprint(str(static_dir), "css/site.css")

    def test_leaves_urls_it_cannot_vouch_for(self, app):
        html = app.test_client().get("/page").get_data(as_text=True)
        assert '/static/missing.js?v=1"' in html
        assert '"https://cdn.example.org/static/app.js"' in html
        assert '"/pocket/static/app.js"' in html

    def test_leaves_inline_javascript_strings_alone(self, app):
        # The code appends its own query; a hash added here would produce
        # `app.js?h=...?v=2`.
        html = app.test_client().get("/page").get_data(as_text=True)
        assert 's.src = "/static/app.js" + "?v=2"' in html

    def test_script_root_prefix_is_recognised(self, app, static_dir):
        html = app.test_client().get(
            "/page", environ_overrides={"SCRIPT_NAME": "/app1"}).get_data(as_text=True)
        assert _hash_of(html, "/app1/static/app.js?v=44&") == fingerprint(str(static_dir), "app.js")

    def test_non_html_and_passthrough_responses_untouched(self, app):
        client = app.test_client()
        assert HASH_PARAM + "=" not in client.get("/json").get_data(as_text=True)
        assert HASH_PARAM + "=" not in client.get("/download").get_data(as_text=True)

    def test_idempotent(self, static_dir):
        once = add_fingerprints('<script src="/static/app.js"></script>', str(static_dir), ["/static/"])
        assert add_fingerprints(once, str(static_dir), ["/static/"]) == once

    def test_registering_twice_does_not_double_hash(self, app):
        register_static_asset_caching(app)
        html = app.test_client().get("/page").get_data(as_text=True)
        assert html.count(HASH_PARAM + "=") == 2


class TestStaticRouteHeaders:

    def test_matching_hash_is_immutable(self, app, static_dir):
        fp = fingerprint(str(static_dir), "app.js")
        resp = app.test_client().get(f"/static/app.js?v=44&{HASH_PARAM}={fp}")
        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == IMMUTABLE_CACHE_CONTROL

    def test_stale_hash_is_revalidated(self, app):
        resp = app.test_client().get(f"/static/app.js?{HASH_PARAM}=000000000000")
        assert resp.headers["Cache-Control"] == "no-cache"

    def test_no_hash_keeps_the_old_behaviour(self, app):
        resp = app.test_client().get("/static/app.js?v=44")
        assert resp.headers["Cache-Control"] == "no-cache"

    def test_an_edit_is_never_served_as_immutable_under_the_old_url(self, app, static_dir):
        client = app.test_client()
        old = fingerprint(str(static_dir), "app.js")
        path = static_dir / "app.js"
        path.write_text("console.log('edited');  // different size")
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10_000_000))

        stale = client.get(f"/static/app.js?{HASH_PARAM}={old}")
        assert stale.headers["Cache-Control"] == "no-cache"
        assert "edited" in stale.get_data(as_text=True)

        html = client.get("/page").get_data(as_text=True)
        new = _hash_of(html, "/static/app.js?v=44&")
        assert new != old
        fresh = client.get(f"/static/app.js?{HASH_PARAM}={new}")
        assert fresh.headers["Cache-Control"] == IMMUTABLE_CACHE_CONTROL


class TestStylesheetReferences:
    """`styles.css` pulls the Outfit font in with `@import`, and the font files
    come in through `url()` inside that. Neither is a <link> tag, so without
    this both were revalidated on every page: one render-blocking round trip
    for the import and one more for the font.
    """

    def _touch(self, path, data):
        path.write_bytes(data)
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))

    def test_served_stylesheet_hashes_its_imports_and_fonts(self, app, static_dir):
        client = app.test_client()
        fp = fingerprint(str(static_dir), "main.css")
        css = client.get(f"/static/main.css?{HASH_PARAM}={fp}").get_data(as_text=True)
        font_css_fp = fingerprint(str(static_dir), "vendor/font/font.css")
        assert f"@import url('vendor/font/font.css?{HASH_PARAM}={font_css_fp}')" in css

        font_css = client.get(f"/static/vendor/font/font.css?{HASH_PARAM}={font_css_fp}")
        body = font_css.get_data(as_text=True)
        woff_fp = fingerprint(str(static_dir), "vendor/font/files/a.woff2")
        assert f"url(files/a.woff2?{HASH_PARAM}={woff_fp})" in body
        assert font_css.headers["Cache-Control"] == IMMUTABLE_CACHE_CONTROL

        woff = client.get(f"/static/vendor/font/files/a.woff2?{HASH_PARAM}={woff_fp}")
        assert woff.headers["Cache-Control"] == IMMUTABLE_CACHE_CONTROL

    def test_data_uris_and_escaping_refs_are_left_alone(self, app, static_dir):
        fp = fingerprint(str(static_dir), "vendor/font/font.css")
        body = app.test_client().get(
            f"/static/vendor/font/font.css?{HASH_PARAM}={fp}").get_data(as_text=True)
        assert 'url("data:image/png;base64,AAAA")' in body
        assert "url('../../../outside.png')" in body

    def test_a_changed_font_changes_every_stylesheet_above_it(self, static_dir):
        # The stylesheet is cached for a year under its own hash; if that hash
        # ignored the font, a new font would never reach a returning browser.
        before_font_css = fingerprint(str(static_dir), "vendor/font/font.css")
        before_main = fingerprint(str(static_dir), "main.css")
        self._touch(static_dir / "vendor" / "font" / "files" / "a.woff2", b"font-v2, longer")
        assert fingerprint(str(static_dir), "vendor/font/font.css") != before_font_css
        assert fingerprint(str(static_dir), "main.css") != before_main

    def test_import_cycle_terminates(self, static_dir):
        (static_dir / "a.css").write_text("@import 'b.css';")
        (static_dir / "b.css").write_text("@import 'a.css';")
        assert fingerprint(str(static_dir), "a.css")

    def test_unhashed_stylesheet_is_served_untouched(self, app, static_dir):
        body = app.test_client().get("/static/main.css").get_data(as_text=True)
        assert body == (static_dir / "main.css").read_text()

    def test_references_inside_comments_are_ignored(self, static_dir):
        # styles.css explains itself in a comment containing "an @import is
        # invisible ...", which read as a reference to a file named `is`.
        (static_dir / "commented.css").write_text(
            "/* the @import 'css/site.css' that used to be here,\n"
            "   and url(app.js), are history */\n"
            "body { margin: 0; }\n")
        before = fingerprint(str(static_dir), "commented.css")
        self._touch(static_dir / "css" / "site.css", b"body { color: blue; } /* v2 */")
        self._touch(static_dir / "app.js", b"console.log('two, longer');")
        assert fingerprint(str(static_dir), "commented.css") == before

    def test_comments_are_served_unrewritten(self, app, static_dir):
        comment = "/* @import url('css/site.css') */"
        (static_dir / "withcomment.css").write_text(
            comment + "\n@import url('css/site.css');\n")
        fp = fingerprint(str(static_dir), "withcomment.css")
        body = app.test_client().get(
            f"/static/withcomment.css?{HASH_PARAM}={fp}").get_data(as_text=True)
        assert body.startswith(comment + "\n")
        site_fp = fingerprint(str(static_dir), "css/site.css")
        assert f"@import url('css/site.css?{HASH_PARAM}={site_fp}');" in body

    def test_a_range_request_gets_the_whole_rewritten_body(self, app, static_dir):
        # The range would be computed against the file on disk, not the body
        # served, so the server ignores Range and answers 200.
        client = app.test_client()
        url = f"/static/main.css?{HASH_PARAM}={fingerprint(str(static_dir), 'main.css')}"
        full = client.get(url)
        ranged = client.get(url, headers={"Range": "bytes=0-9"})
        assert ranged.status_code == 200
        assert "Content-Range" not in ranged.headers
        assert ranged.get_data() == full.get_data()
        assert ranged.headers["Content-Length"] == str(len(full.get_data()))

    def test_a_range_past_the_file_on_disk_gets_the_whole_rewritten_body(self, app, static_dir):
        # The rewritten body is longer than the file, so a range that starts
        # past the file's end is inside the body served, yet was answered 416.
        client = app.test_client()
        url = f"/static/main.css?{HASH_PARAM}={fingerprint(str(static_dir), 'main.css')}"
        full = client.get(url)
        on_disk = (static_dir / "main.css").stat().st_size
        assert len(full.get_data()) > on_disk
        ranged = client.get(url, headers={"Range": f"bytes={on_disk}-"})
        assert ranged.status_code == 200
        assert ranged.get_data() == full.get_data()
        assert ranged.mimetype == "text/css"
        assert "Content-Range" not in ranged.headers
        assert ranged.headers["Cache-Control"] == IMMUTABLE_CACHE_CONTROL

    def test_a_range_past_an_unrewritten_stylesheet_is_still_416(self, app, static_dir):
        (static_dir / "plain.css").write_text("body { margin: 0; }\n")
        url = f"/static/plain.css?{HASH_PARAM}={fingerprint(str(static_dir), 'plain.css')}"
        r = app.test_client().get(url, headers={"Range": "bytes=5000-"})
        assert r.status_code == 416
        assert r.headers.get("Cache-Control") != IMMUTABLE_CACHE_CONTROL

    def test_an_unterminated_comment_runs_to_the_end_of_the_file(self, static_dir):
        (static_dir / "open.css").write_text(".y{} /* unterminated url(app.js)")
        before = fingerprint(str(static_dir), "open.css")
        self._touch(static_dir / "app.js", b"console.log('two, longer');")
        assert fingerprint(str(static_dir), "open.css") == before

    def test_a_range_request_on_a_file_that_is_not_rewritten_still_works(self, app, static_dir):
        url = f"/static/app.js?{HASH_PARAM}={fingerprint(str(static_dir), 'app.js')}"
        r = app.test_client().get(url, headers={"Range": "bytes=0-6"})
        assert r.status_code == 206
        assert r.get_data() == b"console"


class TestSessionCookie:
    """Logins mark the session permanent, and Flask re-signs a permanent
    session's cookie on every response. On a public, year-long asset that put
    the user's session in Set-Cookie and added Vary: Cookie, so browsers dropped
    the cached copy whenever the cookie changed.
    """

    @pytest.fixture
    def session_app(self, app):
        from flask import session
        app.secret_key = "test"

        @app.route("/login")
        def login():
            session.permanent = True
            session["username"] = "u"
            return "ok"

        @app.route("/whoami")
        def whoami():
            return session.get("username", "")

        return app

    def test_static_responses_leave_the_session_alone(self, session_app, static_dir):
        client = session_app.test_client()
        client.get("/login")
        url = f"/static/app.js?{HASH_PARAM}={fingerprint(str(static_dir), 'app.js')}"
        r = client.get(url)
        assert r.headers["Cache-Control"] == IMMUTABLE_CACHE_CONTROL
        assert "Set-Cookie" not in r.headers
        assert "Cookie" not in r.headers.get("Vary", "")

    def test_other_responses_still_refresh_it(self, session_app):
        client = session_app.test_client()
        client.get("/login")
        r = client.get("/whoami")
        assert r.get_data(as_text=True) == "u"
        assert "session=" in r.headers.get("Set-Cookie", "")

    def test_a_custom_session_interface_is_left_in_place(self, static_dir):
        from flask.sessions import SecureCookieSessionInterface

        class Custom(SecureCookieSessionInterface):
            pass

        app = Flask(__name__, static_folder=str(static_dir))
        custom = Custom()
        app.session_interface = custom
        register_static_asset_caching(app)
        assert app.session_interface is custom
