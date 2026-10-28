"""
The web-agent proxy serves third-party pages in a sandbox.

/api/web_agent/proxy/<url> fetches any public page and serves it from
Potato's own origin. Without a sandbox the page's scripts ran as Potato with
the viewer's session, so a proxy link opened by an admin acted as the admin.
The response now carries ``Content-Security-Policy: sandbox`` without
allow-same-origin. A sandboxed page gets no SameSite=Lax session cookie on
its own requests, so rewritten URLs carry a signed proxy-only token instead.
"""

import re
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from potato.web_proxy import web_proxy_bp

PAGE = ('<html><head><link rel="stylesheet" href="/s.css"></head>'
        '<body><script>fetch("/admin/api/x")</script>'
        '<a href="/next">n</a></body></html>')


@pytest.fixture
def client():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(web_proxy_bp)
    app.add_url_rule("/login", "login", lambda: "login")
    return app.test_client()


def _fake_get(content_type, body):
    def get(url, **kwargs):
        resp = MagicMock()
        resp.headers = {"Content-Type": content_type}
        resp.text = body
        resp.content = body.encode()
        resp.status_code = 200
        resp.url = url
        return resp
    return get


def _login(client):
    with client.session_transaction() as s:
        s["username"] = "annotator"


@pytest.mark.parametrize("content_type,body", [
    ("text/html; charset=utf-8", PAGE),
    ("image/svg+xml", '<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>'),
])
def test_proxied_document_is_sandboxed(client, content_type, body):
    _login(client)
    with patch("potato.web_proxy._is_private_ip", return_value=False), \
            patch("requests.get", _fake_get(content_type, body)):
        resp = client.get("/api/web_agent/proxy/https://example.org/")
    assert resp.status_code == 200
    csp = resp.headers.get("Content-Security-Policy", "")
    directives = csp.split()
    assert directives[:1] == ["sandbox"]
    assert "allow-same-origin" not in directives
    assert "allow-scripts" in directives     # the recorder script must still run
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_rewritten_urls_carry_a_token_that_works_without_the_cookie(client):
    _login(client)
    with patch("potato.web_proxy._is_private_ip", return_value=False), \
            patch("requests.get", _fake_get("text/html", PAGE)):
        page = client.get("/api/web_agent/proxy/https://example.org/").get_data(as_text=True)
    urls = re.findall(r'href="(/api/web_agent/proxy/[^"]+)"', page)
    assert urls and all("/_pt_" in u for u in urls)
    assert "annotator" not in page          # the token names no user

    with client.session_transaction() as s:
        s.clear()                           # the sandboxed page sends no cookie
    with patch("potato.web_proxy._is_private_ip", return_value=False), \
            patch("requests.get", _fake_get("text/css", "body{}")):
        sub = client.get(urls[0])
    assert sub.status_code == 200
    assert sub.get_data(as_text=True) == "body{}"


def test_bad_token_and_no_session_is_refused(client):
    with patch("potato.web_proxy._is_private_ip", return_value=False), \
            patch("requests.get", _fake_get("text/html", PAGE)):
        resp = client.get("/api/web_agent/proxy/_pt_forged/https://example.org/")
        assert resp.status_code == 302
        resp = client.get("/api/web_agent/proxy/https://example.org/")
        assert resp.status_code == 302
