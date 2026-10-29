"""
Server tests for page-level show_when / exit_when (experiment flow).

A participant answers a screener over the real save route, submits the page
the way the browser does, and the next GET lands on the page the rule picks:
the follow-up for smokers, the general page for non-smokers, and the
screen-out page for minors.

The screener's questions are `required: true`, and the server enforces that:
a participant who submits the page without answering stays on it, so the
screen-out rule cannot be skipped.
"""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)


def _write(test_dir, name, questions):
    path = os.path.join(test_dir, name)
    with open(path, "w") as f:
        json.dump(questions, f)
    return path


def _login(base_url, username):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"action": "signup", "email": username, "pass": "pass"}, timeout=5)
    s.post(f"{base_url}/auth", data={"action": "login", "email": username, "pass": "pass"}, timeout=5)
    return s


def _submit_page(s, base_url, annotations):
    r = s.post(f"{base_url}/updateinstance",
               json={"instance_id": "__phase_page__", "annotations": annotations,
                     "span_annotations": []}, timeout=5)
    assert r.status_code == 200, r.text
    r = s.post(f"{base_url}/annotate", json={"action": "next_instance"},
               allow_redirects=True, timeout=5)
    return r


@pytest.fixture(scope="module")
def flow_server(request):
    test_dir = create_test_directory("phase_branching_server")
    data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hello"}])
    screener = _write(test_dir, "screener.json", [
        {"name": "smoker", "annotation_type": "radio", "description": "Do you smoke?",
         "labels": ["Yes", "No"], "label_requirement": {"required": True}},
        {"name": "age", "annotation_type": "number", "description": "Your age?",
         "label_requirement": {"required": True}},
        # Required only when shown: a non-smoker never sees it.
        {"name": "smoke_years", "annotation_type": "number",
         "description": "Years smoking?", "label_requirement": {"required": True},
         "display_logic": {"show_when": [
             {"schema": "smoker", "operator": "equals", "value": "Yes"}]}},
    ])
    smoking = _write(test_dir, "smoking.json", [
        {"name": "packs_per_day", "annotation_type": "number",
         "description": "Packs per day?"},
    ])
    general = _write(test_dir, "general.json", [
        {"name": "general_q", "annotation_type": "text",
         "description": "Anything else?"},
    ])
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{"name": "rating", "annotation_type": "radio",
                             "labels": ["good", "bad"], "description": "Rate."}],
        data_files=[data_file],
        phases={
            "order": ["screener", "smoking", "general", "annotation"],
            "screener": {
                "type": "prestudy", "file": screener,
                "exit_when": {
                    "show_when": [{"schema": "age", "operator": "lt", "value": 18}],
                    "message": "This study is for adults only.",
                },
            },
            "smoking": {
                "type": "prestudy", "file": smoking,
                "show_when": [{"schema": "smoker", "operator": "equals", "value": "Yes"}],
            },
            "general": {"type": "prestudy", "file": general},
        },
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
    return server


def test_first_page_is_screener(flow_server):
    s = _login(flow_server.base_url, "first_page")
    r = s.get(f"{flow_server.base_url}/", timeout=5)
    assert 'data-schema-name="smoker"' in r.text


def test_smoker_sees_followup(flow_server):
    s = _login(flow_server.base_url, "smoker_user")
    s.get(f"{flow_server.base_url}/", timeout=5)
    r = _submit_page(s, flow_server.base_url, {"smoker:::Yes": "Yes", "age:::age": "40",
                                               "smoke_years:::smoke_years": "5"})
    assert 'data-schema-name="packs_per_day"' in r.text


def test_non_smoker_skips_followup(flow_server):
    s = _login(flow_server.base_url, "non_smoker")
    s.get(f"{flow_server.base_url}/", timeout=5)
    r = _submit_page(s, flow_server.base_url, {"smoker:::No": "No", "age:::age": "40"})
    assert 'data-schema-name="packs_per_day"' not in r.text
    assert 'data-schema-name="general_q"' in r.text


def test_minor_is_screened_out(flow_server):
    s = _login(flow_server.base_url, "minor_user")
    s.get(f"{flow_server.base_url}/", timeout=5)
    r = _submit_page(s, flow_server.base_url, {"smoker:::No": "No", "age:::age": "16"})
    assert 'id="screened-out"' in r.text
    assert "This study is for adults only." in r.text
    # And it sticks: the participant cannot get back into the study.
    again = s.get(f"{flow_server.base_url}/", timeout=5)
    assert 'id="screened-out"' in again.text


def _phase_page(username):
    from potato.user_state_management import get_user_state_manager
    return get_user_state_manager().get_user_state(username).get_current_phase_and_page()[1]


@pytest.mark.parametrize("answers", [
    {},                                                    # nothing at all
    {"smoker:::No": "No"},                                 # age, the screen-out question, left out
    {"smoker:::No": "No", "age:::age": "   "},             # whitespace is not an age
    {"smoker:::Yes": "Yes", "age:::age": "40"},            # the follow-up it revealed left out
], ids=["empty", "no_age", "blank_age", "no_followup"])
def test_a_required_question_left_out_keeps_the_participant_on_the_page(flow_server, answers):
    user = "skipper_" + "_".join(sorted(answers)).replace(":", "") or "skipper"
    s = _login(flow_server.base_url, user)
    s.get(f"{flow_server.base_url}/", timeout=5)
    r = _submit_page(s, flow_server.base_url, answers)
    assert r.status_code == 400
    assert _phase_page(user) == "screener"
    # A bare form POST, which skips the browser's check, is refused too.
    assert s.post(f"{flow_server.base_url}/prestudy", data={}, timeout=5).status_code == 400
    assert _phase_page(user) == "screener"
    r = s.get(f"{flow_server.base_url}/", timeout=5)
    assert 'data-schema-name="smoker"' in r.text
    assert 'id="screened-out"' not in r.text


def test_skip_and_screen_out_are_persisted(flow_server):
    s = _login(flow_server.base_url, "persist_user")
    s.get(f"{flow_server.base_url}/", timeout=5)
    _submit_page(s, flow_server.base_url, {"smoker:::No": "No", "age:::age": "30"})
    state_file = os.path.join(_output_dir(flow_server), "persist_user", "user_state.json")
    # The skip is saved on the next state write; the page submit triggers one.
    s.get(f"{flow_server.base_url}/", timeout=5)
    with open(state_file) as f:
        state = json.load(f)
    assert [p["page"] for p in state["flow_record"]["skipped_pages"]] == ["smoking"]


def _output_dir(server):
    import yaml
    with open(server.config) as f:
        cfg = yaml.safe_load(f)
    out = cfg["output_annotation_dir"]
    if not os.path.isabs(out):
        out = os.path.join(os.path.dirname(server.config), out)
    return out


def test_an_answer_to_a_hidden_question_is_not_kept(flow_server):
    """display_logic hides smoke_years from a non-smoker in the browser, but a
    POST that answered it anyway was stored as if the question had been
    shown."""
    from potato.phase import UserPhase
    from potato.user_state_management import get_user_state_manager

    s = _login(flow_server.base_url, "hidden_answer")
    s.get(f"{flow_server.base_url}/", timeout=5)
    r = _submit_page(s, flow_server.base_url, {"smoker:::No": "No", "age:::age": "30",
                                               "smoke_years:::smoke_years": "12"})
    assert 'data-schema-name="general_q"' in r.text
    state = get_user_state_manager().get_user_state("hidden_answer")
    kept = {label.get_schema() for label in
            state.phase_to_page_to_label_to_value[UserPhase.PRESTUDY]["screener"]}
    assert kept == {"smoker", "age"}
