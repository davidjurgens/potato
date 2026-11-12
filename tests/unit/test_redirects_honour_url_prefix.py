"""Server-side redirects stay inside the study's URL prefix.

Behind a reverse proxy at ``/study``, ``redirect("/pocket")`` sends the browser
to the bare host's ``/pocket`` -- another app, or a 404. Five routes did that:
the phone-to-Pocket redirect on ``/annotate``, three in Rooms and one on the
codebook page. They now prefix ``request.script_root``, which is ``/study``
under the proxy and empty otherwise.
"""

import pathlib
import re
from unittest.mock import patch

from flask import Flask

REPO = pathlib.Path(__file__).resolve().parents[2]


def _app_with(blueprint):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(blueprint)
    return app


def test_codebook_page_redirects_within_the_prefix():
    from potato.codebook.page import codebook_page_bp

    app = _app_with(codebook_page_bp)
    with patch("potato.codebook.api.codebook_enabled", return_value=True):
        resp = app.test_client().get(
            "/codebook", environ_overrides={"SCRIPT_NAME": "/study"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/study/")


def test_codebook_page_redirect_is_unchanged_without_a_prefix():
    from potato.codebook.page import codebook_page_bp

    app = _app_with(codebook_page_bp)
    with patch("potato.codebook.api.codebook_enabled", return_value=True):
        resp = app.test_client().get("/codebook")
    assert resp.status_code == 302
    assert resp.headers["Location"] in ("/", "http://localhost/")


def test_no_route_redirects_to_a_bare_root_path():
    """A literal redirect("/...") ignores the prefix; build it from
    request.script_root or url_for instead."""
    offenders = []
    for path in (REPO / "potato").rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""\bredirect\(\s*['"]/""", line):
                offenders.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
