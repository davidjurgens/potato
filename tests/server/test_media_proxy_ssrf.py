"""
End-to-end checks on the media endpoints that fetch a caller-supplied URL.

Two separate properties, and a test that only covers the first is how the
earlier fix was reported as done when it was not:

1. Unauthenticated callers are refused.
2. An *authenticated* caller still cannot reach an internal address. Every
   annotator on a crowdsourced task is authenticated, so auth alone is not the
   fix.
"""

import pytest



@pytest.fixture(scope="module")
def client():
    from potato.flask_server import app
    from potato.routes import configure_routes
    from potato.server_utils.config_module import config

    config.setdefault("task_dir", ".")
    # The module-level `app` has no routes until configure_routes() runs: the
    # live server registers them through the factory, and a test that skips it
    # gets 404 for every endpoint, which reads as "blocked" if the assertion
    # only checks "not 200".
    configure_routes(app, config)
    app.config["TESTING"] = True
    app.secret_key = app.secret_key or "test-secret-for-media-proxy"
    with app.test_client() as c:
        yield c


def _login(client):
    with client.session_transaction() as sess:
        sess["username"] = "annotator@example.com"


BLOCKED = [
    ("cloud metadata", "http://169.254.169.254/latest/meta-data/"),
    ("loopback", "http://127.0.0.1:9/"),
    ("localhost name", "http://localhost:9/"),
    ("private 10/8", "http://10.0.0.1/"),
    ("private 192.168", "http://192.168.1.1/"),
    ("decimal loopback", "http://2130706433/"),
    ("v6 loopback", "http://[::1]/"),
    ("file scheme", "file:///etc/passwd"),
]


class TestUnauthenticated:
    @pytest.mark.parametrize("label,url", BLOCKED)
    def test_audio_proxy_refuses(self, client, label, url):
        r = client.get("/api/audio/proxy", query_string={"url": url})
        assert r.status_code == 401, label

    def test_waveform_generate_refuses(self, client):
        r = client.post("/api/waveform/generate",
                        json={"audio_url": "http://169.254.169.254/"})
        assert r.status_code == 401

    def test_video_waveform_refuses(self, client):
        r = client.post("/api/video/waveform/generate",
                        json={"video_url": "http://169.254.169.254/"})
        assert r.status_code == 401


class TestAuthenticatedStillCannotReachInternalHosts:
    """The part auth does not cover."""

    @pytest.mark.parametrize("label,url", BLOCKED)
    def test_audio_proxy_blocks(self, client, label, url):
        _login(client)
        r = client.get("/api/audio/proxy", query_string={"url": url})
        assert r.status_code == 403, (
            "%s returned %s; an authenticated annotator reached an internal "
            "address" % (label, r.status_code)
        )
        assert b"not allowed" in r.data.lower()

    def test_no_cors_wildcard(self, client):
        _login(client)
        r = client.get("/api/audio/proxy",
                       query_string={"url": "http://169.254.169.254/"})
        assert r.headers.get("Access-Control-Allow-Origin") != "*"

    def test_missing_url_is_a_400_not_a_crash(self, client):
        _login(client)
        r = client.get("/api/audio/proxy")
        assert r.status_code == 400
