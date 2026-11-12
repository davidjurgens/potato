"""{condition.<factor>} in item text and in question wording is replaced by
the participant's level, on the annotation page and on survey pages, and an
unknown factor stays visible."""

import json
import os

import pytest
import requests

from potato.server_utils.phase_flow import fill_condition_placeholders
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file, create_test_directory)


def test_fill_escapes_and_keeps_unknown():
    html = "<p>{condition.endorser} backs it; {condition.nope} stays; {condition.x}</p>"
    out = fill_condition_placeholders(html, {"endorser": "Tom & <Jerry>", "x": 3})
    assert out == "<p>Tom &amp; &lt;Jerry&gt; backs it; {condition.nope} stays; 3</p>"
    assert fill_condition_placeholders(html, None) == html


@pytest.fixture(scope="module")
def vignette_server(request):
    d = create_test_directory("condition_placeholders_server")
    data = create_test_data_file(d, [{"id": "v1", "text": "{condition.endorser} supports the new park."}])
    page = os.path.join(d, "pre.json")
    with open(page, "w") as f:
        json.dump([{"name": "trust", "annotation_type": "radio", "labels": ["yes", "no"],
                    "description": "Do you trust {condition.endorser}?"}], f)
    config = create_test_config(
        d, annotation_schemes=[{"name": "support", "annotation_type": "radio",
                                "labels": ["yes", "no"],
                                "description": "Would you vote with {condition.endorser}?"},
                               {"name": "ent", "annotation_type": "span", "labels": ["X"],
                                "description": "Mark words"}],
        data_files=[data],
        phases={"order": ["pre", "annotation"], "pre": {"type": "prestudy", "file": page}},
        additional_config={"conditions": {"factors": {"endorser": ["The mayor", "A neighbour"]},
                                          "assignment": "round_robin"}})
    server = FlaskTestServer(config=config)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    return server


def test_both_pages_use_the_participants_level(vignette_server):
    base = vignette_server.base_url
    levels = set()
    for name in ("cv_a", "cv_b"):
        s = requests.Session()
        s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "p"}, timeout=5)
        s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "p"}, timeout=5)
        survey = s.get(f"{base}/", timeout=5).text
        assert "{condition.endorser}" not in survey
        level = "The mayor" if "Do you trust The mayor?" in survey else "A neighbour"
        assert f"Do you trust {level}?" in survey
        s.post(f"{base}/updateinstance", json={"instance_id": "__phase_page__",
               "annotations": {"trust:::yes": "yes"}, "span_annotations": []}, timeout=5)
        page = s.post(f"{base}/annotate", json={"action": "next_instance"}, timeout=5).text
        assert f"{level} supports the new park." in page
        assert f"Would you vote with {level}?" in page
        # The JSON APIs give the text the page shows, and span offsets count
        # its characters (audit 97 T12).
        shown = f"{level} supports the new park."
        assert s.get(f"{base}/api/current_instance", timeout=5).json()["data"]["text"] == shown
        assert s.get(f"{base}/api/instance_data", timeout=5).json()["text"] == shown
        start = len(level) + 1
        s.post(f"{base}/updateinstance", json={
            "instance_id": "v1", "annotations": {}, "span_annotations": [
                {"schema": "ent", "name": "X", "start": start, "end": start + 8, "value": "supports"}]},
            timeout=5)
        body = s.get(f"{base}/api/spans/v1", timeout=5).json()
        assert body["text"] == shown
        assert [sp["text"] for sp in body["spans"]] == ["supports"]
        levels.add(level)
    assert levels == {"The mayor", "A neighbour"}, "round_robin gave both the same level"
