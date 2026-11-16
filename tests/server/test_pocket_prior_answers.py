"""prior_answers on Pocket: a phone is routed to /pocket instead of /annotate,
so the participant's own prestudy answer has to reach Pocket too.

It travels in /pocket/api/task and never in the /pocket page, because the
Pocket service worker caches that page for every account on the device.
"""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file, create_test_directory)

QUESTION = "In your own words, how would you define the concept?"


@pytest.fixture(scope="module")
def pocket_server(request):
    d = create_test_directory("pocket_prior_answers")
    data = create_test_data_file(d, [{"id": "i1", "text": "First item."},
                                     {"id": "i2", "text": "Second item."}])
    page = os.path.join(d, "pre.json")
    with open(page, "w") as f:
        json.dump([
            {"name": "concept_definition", "annotation_type": "text",
             "description": QUESTION, "label_requirement": {"required": True}},
            {"name": "optional_note", "annotation_type": "text",
             "description": "Anything else?"},
        ], f)
    config = create_test_config(
        d, annotation_schemes=[{"name": "fits", "annotation_type": "radio",
                                "labels": ["yes", "no"], "description": "Does it fit?"}],
        data_files=[data],
        phases={"order": ["definition", "annotation"],
                "definition": {"type": "prestudy", "file": page}},
        additional_config={
            "pocket": {"enabled": True},
            "prior_answers": [
                {"schema": "concept_definition", "title": "Definition"},
                {"schema": "optional_note", "collapsible": False},
            ]})
    server = FlaskTestServer(config=config)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    return server


def _participant(base, name, answer):
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "p"}, timeout=5)
    assert QUESTION in s.get(f"{base}/", timeout=5).text
    s.post(f"{base}/updateinstance", json={
        "instance_id": "__phase_page__",
        "annotations": {"concept_definition:::text_box": answer},
        "span_annotations": []}, timeout=5)
    s.post(f"{base}/annotate", json={"action": "next_instance"}, timeout=5)
    return s


def test_task_carries_the_participants_own_answer_as_plain_lines(pocket_server):
    base = pocket_server.base_url
    answer = "Elites <script>x</script> vs. people\nsecond line"
    s = _participant(base, "pk_one", answer)

    task = s.get(f"{base}/pocket/api/task", timeout=5).json()

    # Plain text: pocket.js sets it as textContent, so escaping it here would
    # show "&lt;" to the annotator.
    assert task["prior_answers"] == [{
        "schema": "concept_definition", "title": "Definition",
        "lines": [answer], "collapsible": True, "open": False}]


def test_each_participant_gets_only_their_own_answer(pocket_server):
    base = pocket_server.base_url
    s = _participant(base, "pk_two", "A thin ideology")
    [block] = s.get(f"{base}/pocket/api/task", timeout=5).json()["prior_answers"]
    assert block["lines"] == ["A thin ideology"]


def test_the_cached_pocket_page_holds_no_answer(pocket_server):
    """The service worker serves /pocket from its cache to whoever signs in
    next on the device, so the page must not contain anyone's answer."""
    base = pocket_server.base_url
    s = _participant(base, "pk_three", "Unmistakable-definition-text")
    html = s.get(f"{base}/pocket", timeout=5).text
    assert 'id="pk-prior-answers"' in html
    assert "Unmistakable-definition-text" not in html
    assert "Definition" not in html.split('id="pk-prior-answers"', 1)[1].split("</div>", 1)[0]
