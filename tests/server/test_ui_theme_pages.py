"""
Every annotator page decides its theme before it paints.

The decision is an inline script in <head> (templates/_theme_head.html). A
page without it renders light whatever the annotator chose, and flashes when
the next page is dark. Admin pages stay light by design.
"""

import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

SCHEMES = [{"annotation_type": "radio", "name": "sentiment",
            "description": "Sentiment", "labels": ["positive", "negative"]}]


def _mode(html):
    match = re.search(r"var mode = \"(\w+)\";", html)
    return match.group(1) if match else None


def _before_stylesheets(html):
    script = html.find("potato-theme")
    sheet = html.find('rel="stylesheet"')
    return 0 <= script < sheet


@pytest.fixture(scope="module")
def server():
    with TestConfigManager("ui_theme_pages", SCHEMES, num_items=2) as tc:
        srv = FlaskTestServer(port=None, config_file=tc.config_path)
        if not srv.start():
            pytest.fail("Failed to start server")
        yield srv
        srv.stop()


@pytest.mark.parametrize("path", ["/", "/forgot-password"])
def test_signed_out_pages(server, path):
    html = requests.get(server.base_url + path, timeout=5).text
    assert _mode(html) == "auto"
    assert _before_stylesheets(html)


def test_the_annotation_page_has_the_theme_and_the_toggle(server):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": "t", "pass": "p"}, timeout=5)
    s.post(f"{server.base_url}/auth", data={"email": "t", "pass": "p"}, timeout=5)
    html = s.get(f"{server.base_url}/annotate", timeout=5).text
    assert _mode(html) == "auto"
    assert _before_stylesheets(html)
    assert "data-theme-toggle" in html
    logged_out = s.get(f"{server.base_url}/logout", timeout=5).text
    assert _mode(logged_out) == "auto"


def test_a_forced_theme_reaches_the_page_and_drops_the_toggle():
    with TestConfigManager("ui_theme_forced", SCHEMES, num_items=2,
                           additional_config={"ui": {"theme": "dark"}}) as tc:
        srv = FlaskTestServer(port=None, config_file=tc.config_path)
        if not srv.start():
            pytest.fail("Failed to start server")
        try:
            s = requests.Session()
            s.post(f"{srv.base_url}/register", data={"email": "f", "pass": "p"}, timeout=5)
            s.post(f"{srv.base_url}/auth", data={"email": "f", "pass": "p"}, timeout=5)
            html = s.get(f"{srv.base_url}/annotate", timeout=5).text
            assert _mode(html) == "dark"
            assert "data-theme-toggle" not in html
            meta = re.search(r"<meta[^>]*color-scheme[^>]*>", html).group(0)
            assert 'content="dark"' in meta
        finally:
            srv.stop()
