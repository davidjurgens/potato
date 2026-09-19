"""The request path of one Next click, against a real server.

Between instances the annotation page shows "Loading annotation interface"
until the next page is usable. On a real network that took seconds on the
simplest task, and none of it was server compute:

- the navigation POST rendered the whole next page, which the browser threw
  away before fetching it again with a GET;
- every script and stylesheet was revalidated on every page load;
- four feature bundles loaded on every page because their asset markers
  matched the page template's own `<script src>` includes.

These tests pin the server half of each fix. The browser half is covered by
tests/jest/span-core-load-path.test.js and
tests/selenium/test_navigation_caching_ui.py.
"""

import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

SCHEMES = [{
    "annotation_type": "radio",
    "name": "sentiment",
    "description": "Sentiment",
    "labels": ["positive", "neutral", "negative"],
}]

NAV_HEADERS = {"X-Potato-Navigation": "1"}


def _session(base_url, user):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"email": user, "pass": "pw"}, timeout=5)
    s.post(f"{base_url}/auth", data={"email": user, "pass": "pw"}, timeout=5)
    return s


def _instance_id(html):
    m = re.search(r'id="instance_id"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else None


def _answer(s, base_url, instance_id):
    r = s.post(f"{base_url}/updateinstance", json={
        "instance_id": instance_id,
        "annotations": {"sentiment:::positive": "true"},
        "span_annotations": [],
    }, timeout=5)
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def server():
    with TestConfigManager("nav_fast_path", SCHEMES, num_items=4) as tc:
        srv = FlaskTestServer(port=None, config_file=tc.config_path)
        if not srv.start():
            pytest.fail("Failed to start Flask server")
        yield srv
        srv.stop()


class TestNavigationPost:

    def test_header_gets_json_naming_the_new_instance(self, server):
        base = server.base_url
        s = _session(base, "nav_json")
        first = _instance_id(s.get(f"{base}/annotate").text)
        _answer(s, base, first)

        r = s.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": first},
                   headers=NAV_HEADERS, timeout=5)
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("application/json")
        assert "no-store" in r.headers.get("Cache-Control", "")
        body = r.json()
        assert body["status"] == "ok"
        assert body["instance_id"] != first

        # The move really happened: the GET the page makes next shows it.
        assert _instance_id(s.get(f"{base}/annotate").text) == body["instance_id"]

    def test_previous_with_header(self, server):
        base = server.base_url
        s = _session(base, "nav_prev")
        first = _instance_id(s.get(f"{base}/annotate").text)
        _answer(s, base, first)
        s.post(f"{base}/annotate", json={"action": "next_instance"}, headers=NAV_HEADERS, timeout=5)

        r = s.post(f"{base}/annotate", json={"action": "prev_instance"}, headers=NAV_HEADERS, timeout=5)
        assert r.json() == {"status": "ok", "instance_id": first}

    def test_go_to_with_header(self, server):
        base = server.base_url
        s = _session(base, "nav_goto")
        s.get(f"{base}/annotate")
        r = s.post(f"{base}/annotate", json={"action": "go_to", "go_to": 2},
                   headers=NAV_HEADERS, timeout=5)
        assert r.json()["status"] == "ok"
        assert _instance_id(s.get(f"{base}/annotate").text) == r.json()["instance_id"]

    @pytest.mark.parametrize("value", ["abc", "", "1.5"])
    def test_go_to_that_is_not_a_number_is_a_400(self, server, value):
        # int() on these raised, and the annotator saw a 500.
        base = server.base_url
        s = _session(base, f"nav_goto_bad_{value or 'empty'}")
        first = _instance_id(s.get(f"{base}/annotate").text)
        r = s.post(f"{base}/annotate", json={"action": "go_to", "go_to": value},
                   headers=NAV_HEADERS, timeout=5)
        assert r.status_code == 400
        assert r.json()["status"] == "error"
        assert _instance_id(s.get(f"{base}/annotate").text) == first

    def test_the_go_to_route_rejects_a_non_number(self, server):
        base = server.base_url
        s = _session(base, "nav_goto_route")
        s.get(f"{base}/annotate")
        r = s.post(f"{base}/go_to", data={"go_to": "abc"}, timeout=5)
        assert r.status_code == 400

    def test_without_header_the_page_is_still_rendered(self, server):
        # Anything else posting here -- older pages still open in a tab,
        # scripts, other front ends -- keeps getting the page.
        base = server.base_url
        s = _session(base, "nav_html")
        first = _instance_id(s.get(f"{base}/annotate").text)
        _answer(s, base, first)
        r = s.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": first}, timeout=5)
        assert r.headers["Content-Type"].startswith("text/html")
        assert _instance_id(r.text) not in (None, first)

    def test_header_other_than_1_gets_the_page(self, server):
        # "X-Potato-Navigation: 0" reads as "not a navigation request".
        base = server.base_url
        s = _session(base, "nav_zero")
        first = _instance_id(s.get(f"{base}/annotate").text)
        _answer(s, base, first)
        r = s.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": first},
                   headers={"X-Potato-Navigation": "0"}, timeout=5)
        assert r.headers["Content-Type"].startswith("text/html")

    def test_finishing_the_last_item_still_redirects(self, server):
        base = server.base_url
        s = _session(base, "nav_finish")
        html = s.get(f"{base}/annotate").text
        for _ in range(10):
            iid = _instance_id(html)
            if iid is None:
                break
            _answer(s, base, iid)
            r = s.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": iid},
                       headers=NAV_HEADERS, timeout=5)
            if r.history:     # redirected to the next phase
                break
            assert r.json()["status"] == "ok"
            html = s.get(f"{base}/annotate").text
        assert r.history, "the last Next should redirect out of the annotation phase"
        assert 'id="instance_id"' not in s.get(f"{base}/annotate").text


class TestStaticCaching:

    def test_page_assets_carry_a_hash_and_are_immutable(self, server):
        base = server.base_url
        s = _session(base, "cache_user")
        html = s.get(f"{base}/annotate").text
        m = re.search(r'<script src="(/static/annotation\.js\?[^"]*\bh=[0-9a-f]+)"', html)
        assert m, "annotation.js should be referenced with a content hash"
        r = s.get(base + m.group(1).replace("&amp;", "&"))
        assert r.status_code == 200
        assert "immutable" in r.headers["Cache-Control"]
        assert "max-age=31536000" in r.headers["Cache-Control"]

    def test_every_static_script_and_stylesheet_is_hashed(self, server):
        s = _session(server.base_url, "cache_all")
        html = s.get(f"{server.base_url}/annotate").text
        urls = re.findall(r'<(?:script|link)\b[^>]*\s(?:src|href)="(/static/[^"]+)"', html)
        assert urls
        unhashed = [u for u in urls if not re.search(r"[?&](?:amp;)?h=[0-9a-f]+", u)]
        assert unhashed == []

    def test_static_responses_carry_no_session_cookie(self, server):
        # Logins make the session permanent, and Flask re-signs a permanent
        # session's cookie on every response. On a public, year-long asset
        # that meant Set-Cookie with the user's session plus Vary: Cookie,
        # and browsers dropped the cached copy whenever the cookie changed.
        base = server.base_url
        s = _session(base, "cache_cookie")
        page = s.get(f"{base}/annotate")
        # The page itself still refreshes the session...
        assert "session=" in page.headers.get("Set-Cookie", "")
        # ...and the assets it loads do not touch it.
        urls = re.findall(r'<(?:script|link)\b[^>]*\s(?:src|href)="(/static/[^"]+)"', page.text)
        assert urls
        for url in urls[:10]:
            r = s.get(base + url.replace("&amp;", "&"), timeout=5)
            assert r.status_code == 200, url
            assert "immutable" in r.headers["Cache-Control"], url
            assert "Set-Cookie" not in r.headers, url
            assert "Cookie" not in r.headers.get("Vary", ""), url
        # The session still works after all those asset requests.
        assert _instance_id(s.get(f"{base}/annotate").text)

    def test_a_range_request_on_a_rewritten_stylesheet_gets_the_whole_body(self, server):
        # A stylesheet with @import/url() references is served rewritten, so a
        # byte range computed against the file on disk would describe a
        # different body. The server answers 200 with the whole thing.
        s = _session(server.base_url, "cache_range")
        html = s.get(f"{server.base_url}/annotate").text
        m = re.search(r'href="(/static/styles\.css\?[^"]*\bh=[0-9a-f]+)"', html)
        assert m, "styles.css should be referenced with a content hash"
        url = server.base_url + m.group(1).replace("&amp;", "&")
        full = s.get(url, timeout=5)
        assert full.status_code == 200
        ranged = s.get(url, headers={"Range": "bytes=0-9"}, timeout=5)
        assert ranged.status_code == 200
        assert "Content-Range" not in ranged.headers
        assert ranged.content == full.content
        assert int(ranged.headers["Content-Length"]) == len(full.content)

    def test_unhashed_request_keeps_no_cache(self, server):
        r = requests.get(f"{server.base_url}/static/annotation.js", timeout=5)
        assert r.headers["Cache-Control"] == "no-cache"


class TestFeatureBundlesAreGated:

    @pytest.mark.parametrize("bundle", [
        "pdf-link-mode.js", "js/pdfjs-loader.js", "web-agent-recorder.js",
        "live-coding-agent-viewer.js", "label-visibility.js",
        "turn-annotations.js", "multi-agent-discussion.js", "audio-dialogue.js",
        "run-tree.js", "entity-linking.js",
    ])
    def test_a_radio_page_does_not_load(self, server, bundle):
        s = _session(server.base_url, "gate_user")
        html = s.get(f"{server.base_url}/annotate").text
        assert f"/static/{bundle}" not in html

    def test_the_core_scripts_still_load(self, server):
        s = _session(server.base_url, "gate_core")
        html = s.get(f"{server.base_url}/annotate").text
        for core in ("annotation.js", "span-core.js", "display-logic.js"):
            assert f"/static/{core}" in html
