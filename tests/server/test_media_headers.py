"""Audit 97 V13: /media never runs a file as the server's own page.

Media is project data, and with an import it can be someone else's data.
/media served .svg and .html inline with no nosniff and no CSP, so a crafted
file in media/ ran script on the server's origin. Every response now carries
nosniff, and a document type gets `Content-Security-Policy: sandbox`.
"""

import os
import shutil

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "..", "examples", "advanced",
                       "long-guidelines")


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("media_headers"), "long-guidelines")
    shutil.copytree(EXAMPLE, work,
                    ignore=shutil.ignore_patterns("annotation_output", "*.sqlite*", ".potato_cache"))
    media = os.path.join(work, "media")
    with open(os.path.join(media, "x.svg"), "w") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    with open(os.path.join(media, "x.html"), "w") as f:
        f.write("<script>fetch('/admin')</script>")
    with open(os.path.join(media, "note.txt"), "w") as f:
        f.write("<script>alert(1)</script>")
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the long-guidelines example")
    yield srv
    srv.stop()


@pytest.mark.parametrize("name", ["x.svg", "x.html", "codebook.html"])
def test_document_types_are_sandboxed(server, name):
    r = requests.get(f"{server.base_url}/media/{name}")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Content-Security-Policy") == "sandbox"


def test_every_media_response_says_nosniff(server):
    r = requests.get(f"{server.base_url}/media/note.txt")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" not in r.headers


@pytest.mark.parametrize("method, path, headers, status", [
    ("GET", "/media/missing.png", {}, 404),
    ("POST", "/media/note.txt", {}, 405),
    ("GET", "/media/note.txt", {"Range": "bytes=999999-"}, 416),
])
def test_error_responses_say_nosniff_too(server, method, path, headers, status):
    """potato-skill, audit 97 re-verify: 404, 405 and 416 from /media had no
    nosniff, since they never reach serve_media's own headers."""
    r = requests.request(method, server.base_url + path, headers=headers, timeout=5)
    assert r.status_code == status, r.status_code
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
