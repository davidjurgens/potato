"""
Previous from the last item goes back; it does not finish the study.

/annotate finished a user's study whenever every assigned item had an answer,
before looking at what the request asked for. An image item has an answer as
soon as it is visited (no shapes is an answer), so on a two-item image study,
opening item 2 and pressing Previous to check item 1 showed "You have
completed the annotation task". Found on the whole-slide example.
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
    "labels": ["positive", "negative"],
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
        "instance_id": instance_id, "annotations": {"sentiment:::positive": "true"},
        "span_annotations": []}, timeout=5)
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def server():
    with TestConfigManager("prev_from_last", SCHEMES, num_items=2) as tc:
        srv = FlaskTestServer(port=None, config_file=tc.config_path)
        if not srv.start():
            pytest.fail("Failed to start server")
        yield srv
        srv.stop()


def _answer_both_and_stand_on_the_last(base, user):
    s = _session(base, user)
    first = _instance_id(s.get(f"{base}/annotate").text)
    _answer(s, base, first)
    r = s.post(f"{base}/annotate", json={"action": "next_instance"}, headers=NAV_HEADERS,
               timeout=5)
    last = r.json()["instance_id"]
    _answer(s, base, last)
    return s, first, last


@pytest.mark.parametrize("headers", [NAV_HEADERS, {}], ids=["json-nav", "page-post"])
def test_previous_goes_back_after_every_item_is_answered(server, headers):
    base = server.base_url
    s, first, _last = _answer_both_and_stand_on_the_last(
        base, f"prev_last_{'nav' if headers else 'page'}")
    r = s.post(f"{base}/annotate", json={"action": "prev_instance"}, headers=headers,
               timeout=5)
    assert r.status_code == 200
    if headers:
        assert r.json() == {"status": "ok", "instance_id": first}
    page = s.get(f"{base}/annotate").text
    assert _instance_id(page) == first, "Previous finished the study instead of going back"


def test_go_to_an_earlier_item_also_goes_back(server):
    base = server.base_url
    s, first, _last = _answer_both_and_stand_on_the_last(base, "prev_last_goto")
    r = s.post(f"{base}/annotate", json={"action": "go_to", "go_to": 0},
               headers=NAV_HEADERS, timeout=5)
    assert r.json()["status"] == "ok"
    assert _instance_id(s.get(f"{base}/annotate").text) == first


def test_next_from_the_answered_last_item_still_finishes(server):
    base = server.base_url
    s, _first, _last = _answer_both_and_stand_on_the_last(base, "prev_last_next")
    s.post(f"{base}/annotate", json={"action": "next_instance"}, headers=NAV_HEADERS,
           timeout=5)
    page = s.get(f"{base}/annotate", allow_redirects=True).text
    assert _instance_id(page) is None
    assert "completed" in page.lower() or "thank you" in page.lower()


def test_a_review_can_return_to_the_last_item_and_then_finish(server):
    base = server.base_url
    s, first, last = _answer_both_and_stand_on_the_last(base, "prev_last_review")
    s.post(f"{base}/annotate", json={"action": "prev_instance"}, headers=NAV_HEADERS, timeout=5)
    r = s.post(f"{base}/annotate", json={"action": "next_instance"}, headers=NAV_HEADERS,
               timeout=5)
    assert r.json() == {"status": "ok", "instance_id": last}
    assert _instance_id(s.get(f"{base}/annotate").text) == last
    s.post(f"{base}/annotate", json={"action": "next_instance"}, headers=NAV_HEADERS, timeout=5)
    assert _instance_id(s.get(f"{base}/annotate").text) is None      # finished


def test_a_review_left_open_does_not_outlive_its_page(server):
    # A path that finishes without going through /annotate's end-of-list
    # branch (an IBWS round, the engine's no-work page, a phase change made
    # elsewhere) leaves the review flag set. It must not suppress the
    # completion check on the next page: the flag names the page it was set
    # on. The server runs in-process, so the page change is made directly.
    from potato.phase import UserPhase
    from potato.user_state_management import get_user_state_manager
    base = server.base_url
    user = "prev_last_stale"
    s, first, _last = _answer_both_and_stand_on_the_last(base, user)
    s.post(f"{base}/annotate", json={"action": "prev_instance"}, headers=NAV_HEADERS, timeout=5)
    assert _instance_id(s.get(f"{base}/annotate").text) == first      # reviewing
    get_user_state_manager().get_user_state(user).advance_to_phase(
        UserPhase.ANNOTATION, "second_round")
    page = s.get(f"{base}/annotate", allow_redirects=True).text
    assert _instance_id(page) is None, "a review from an earlier page held the user on an item"
