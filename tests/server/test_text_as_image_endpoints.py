"""``text_as_image`` against a real server: no endpoint hands back the words.

The page is one carrier. The JSON endpoints the page calls are the others: an
annotator can open ``/api/instance_data`` in a new tab and copy the item from
there. Each test hits one of them with the feature on and looks for the item's
words in the raw response body.
"""

import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

#: Nonsense tokens on purpose, so a hit can only be the item text.
ITEMS = [
    {"id": "1", "text": "Zorbaxil qynthorp veldrammic.", "topic": "fauna"},
    {"id": "2", "text": "Wuxlotte prandivore skelmitch.", "topic": "flora"},
]
TOKENS = ["Zorbaxil", "qynthorp", "veldrammic", "Wuxlotte", "prandivore", "skelmitch"]

SCHEMES = [{
    "annotation_type": "radio",
    "name": "sentiment",
    "description": "Sentiment",
    "labels": ["positive", "negative"],
}]


def _assert_no_text(body):
    for token in TOKENS:
        assert token not in body


def _instance_id(html):
    m = re.search(r'id="instance_id"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else None


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("text_as_image_endpoints")
    config_file = create_test_config(
        test_dir, SCHEMES,
        data_files=[create_test_data_file(test_dir, ITEMS)],
        additional_config={"text_as_image": True},
    )
    srv = FlaskTestServer(port=None, config_file=config_file)
    if not srv.start():
        pytest.fail("Failed to start Flask server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture
def session(server, request):
    user = request.node.name[-40:]
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": user, "pass": "pw"}, timeout=5)
    s.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"}, timeout=5)
    return s


class TestNoEndpointReturnsTheText:

    def test_annotate_page(self, server, session):
        r = session.get(f"{server.base_url}/annotate", timeout=5)
        assert r.status_code == 200
        assert "data:image/png;base64," in r.text
        _assert_no_text(r.text)

    def test_current_instance(self, server, session):
        session.get(f"{server.base_url}/annotate", timeout=5)
        r = session.get(f"{server.base_url}/api/current_instance", timeout=5)
        assert r.status_code == 200
        # The other fields still arrive: only the text is dropped.
        assert r.json()["data"]["topic"] in {"fauna", "flora"}
        _assert_no_text(r.text)

    def test_instance_data(self, server, session):
        session.get(f"{server.base_url}/annotate", timeout=5)
        r = session.get(f"{server.base_url}/api/instance_data", timeout=5)
        assert r.status_code == 200
        assert r.json()["topic"] in {"fauna", "flora"}
        _assert_no_text(r.text)

    @pytest.mark.parametrize("instance_id", ["1", "2"])
    def test_spans(self, server, session, instance_id):
        # Any id, not only the current one: the endpoint serves both.
        session.get(f"{server.base_url}/annotate", timeout=5)
        r = session.get(f"{server.base_url}/api/spans/{instance_id}", timeout=5)
        assert r.status_code == 200
        assert r.json()["text"] == ""
        _assert_no_text(r.text)

    def test_next_and_previous_fast_path(self, server, session):
        """2.9.2 navigation: a JSON answer to the POST, then a GET of the page."""
        base = server.base_url
        first = _instance_id(session.get(f"{base}/annotate", timeout=5).text)
        headers = {"X-Potato-Navigation": "1"}
        for action in ("next_instance", "prev_instance"):
            r = session.post(f"{base}/annotate", headers=headers, timeout=5,
                             json={"action": action, "instance_id": first})
            assert r.status_code == 200
            _assert_no_text(r.text)
            page = session.get(f"{base}/annotate", timeout=5)
            assert "data:image/png;base64," in page.text
            _assert_no_text(page.text)
