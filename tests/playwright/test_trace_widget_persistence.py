"""
Browser test: trace-review widgets still show an answer after navigating back.

These widgets build their controls from the hidden input when their script
runs. annotation.js then clears every text input, radio and checkbox on the
page (``clearAllFormInputs``) and, in ``loadAnnotations``, puts back only what
the markup itself carries: a text input's ``value`` attribute and a
checkbox's or radio's ``checked`` attribute. A control the widget fills
through the property alone (``input.value = ...``, ``radio.checked = true``)
comes back blank; code_review lost its verdict and comment file path that
way. Each case answers its example's first item through the UI, goes Next
then Previous, and reads the visible controls.

Persistence is checked by navigating away and back, never ``page.reload()``
(browsers cache form state across a refresh).
"""

import os
import shutil

import pytest
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.teardown_watchdog import TEST_TEARDOWN_TIMEOUT_SECONDS, bounded_teardown
from tests.helpers.test_utils import create_test_directory
from tests.playwright.test_base import BasePlaywrightTest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Each case: the example, scheme overrides, the steps that answer the first
# item, and the visible state those steps leave ({selector: value or checked}).
CASES = {
    "tool_call_review": {
        "example": "examples/agent-traces/tool-call-review",
        "steps": [("click", ".tcr-vbtn[data-idx='1'][data-v='wrong_args']"),
                  ("fill", ".tcr-notes[data-idx='1']", "restaurant is empty")],
        "shown": {".tcr-notes[data-idx='1']": "restaurant is empty"},
    },
    "gui_trajectory": {
        "example": "examples/agent-traces/gui-trajectory",
        "steps": [("click", ".gt-vbtn[data-idx='1'][data-v='hallucinated']"),
                  ("fill", ".gt-notes[data-idx='1']", "no such button")],
        "shown": {".gt-notes[data-idx='1']": "no such button"},
    },
    "multimodal_reasoning": {
        "example": "examples/agent-traces/multimodal-reasoning",
        "steps": [("click", ".mmr-vbtn[data-idx='2'][data-v='visual_hallucination']"),
                  ("fill", ".mmr-notes[data-idx='2']", "the chart has no red bar")],
        "shown": {".mmr-notes[data-idx='2']": "the chart has no red bar"},
    },
    "speech_transcript": {
        "example": "examples/agent-traces/speech-transcript",
        "steps": [("click", ".st-ebtn[data-idx='0'][data-e='asr_error']"),
                  ("fill", ".st-correction[data-idx='0']", "what's the weather like today")],
        "shown": {".st-correction[data-idx='0']": "what's the weather like today"},
    },
    "emergent_behavior": {
        "example": "examples/agent-traces/emergent-behavior",
        "steps": [("check", ".eb-cb[data-b='groupthink'][data-t='0']"),
                  ("check", ".eb-cb[data-b='groupthink'][data-t='2']"),
                  ("fill", ".eb-note[data-b='groupthink']", "everyone defers to the planner")],
        "shown": {".eb-cb[data-b='groupthink'][data-t='0']": True,
                  ".eb-cb[data-b='groupthink'][data-t='2']": True,
                  ".eb-note[data-b='groupthink']": "everyone defers to the planner"},
    },
    "agent_scorecard": {
        "example": "examples/agent-traces/agent-scorecard",
        "steps": [("check", ".asc-ms-cb[data-m='plan produced']")],
        "shown": {".asc-ms-cb[data-m='plan produced']": True,
                  ".asc-ms-cb[data-m='result verified']": False},
    },
    "trajectory_eval": {
        "example": "examples/agent-traces/trajectory-evaluation",
        "steps": [("click", ".traj-step-card[data-step-index='0'] .traj-correctness-btn[data-value='incorrect']"),
                  ("check", ".traj-step-card[data-step-index='0'] input[type=radio][value='major']"),
                  ("fill", ".traj-step-card[data-step-index='0'] .traj-rationale", "searched the wrong table")],
        "shown": {".traj-step-card[data-step-index='0'] input[type=radio][value='major']": True,
                  ".traj-step-card[data-step-index='0'] .traj-rationale": "searched the wrong table"},
    },
    "trajectory_edit": {
        "example": "examples/agent-traces/trajectory-correction",
        "overrides": {"require_reason_on_edit": True},
        "steps": [("fill", ".trajedit-textarea[data-step='0']", "search(query='weather in Paris')"),
                  ("fill", ".trajedit-reason[data-step='0']", "wrong city")],
        "shown": {".trajedit-textarea[data-step='0']": "search(query='weather in Paris')",
                  ".trajedit-reason[data-step='0']": "wrong city"},
    },
}

SHOWN_JS = """([schema, selectors]) => {
    const form = document.getElementById(schema);
    const out = {};
    for (const sel of selectors) {
        const el = form && form.querySelector(sel);
        if (!el) { out[sel] = null; continue; }
        out[sel] = (el.type === 'checkbox' || el.type === 'radio') ? el.checked : el.value;
    }
    return out;
}"""


def _example_server(annotation_type, case):
    """A copy of the example with the login and survey pages left out."""
    work = os.path.join(create_test_directory(f"trace_persist_{annotation_type}"), "example")
    shutil.copytree(os.path.join(REPO, case["example"]), work, ignore=shutil.ignore_patterns(
        "annotation_output", "project.sqlite*", "layouts", "test_config_port_*"))
    path = os.path.join(work, "config.yaml")
    with open(path) as f:
        config = yaml.safe_load(f)
    for key in ("phases", "surveyflow", "training", "prestudy", "poststudy", "consent",
                "instructions", "crowdsourcing", "login"):
        config.pop(key, None)
    for scheme in config["annotation_schemes"]:
        if scheme["annotation_type"] == annotation_type:
            scheme.update(case.get("overrides", {}))
    config["user_config"] = {"allow_all_users": True, "users": []}
    config["require_password"] = False
    with open(path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    return FlaskTestServer(config_file=path)


@pytest.mark.playwright
class TestTraceWidgetPersistence(BasePlaywrightTest):

    @pytest.fixture
    def example_server(self, request):
        annotation_type = request.param
        srv = _example_server(annotation_type, CASES[annotation_type])
        if not srv.start():
            pytest.fail(f"the {annotation_type} example server did not start")
        yield srv
        with bounded_teardown("trace_persist", seconds=TEST_TEARDOWN_TIMEOUT_SECONDS,
                              announce=False):
            srv.stop()

    def _instance_id(self, page):
        instance_id = page.evaluate(
            "() => (window.currentInstance && window.currentInstance.id) || null")
        assert instance_id, "could not determine the current instance id"
        return instance_id

    @pytest.mark.parametrize("example_server", list(CASES), indirect=True)
    def test_answer_survives_navigation(self, page, example_server, request):
        annotation_type = request.node.callspec.params["example_server"]
        case = CASES[annotation_type]
        self.register_and_login(page, example_server)
        page.goto(f"{example_server.base_url}/annotate")
        form = page.locator(f"form[data-annotation-type='{annotation_type}']")
        schema = form.get_attribute("data-schema-name")
        first = case["steps"][0][1]
        page.wait_for_selector(f"#{schema} {first}")
        instance_id = self._instance_id(page)

        for kind, selector, *value in case["steps"]:
            control = form.locator(selector)
            if kind == "click":
                control.click()
            elif kind == "check":
                control.check()
            else:
                control.fill(value[0])
        self.wait_for_debounce(page)

        # The server holds the answer before we look at the page again.
        stored = self.verify_server_annotations(page, example_server, instance_id)
        assert schema in str(stored), stored
        assert page.evaluate(SHOWN_JS, [schema, list(case["shown"])]) == case["shown"]

        self.click_next(page)
        page.wait_for_function(
            "id => window.currentInstance && window.currentInstance.id !== id",
            arg=instance_id)
        self.click_prev(page)
        page.wait_for_function(
            "id => window.currentInstance && window.currentInstance.id === id",
            arg=instance_id)
        page.wait_for_selector(f"#{schema} {first}")
        # Let every post-load step (populateInputValues, instance-ready) run.
        page.wait_for_timeout(500)

        shown = page.evaluate(SHOWN_JS, [schema, list(case["shown"])])
        assert shown == case["shown"], shown
