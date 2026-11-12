"""
Server tests for `answers` on a `type: jspsych` page (issue #177).

A consent page written in jsPsych records the participant's choice. With
`answers: [agree]` the choice becomes `consent_agree`, which the page's
`exit_when` tests, so a participant who declines is screened out instead of
being kept on a closing screen of the timeline.
"""

import json
import os
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

TIMELINE = """window.potatoTimeline = [{
  type: jsPsychSurveyMultiChoice,
  questions: [{name: 'agree', prompt: 'Do you agree?', options: ['Yes', 'No']}]
}];
"""

HEADERS = {"X-Potato-Navigation": "1"}


@pytest.fixture(scope="module")
def consent_server(request):
    test_dir = create_test_directory("jspsych_answers_server")
    data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hello"}])
    tasks = os.path.join(test_dir, "tasks")
    os.makedirs(tasks)
    with open(os.path.join(tasks, "consent.js"), "w") as f:
        f.write(TIMELINE)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{"name": "rating", "annotation_type": "radio",
                             "labels": ["good", "bad"], "description": "Rate."}],
        data_files=[data_file],
        phases={
            "order": ["consent", "annotation"],
            "consent": {
                "type": "jspsych", "timeline": os.path.join(tasks, "consent.js"),
                "plugins": ["survey-multi-choice"],
                "answers": ["agree"],
                "exit_when": {
                    "show_when": [{"schema": "consent_agree", "operator": "equals",
                                   "value": "No"}],
                    "message": "You chose not to take part.",
                },
            },
        },
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
    return server


def _login(base_url, username):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"action": "signup", "email": username, "pass": "pass"}, timeout=5)
    s.post(f"{base_url}/auth", data={"action": "login", "email": username, "pass": "pass"}, timeout=5)
    return s


def _finish_with(s, base, trial):
    html = s.get(f"{base}/", timeout=5).text
    m = re.search(r'<script type="application/json" id="potato-runtime-config">(.*?)</script>',
                  html, re.S)
    assert m, "not on the jsPsych consent page"
    cfg = json.loads(m.group(1))
    body = {"page": cfg["page"], "run_id": cfg["run_id"], "trials": [trial]}
    r = s.post(f"{base}{cfg['endpoints']['finish']}", json=body, headers=HEADERS, timeout=5)
    assert r.status_code == 200, r.text
    return s.get(f"{base}/", timeout=5).text


def _survey_trial(choice):
    return {"trial_type": "survey-multi-choice", "trial_index": 0, "rt": 900,
            "response": {"agree": choice}}


def test_declining_screens_out(consent_server):
    s = _login(consent_server.base_url, "jsa_no")
    html = _finish_with(s, consent_server.base_url, _survey_trial("No"))
    assert 'id="screened-out"' in html
    assert "You chose not to take part." in html


def test_agreeing_continues_to_annotation(consent_server):
    s = _login(consent_server.base_url, "jsa_yes")
    html = _finish_with(s, consent_server.base_url, _survey_trial("Yes"))
    assert 'id="screened-out"' not in html
    assert 'data-schema-name="rating"' in html
    from potato.user_state_management import get_user_state_manager
    rec = get_user_state_manager().get_user_state("jsa_yes").flow_record
    assert rec["runtime_answers"] == {"consent_agree": "Yes"}


def test_a_data_field_counts_too(consent_server):
    # `data: {agree: 'No'}` on a button trial, not a survey question.
    s = _login(consent_server.base_url, "jsa_data")
    html = _finish_with(s, consent_server.base_url, {
        "trial_type": "html-button-response", "trial_index": 0, "response": 1,
        "agree": "No"})
    assert 'id="screened-out"' in html
