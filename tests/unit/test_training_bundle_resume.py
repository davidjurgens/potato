"""An agent's bundle download resumes after a dropped connection.

A bundle with media can be gigabytes over a slow link to a GPU host. The
agent used to restart from zero on any break; it now asks for the bytes it is
missing (``Range``), tied to the file it started on (``If-Range``). The
server side is Flask's ``send_file``, which already answers ranges; the first
test pins that, so a change in how the route sends the file cannot quietly
remove it.
"""

import hashlib
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from potato.training.agent import Client, ProtocolError

BLOB = os.urandom(300_000)
ETAG = '"%s"' % hashlib.sha256(BLOB).hexdigest()[:16]


def test_the_route_s_send_file_answers_ranges(tmp_path):
    from flask import Flask, send_file

    path = tmp_path / "bundle.tar.gz"
    path.write_bytes(BLOB)
    app = Flask(__name__)

    @app.route("/b")
    def b():
        # The call get_bundle makes.
        return send_file(str(path), mimetype="application/gzip",
                         as_attachment=True, download_name="bundle-x.tar.gz")

    client = app.test_client()
    whole = client.get("/b")
    etag = whole.headers["ETag"]
    part = client.get("/b", headers={"Range": "bytes=1000-", "If-Range": etag})
    assert part.status_code == 206
    assert part.headers["Content-Range"] == "bytes 1000-%d/%d" % (
        len(BLOB) - 1, len(BLOB))
    assert part.data == BLOB[1000:]
    # A different file than the one the agent started on: sent whole.
    stale = client.get("/b", headers={"Range": "bytes=1000-", "If-Range": '"old"'})
    assert stale.status_code == 200 and stale.data == BLOB


class Flaky(BaseHTTPRequestHandler):
    """Serves BLOB with Range support, cutting the first N responses off."""
    cuts = 1
    requests = []
    blob = BLOB
    #: Status codes to answer requests with, in order, before serving.
    script = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Flaky.requests.append(dict(self.headers))
        if self.headers.get("Authorization") != "Bearer tok":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if Flaky.script:
            status = Flaky.script.pop(0)
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        start = 0
        rng = self.headers.get("Range")
        if rng and self.headers.get("If-Range") == ETAG:
            start = int(rng.split("=")[1].rstrip("-"))
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d"
                             % (start, len(self.blob) - 1, len(self.blob)))
        else:
            self.send_response(200)
            self.send_header("ETag", ETAG)
        body = self.blob[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if Flaky.cuts > 0:
            Flaky.cuts -= 1
            self.wfile.write(body[:len(body) // 3])
            self.wfile.flush()
            self.connection.shutdown(2)
            return
        self.wfile.write(body)


@pytest.fixture
def server():
    Flaky.requests = []
    Flaky.script = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Flaky)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()


def _download(server, dest, token="tok", attempts=5):
    client = Client(token, server=server, timeout=10)
    return client.download("/bundle", str(dest), attempts=attempts,
                           _sleep=lambda s: None)


def test_a_dropped_download_resumes_and_is_complete(server, tmp_path):
    Flaky.cuts = 2
    size = _download(server, tmp_path / "b.tar.gz")
    assert size == len(BLOB)
    assert (tmp_path / "b.tar.gz").read_bytes() == BLOB
    assert not (tmp_path / "b.tar.gz.partial").exists()
    # The retries asked only for what was missing.
    assert "Range" not in Flaky.requests[0]
    resumed = [int(r["Range"].split("=")[1].rstrip("-"))
               for r in Flaky.requests[1:]]
    assert len(resumed) == 2 and 0 < resumed[0] < resumed[1] < len(BLOB)


def test_it_gives_up_after_its_attempts(server, tmp_path):
    Flaky.cuts = 10
    with pytest.raises(ProtocolError, match="after 3 attempts"):
        _download(server, tmp_path / "b.tar.gz", attempts=3)
    assert not (tmp_path / "b.tar.gz").exists()


def test_an_http_error_is_not_retried(server, tmp_path):
    Flaky.cuts = 0
    with pytest.raises(ProtocolError) as err:
        _download(server, tmp_path / "b.tar.gz", token="wrong")
    assert err.value.status == 401
    assert len(Flaky.requests) == 1


def test_a_server_error_is_retried(server, tmp_path):
    Flaky.cuts, Flaky.script = 0, [503, 502]
    assert _download(server, tmp_path / "b.tar.gz") == len(BLOB)
    assert len(Flaky.requests) == 3


def test_a_refused_range_restarts_from_zero(server, tmp_path):
    # The first answer is cut short; the resume is refused with 416 (the
    # file shrank). The partial copy is thrown away and the file fetched
    # whole, not left as .partial.
    Flaky.cuts = 1

    def refuse_next():
        Flaky.script.append(416)
    original = Flaky.do_GET

    def do_get(self):
        if len(Flaky.requests) == 1:
            refuse_next()
        original(self)
    Flaky.do_GET = do_get
    try:
        assert _download(server, tmp_path / "b.tar.gz") == len(BLOB)
    finally:
        Flaky.do_GET = original
    assert (tmp_path / "b.tar.gz").read_bytes() == BLOB
    assert "Range" in Flaky.requests[1] and "Range" not in Flaky.requests[2]
    assert not (tmp_path / "b.tar.gz.partial").exists()


def test_giving_up_leaves_no_partial_file(server, tmp_path):
    Flaky.cuts = 10
    with pytest.raises(ProtocolError):
        _download(server, tmp_path / "b.tar.gz", attempts=2)
    assert not (tmp_path / "b.tar.gz.partial").exists()
