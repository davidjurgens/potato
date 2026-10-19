"""
The no-assistance comparison group on a running server.

With `ai_support.holdout.fraction: 1.0` every (annotator, item) pair is held
out, so every assistance route must refuse with the same 403 the labeling
engine's blind items get, the pre-annotation must not reach the page or the
instance-data JSON, and /admin/api/ai_influence must answer.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "holdout-admin-key"
SCHEME = {"annotation_type": "radio", "name": "sentiment", "description": "Sentiment?",
          "labels": ["positive", "negative"]}


def _server(name, fraction):
    test_dir = create_test_directory(name)
    data_file = create_test_data_file(test_dir, [
        {"id": f"item_{n}", "text": f"Text {n}", "predictions": {"sentiment": "positive"}}
        for n in range(1, 4)])
    port = find_free_port(preferred_port=9895)
    config_file = create_test_config(
        test_dir, [SCHEME], data_files=[data_file], port=port,
        additional_config={
            "admin_api_key": ADMIN_KEY,
            "pre_annotation": {"enabled": True, "field": "predictions",
                               "allow_modification": True},
            "ai_support": {"enabled": False,
                           "holdout": {"fraction": fraction, "salt": "test"}},
        })
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start server")
    return server, test_dir


def _login(server, name):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": name, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": name, "pass": "pw"})
    return s


# One server at a time: FlaskTestServer runs in-process and servers share the
# global config, so two live at once would both see whichever started last.
@pytest.fixture
def held_out_server():
    server, test_dir = _server("assist_holdout_all", 1.0)
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


def test_every_assistance_route_refuses_a_held_out_pair(held_out_server):
    from potato.routes import ENGINE_BLIND_ROUTES
    s = _login(held_out_server, "held")
    page = s.get(f"{held_out_server.base_url}/annotate").text
    assert 'id="instance_id"' in page
    for method, path in ENGINE_BLIND_ROUTES:
        url = f"{held_out_server.base_url}{path}"
        if method == "GET":
            r = s.get(url, params={"annotationId": 0, "annotation_id": 0,
                                   "instance_id": "item_1", "schema": "sentiment"})
        else:
            r = s.post(url, json={"message": "what is the label?", "instance_id": "item_1"})
        if path == "/api/chat/send" and r.status_code == 404:
            # Chat is off in this study, which is also no assistance; the
            # engine's test covers the order of the checks with chat on.
            assert "not enabled" in r.text
            continue
        assert r.status_code == 403, (path, r.status_code, r.text[:200])
        assert "no-assistance comparison group" in r.text, (path, r.text[:200])


def _what_the_page_shows(server, name):
    from bs4 import BeautifulSoup
    s = _login(server, name)
    soup = BeautifulSoup(s.get(f"{server.base_url}/annotate").text, "html.parser")
    boxes = [i.get("value") for i in soup.find_all("input", {"name": "sentiment"})
             if i.has_attr("checked")]
    data = s.get(f"{server.base_url}/api/current_instance").json().get("data") or {}
    return boxes, "predictions" in data


def test_an_assisted_pair_gets_the_prediction():
    server, test_dir = _server("assist_holdout_none", 0.0)
    try:
        assert _what_the_page_shows(server, "assisted") == (["positive"], True)
    finally:
        server.stop()
        cleanup_test_directory(test_dir)


def test_a_held_out_pair_gets_neither_page_nor_json_prediction(held_out_server):
    assert _what_the_page_shows(held_out_server, "held2") == ([], False)


def test_the_influence_report_answers(held_out_server):
    r = requests.get(f"{held_out_server.base_url}/admin/api/ai_influence",
                     headers={"X-API-Key": ADMIN_KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["holdout_fraction"] == 1.0
    assert "sentiment" in body["schemas"]


def _page_flag(page):
    import re
    found = re.search(r"assist_withheld: (true|false)", page)
    return found.group(1) if found else None


def test_the_browser_tools_and_keyword_hints_are_withheld_too(held_out_server):
    """The surfaces B4 left out: admin keyword highlights, SAM 2 tracking,
    and the in-browser segmentation tools (switched off by a page flag)."""
    s = _login(held_out_server, "held3")
    page = s.get(f"{held_out_server.base_url}/annotate").text
    assert _page_flag(page) == "true"
    current = s.get(f"{held_out_server.base_url}/api/current_instance").json()["instance_id"]

    keywords = s.get(f"{held_out_server.base_url}/api/keyword_highlights/{current}")
    assert keywords.status_code == 200
    assert keywords.json()["keywords"] == [] and keywords.json()["withheld"] is True

    tracked = s.post(f"{held_out_server.base_url}/api/track/propagate",
                     json={"points": [[10, 10, 1]], "video": "clip.mp4", "start_frame": 0})
    assert tracked.status_code == 403
    assert "no-assistance comparison group" in tracked.json()["error"]


def test_an_assisted_pair_keeps_the_browser_tools():
    server, test_dir = _server("assist_holdout_tools", 0.0)
    try:
        s = _login(server, "assisted2")
        assert _page_flag(s.get(f"{server.base_url}/annotate").text) == "false"
        current = s.get(f"{server.base_url}/api/current_instance").json()["instance_id"]
        body = s.get(f"{server.base_url}/api/keyword_highlights/{current}").json()
        assert "withheld" not in body
    finally:
        server.stop()
        cleanup_test_directory(test_dir)


def test_a_saved_answer_decides_what_the_suggestion_led_to():
    """Accept or reject is decided at save, from the saved answer: changing
    one's mind after taking a suggestion records the later answer."""
    server, test_dir = _server("assist_decisions", 0.0)
    try:
        s = _login(server, "decider")
        base = server.base_url
        s.get(f"{base}/annotate")
        item = s.get(f"{base}/api/current_instance").json()["instance_id"]
        for event in ({"event_type": "request"},
                      {"event_type": "response", "suggestions": ["positive"]}):
            assert s.post(f"{base}/api/track_ai_usage",
                          json={"instance_id": item, "schema_name": "sentiment", **event}).ok

        def save(label):
            r = s.post(f"{base}/updateinstance", json={
                "instance_id": item, "annotations": {f"sentiment:::{label}": label},
                "cleared_schemas": [], "span_annotations": []})
            assert r.status_code == 200, r.text
            return s.get(f"{base}/api/behavioral_data/{item}").json()["ai_usage"][-1]

        took = save("positive")
        assert (took["decision"], took["suggestion_accepted"]) == ("accepted", "positive")
        assert took["time_to_decision_ms"] is not None
        changed = save("negative")
        assert (changed["decision"], changed["suggestion_accepted"]) == ("rejected", None)
    finally:
        server.stop()
        cleanup_test_directory(test_dir)
