"""
Playwright UI tests for SurveyFlow conditional display_logic (issue #165).

Drives a real browser through a SurveyFlow with conditional questions and
verifies the behavior the issue asks for:

- same-page: a question hidden by display_logic reveals when its trigger is met;
- required-field exclusion: a hidden required question does NOT block "Continue",
  but a revealed empty required question DOES;
- cross-page: a poststudy question shows based on a prestudy answer.

Playwright is used (not Selenium) because it renders transitions reliably in
headless mode and has a simple wait_for_function for polling class state.
"""

import json
import os

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)


PRESTUDY = [
    {"name": "prior_experience", "annotation_type": "radio",
     "description": "Have you annotated before?", "labels": ["Yes", "No"],
     "label_requirement": {"required": True}},
    {"name": "experience_details", "annotation_type": "text",
     "description": "Describe your experience.",
     "label_requirement": {"required": True},
     "display_logic": {"show_when": [
         {"schema": "prior_experience", "operator": "equals", "value": "Yes"}]}},
]

POSTSTUDY = [
    {"name": "overall_rating", "annotation_type": "radio",
     "description": "Rate the task.", "labels": ["Good", "Bad"],
     "label_requirement": {"required": True}},
    {"name": "experience_match", "annotation_type": "radio",
     "description": "Did it match your expectations?", "labels": ["Yes", "No"],
     "label_requirement": {"required": True},
     "display_logic": {"show_when": [
         {"schema": "prior_experience", "operator": "equals", "value": "Yes"}]}},
]


def _write_json(test_dir, name, data):
    path = os.path.join(test_dir, name)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("surveyflow_dl_ui")
    data_file = create_test_data_file(test_dir, [{"id": "1", "text": "an item to rate"}])
    prestudy_file = _write_json(test_dir, "prestudy.json", PRESTUDY)
    poststudy_file = _write_json(test_dir, "poststudy.json", POSTSTUDY)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[
            {"name": "sentiment", "annotation_type": "radio", "labels": ["pos", "neg"],
             "description": "Sentiment?", "label_requirement": {"required": True}}
        ],
        data_files=[data_file],
        phases={
            "order": ["prestudy", "annotation", "poststudy"],
            "prestudy": {"type": "prestudy", "file": prestudy_file},
            "poststudy": {"type": "poststudy", "file": poststudy_file},
        },
    )
    srv = FlaskTestServer(config=config_file)
    if not srv.start():
        pytest.fail("Failed to start Flask test server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture
def page(server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        # Register + login through the real endpoints (cookies shared with the page).
        uid = "ui_user"
        context.request.post(f"{server.base_url}/register",
                             form={"action": "signup", "email": uid, "pass": "pass"})
        context.request.post(f"{server.base_url}/auth",
                             form={"action": "login", "email": uid, "pass": "pass"})
        pg = context.new_page()
        yield pg
        context.close()
        browser.close()


def _is_hidden(page, schema):
    return page.evaluate(
        """(s) => {
            const c = document.querySelector('[data-display-logic-target="true"][data-schema-name="'+s+'"]');
            return c ? c.classList.contains('display-logic-hidden') : null;
        }""",
        schema,
    )


def _pick_radio(page, schema, value):
    page.evaluate(
        """([s, v]) => {
            const r = Array.from(document.querySelectorAll('input[type=radio]'))
                .find(r => r.getAttribute('schema') === s && r.value === v);
            if (r) r.click();
        }""",
        [schema, value],
    )


def _goto_annotate(page, server):
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_load_state("networkidle")


class TestSurveyflowConditionalUI:
    def test_same_page_reveal_and_required_exclusion(self, page, server):
        _goto_annotate(page, server)
        page.wait_for_function("() => typeof displayLogicManager !== 'undefined' && displayLogicManager")

        # experience_details starts hidden
        assert _is_hidden(page, "experience_details") is True

        # Selecting "Yes" reveals it
        _pick_radio(page, "prior_experience", "Yes")
        page.wait_for_function(
            """() => {
                const c = document.querySelector('[data-schema-name="experience_details"][data-display-logic-target="true"]');
                return c && !c.classList.contains('display-logic-hidden');
            }"""
        )
        assert _is_hidden(page, "experience_details") is False

        # Selecting "No" hides it again — and Continue must NOT be blocked even
        # though experience_details is required (it is hidden).
        _pick_radio(page, "prior_experience", "No")
        page.wait_for_function(
            """() => {
                const c = document.querySelector('[data-schema-name="experience_details"][data-display-logic-target="true"]');
                return c && c.classList.contains('display-logic-hidden');
            }"""
        )
        valid = page.evaluate("() => validateRequiredFields()")
        assert valid is True, "hidden required question should not block Continue"

        # But once revealed and empty, it DOES block.
        _pick_radio(page, "prior_experience", "Yes")
        page.wait_for_function(
            """() => {
                const c = document.querySelector('[data-schema-name="experience_details"][data-display-logic-target="true"]');
                return c && !c.classList.contains('display-logic-hidden');
            }"""
        )
        valid2 = page.evaluate("() => validateRequiredFields()")
        assert valid2 is False, "revealed empty required question should block Continue"

    def test_cross_page_reveal_from_prestudy_answer(self, page, server):
        _goto_annotate(page, server)
        page.wait_for_function("() => typeof displayLogicManager !== 'undefined' && displayLogicManager")

        # Answer prestudy: prior_experience=Yes + fill the revealed detail, then advance.
        _pick_radio(page, "prior_experience", "Yes")
        page.wait_for_function(
            """() => {
                const c = document.querySelector('[data-schema-name="experience_details"][data-display-logic-target="true"]');
                return c && !c.classList.contains('display-logic-hidden');
            }"""
        )
        page.evaluate(
            """() => {
                const t = document.querySelector('.annotation-form[data-schema-name="experience_details"] textarea, .annotation-form[data-schema-name="experience_details"] input[type=text]');
                if (t) { t.value = 'prior work'; t.dispatchEvent(new Event('input', {bubbles:true})); t.dispatchEvent(new Event('change', {bubbles:true})); }
            }"""
        )
        page.wait_for_timeout(900)  # let autosave flush
        page.evaluate("() => navigateToNext()")
        page.wait_for_load_state("networkidle")

        # Annotation phase: answer the single instance and advance.
        page.wait_for_function("() => window.config && window.config.is_annotation_page === true")
        _pick_radio(page, "sentiment", "pos")
        page.wait_for_timeout(900)
        page.evaluate("() => navigateToNext()")
        page.wait_for_load_state("networkidle")

        # Poststudy: experience_match is gated on the PRESTUDY answer (cross-page),
        # so it must be visible on load.
        page.wait_for_function("() => typeof displayLogicManager !== 'undefined' && displayLogicManager")
        assert page.evaluate("() => !!window.priorPhaseAnswersRaw") is True
        assert _is_hidden(page, "experience_match") is False
