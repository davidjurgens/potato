"""prior_answers end to end: a free-text answer given on a prestudy page is
shown, escaped, on every annotation page of that participant, and only theirs."""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file, create_test_directory)

QUESTION = "In your own words, how would you define the concept?"


@pytest.fixture(scope="module")
def definition_server(request):
    d = create_test_directory("prior_answers_server")
    data = create_test_data_file(d, [{"id": "i1", "text": "First item."},
                                     {"id": "i2", "text": "Second item."}])
    page = os.path.join(d, "pre.json")
    with open(page, "w") as f:
        json.dump([{"name": "concept_definition", "annotation_type": "text",
                    "description": QUESTION, "label_requirement": {"required": True}}], f)
    config = create_test_config(
        d, annotation_schemes=[{"name": "fits", "annotation_type": "radio",
                                "labels": ["yes", "no"], "description": "Does it fit?"}],
        data_files=[data],
        phases={"order": ["definition", "annotation"],
                "definition": {"type": "prestudy", "file": page}},
        additional_config={"prior_answers": [
            {"schema": "concept_definition", "title": "Definition"}]})
    server = FlaskTestServer(config=config)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    return server


def _participant(base, name, answer):
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "p"}, timeout=5)
    survey = s.get(f"{base}/", timeout=5).text
    assert QUESTION in survey
    s.post(f"{base}/updateinstance", json={
        "instance_id": "__phase_page__",
        "annotations": {"concept_definition:::text_box": answer},
        "span_annotations": []}, timeout=5)
    return s, s.post(f"{base}/annotate", json={"action": "next_instance"}, timeout=5).text


def test_own_answer_shows_escaped_on_every_annotation_page(definition_server):
    base = definition_server.base_url
    s, page = _participant(base, "pa_one", "Elites <script>x</script> vs. people")
    assert 'class="prior-answer-block" data-prior-answer-schema="concept_definition"' in page
    assert "<summary>Definition</summary>" in page
    assert "Elites &lt;script&gt;x&lt;/script&gt; vs. people" in page
    assert "<script>x</script>" not in page
    # Closed by default: the annotator opens it with a click.
    assert '<details class="prior-answer-block" data-prior-answer-schema="concept_definition">' in page

    second = s.post(f"{base}/annotate", json={"action": "next_instance"}, timeout=5).text
    assert "Elites &lt;script&gt;x&lt;/script&gt; vs. people" in second


def test_each_participant_sees_only_their_own_answer(definition_server):
    base = definition_server.base_url
    _s, page = _participant(base, "pa_two", "A thin ideology")
    assert "A thin ideology" in page
    assert "Elites &lt;script&gt;" not in page

