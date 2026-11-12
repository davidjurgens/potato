"""Unanswered required questions still refuse a navigation POST.

A separate module from test_navigation_fast_path.py because test servers run
in-process and share singletons: a second config started in the same module
reconfigures the first.
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


class TestRequiredBlock:
    """An unanswered required question still refuses Next, header or not."""

    @pytest.fixture(scope="class")
    def required_server(self):
        schemes = [dict(SCHEMES[0], label_requirement={"required": True})]
        with TestConfigManager("nav_fast_required", schemes, num_items=3) as tc:
            srv = FlaskTestServer(port=None, config_file=tc.config_path)
            if not srv.start():
                pytest.fail("Failed to start Flask server")
            yield srv
            srv.stop()

    def test_same_refusal_with_and_without_the_header(self, required_server):
        base = required_server.base_url
        s = _session(base, "nav_block")
        first = _instance_id(s.get(f"{base}/annotate").text)

        plain = s.post(f"{base}/annotate", json={"action": "next_instance"}, timeout=5)
        fast = s.post(f"{base}/annotate", json={"action": "next_instance"},
                      headers=NAV_HEADERS, timeout=5)
        assert plain.status_code == fast.status_code == 400
        assert fast.json()["status"] == "validation_error"
        assert fast.json() == plain.json()
        assert _instance_id(s.get(f"{base}/annotate").text) == first
