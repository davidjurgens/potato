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
