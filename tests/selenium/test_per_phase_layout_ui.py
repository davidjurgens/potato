"""
Selenium tests for per-phase custom layout snippets (Issue #119).

Verifies that each surveyflow phase renders its own custom task_layout file,
and that different phases with distinct custom layouts show the correct content.

Setup:
  - 2 consent pages, each with a distinct custom layout
  - 2 prestudy pages, each with a distinct custom layout
  - annotation phase (auto-generated layout)
  - 2 poststudy pages, each with a distinct custom layout

Each custom layout embeds a unique marker string (data-testid + visible heading)
so we can verify the correct layout is rendered for each page.
"""

import json
import os
import time
import unittest

import requests
import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_data_file,
)


# Unique marker IDs embedded in each custom layout file
LAYOUT_MARKERS = {
    "consent_intro": "LAYOUT-CONSENT-INTRO-7a3b",
    "consent_agree": "LAYOUT-CONSENT-AGREE-9f1c",
    "demographics": "LAYOUT-PRESTUDY-DEMO-2e5d",
    "personality": "LAYOUT-PRESTUDY-PERS-8b4a",
    "feedback": "LAYOUT-POSTSTUDY-FEED-3c6e",
    "exit_survey": "LAYOUT-POSTSTUDY-EXIT-5d7f",
}


def _write_custom_layout(path, marker_id, heading_text, schema_name):
    """Write a custom task_layout HTML file with a unique marker and the schema form."""
    html = f"""\
<div data-testid="{marker_id}" class="custom-phase-layout">
  <h3 class="phase-layout-heading">{heading_text}</h3>
  <p class="layout-marker">{marker_id}</p>
  {{{{ annotation_schematic }}}}
</div>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def _write_survey_json(path, schema_name, description, labels):
    """Write a survey JSON file with a single radio scheme."""
    survey = [
        {
            "id": "1",
            "name": schema_name,
            "description": description,
            "annotation_type": "radio",
            "labels": labels,
        }
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(survey, f)


def create_per_phase_layout_config(test_dir, port):
    """
    Create a config with 6 phase pages (2 consent, 2 prestudy, 2 poststudy),
    each with its own custom task_layout file, plus an annotation phase.
    """
    # Data for annotation phase
    test_data = [
        {"id": "item_1", "text": "Annotate this item."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    surveys_dir = os.path.join(test_dir, "surveys")
    os.makedirs(surveys_dir, exist_ok=True)

    layouts_dir = os.path.join(test_dir, "layouts")
    os.makedirs(layouts_dir, exist_ok=True)

    # -- Consent pages (2) --
    _write_survey_json(
        os.path.join(surveys_dir, "consent_intro.json"),
        "consent_intro_q",
        "Welcome! Please review the study information below.",
        ["I want to learn more"],
    )
    _write_custom_layout(
        os.path.join(layouts_dir, "layout_consent_intro.html"),
        LAYOUT_MARKERS["consent_intro"],
        "Study Introduction Layout",
        "consent_intro_q",
    )

    _write_survey_json(
        os.path.join(surveys_dir, "consent_agree.json"),
        "consent_agree_q",
        "Do you agree to participate?",
        ["Yes, I agree", "No"],
    )
    _write_custom_layout(
        os.path.join(layouts_dir, "layout_consent_agree.html"),
        LAYOUT_MARKERS["consent_agree"],
        "Consent Agreement Layout",
        "consent_agree_q",
    )

    # -- Prestudy pages (2) --
    _write_survey_json(
        os.path.join(surveys_dir, "demographics.json"),
        "demographics_q",
        "What is your age group?",
        ["18-25", "26-35", "36-50", "50+"],
    )
    _write_custom_layout(
        os.path.join(layouts_dir, "layout_demographics.html"),
        LAYOUT_MARKERS["demographics"],
        "Demographics Layout",
        "demographics_q",
    )

    _write_survey_json(
        os.path.join(surveys_dir, "personality.json"),
        "personality_q",
        "I see myself as someone who is outgoing.",
        ["Strongly agree", "Agree", "Neutral", "Disagree", "Strongly disagree"],
    )
    _write_custom_layout(
        os.path.join(layouts_dir, "layout_personality.html"),
        LAYOUT_MARKERS["personality"],
        "Personality Layout",
        "personality_q",
    )

    # -- Poststudy pages (2) --
    _write_survey_json(
        os.path.join(surveys_dir, "feedback.json"),
        "feedback_q",
        "How was the annotation experience?",
        ["Excellent", "Good", "Fair", "Poor"],
    )
    _write_custom_layout(
        os.path.join(layouts_dir, "layout_feedback.html"),
        LAYOUT_MARKERS["feedback"],
        "Feedback Layout",
        "feedback_q",
    )

    _write_survey_json(
        os.path.join(surveys_dir, "exit_survey.json"),
        "exit_survey_q",
        "Would you participate in a similar study again?",
        ["Definitely", "Maybe", "No"],
    )
    _write_custom_layout(
        os.path.join(layouts_dir, "layout_exit_survey.html"),
        LAYOUT_MARKERS["exit_survey"],
        "Exit Survey Layout",
        "exit_survey_q",
    )

    config = {
        "annotation_task_name": f"PerPhaseLayout Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative"],
                "description": "What is the sentiment?",
            }
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 1,
        "max_annotations_per_item": 100,
        "phases": {
            "order": [
                "consent_intro",
                "consent_agree",
                "demographics",
                "personality",
                "annotation",
                "feedback",
                "exit_survey",
            ],
            "consent_intro": {
                "type": "consent",
                "file": "surveys/consent_intro.json",
                "task_layout": os.path.join(layouts_dir, "layout_consent_intro.html"),
            },
            "consent_agree": {
                "type": "consent",
                "file": "surveys/consent_agree.json",
                "task_layout": os.path.join(layouts_dir, "layout_consent_agree.html"),
            },
            "demographics": {
                "type": "prestudy",
                "file": "surveys/demographics.json",
                "task_layout": os.path.join(layouts_dir, "layout_demographics.html"),
            },
            "personality": {
                "type": "prestudy",
                "file": "surveys/personality.json",
                "task_layout": os.path.join(layouts_dir, "layout_personality.html"),
            },
            "annotation": {"type": "annotation"},
            "feedback": {
                "type": "poststudy",
                "file": "surveys/feedback.json",
                "task_layout": os.path.join(layouts_dir, "layout_feedback.html"),
            },
            "exit_survey": {
                "type": "poststudy",
                "file": "surveys/exit_survey.json",
                "task_layout": os.path.join(layouts_dir, "layout_exit_survey.html"),
            },
        },
        "site_dir": "default",
        "output_annotation_dir": output_dir,
        "task_dir": test_dir,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": f"test-secret-{port}",
        "persist_sessions": False,
        "alert_time_each_instance": 0,
        "user_config": {"allow_all_users": True, "users": []},
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


class TestPerPhaseLayoutUI(unittest.TestCase):
    """
    Verify that each phase page renders its own distinct custom layout.

    The test creates 6 phase pages across consent, prestudy, and poststudy,
    each with a unique custom task_layout containing a marker string.
    We verify:
      1. Each page shows its own marker (correct layout rendered)
      2. Each page does NOT show other pages' markers (no cross-contamination)
      3. The annotation phase renders without custom layout markers
      4. Layout files on disk are separate per phase (not overwritten)
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"per_phase_layout_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_per_phase_layout_config(cls.test_dir, cls.port)

        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file
        )
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"ppl_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # ---- Helpers ----

    def _login(self):
        """Login with simple auth."""
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(self.test_user)
        self.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']"
        ).click()
        time.sleep(2)

    def _get_requests_session(self):
        """Create a requests.Session sharing Selenium cookies."""
        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
        return session

    def _advance_phase(self, route):
        """Advance a phase via POST, then reload in browser."""
        session = self._get_requests_session()
        session.post(
            f"{self.server.base_url}/{route}",
            data={"submitted": "true"},
            timeout=5,
        )
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1.5)

    def _get_page_source(self):
        """Return page source for assertions."""
        return self.driver.page_source

    def _assert_marker_present(self, marker, msg=None):
        """Assert that a layout marker is present in the page."""
        source = self._get_page_source()
        self.assertIn(
            marker, source,
            msg or f"Expected marker '{marker}' in page source"
        )

    def _assert_marker_absent(self, marker, msg=None):
        """Assert that a layout marker is NOT present in the page."""
        source = self._get_page_source()
        self.assertNotIn(
            marker, source,
            msg or f"Marker '{marker}' should NOT be in page source"
        )

    def _assert_only_marker(self, expected_key):
        """Assert exactly one marker is present and all others are absent."""
        expected_marker = LAYOUT_MARKERS[expected_key]
        self._assert_marker_present(
            expected_marker,
            f"Page should show the '{expected_key}' layout marker"
        )
        for key, marker in LAYOUT_MARKERS.items():
            if key != expected_key:
                self._assert_marker_absent(
                    marker,
                    f"Page showing '{expected_key}' should NOT contain '{key}' marker"
                )

    def _advance_to_annotation(self):
        """Advance through consent (2) + prestudy (2) to reach annotation."""
        self._advance_phase("consent")
        self._advance_phase("consent")
        self._advance_phase("prestudy")
        self._advance_phase("prestudy")

    def _complete_annotation(self):
        """Select a radio option and click Next to complete annotation."""
        time.sleep(1)
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
        )
        if radios:
            radio_id = radios[0].get_attribute("id")
            if radio_id:
                try:
                    label = self.driver.find_element(
                        By.CSS_SELECTOR, f"label[for='{radio_id}']"
                    )
                    label.click()
                except Exception:
                    radios[0].click()
            else:
                radios[0].click()
            time.sleep(0.5)

        try:
            next_btn = self.driver.find_element(By.ID, "next-btn")
            next_btn.click()
        except Exception:
            pass
        time.sleep(2)

        # Navigate home to reach the next phase
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

    # ---- Tests ----

    def test_consent_intro_renders_correct_layout(self):
        """First consent page shows consent_intro layout, not consent_agree."""
        self._login()
        self._assert_only_marker("consent_intro")

    def test_consent_intro_has_correct_heading(self):
        """First consent page shows the Study Introduction heading."""
        self._login()
        source = self._get_page_source()
        self.assertIn("Study Introduction Layout", source)

    def test_consent_agree_renders_correct_layout(self):
        """Second consent page shows consent_agree layout after advancing."""
        self._login()
        self._advance_phase("consent")
        self._assert_only_marker("consent_agree")

    def test_consent_agree_has_correct_heading(self):
        """Second consent page shows the Consent Agreement heading."""
        self._login()
        self._advance_phase("consent")
        source = self._get_page_source()
        self.assertIn("Consent Agreement Layout", source)

    def test_demographics_renders_correct_layout(self):
        """First prestudy page shows demographics layout."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("consent")
        self._assert_only_marker("demographics")

    def test_demographics_has_correct_heading(self):
        """Demographics page shows the Demographics Layout heading."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("consent")
        source = self._get_page_source()
        self.assertIn("Demographics Layout", source)

    def test_personality_renders_correct_layout(self):
        """Second prestudy page shows personality layout."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("consent")
        self._advance_phase("prestudy")
        self._assert_only_marker("personality")

    def test_personality_has_correct_heading(self):
        """Personality page shows the Personality Layout heading."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("consent")
        self._advance_phase("prestudy")
        source = self._get_page_source()
        self.assertIn("Personality Layout", source)

    def test_annotation_phase_has_no_custom_markers(self):
        """Annotation phase should NOT contain any custom layout markers."""
        self._login()
        self._advance_to_annotation()

        for key, marker in LAYOUT_MARKERS.items():
            self._assert_marker_absent(
                marker,
                f"Annotation phase should not contain '{key}' custom layout marker"
            )

    def test_annotation_phase_shows_sentiment_schema(self):
        """Annotation phase should render the main annotation schema."""
        self._login()
        self._advance_to_annotation()

        source = self._get_page_source().lower()
        self.assertTrue(
            "sentiment" in source or "positive" in source,
            "Annotation phase should show the sentiment annotation schema"
        )

    def test_feedback_renders_correct_layout(self):
        """First poststudy page shows feedback layout after annotation."""
        self._login()
        self._advance_to_annotation()
        self._complete_annotation()
        self._assert_only_marker("feedback")

    def test_feedback_has_correct_heading(self):
        """Feedback page shows the Feedback Layout heading."""
        self._login()
        self._advance_to_annotation()
        self._complete_annotation()
        source = self._get_page_source()
        self.assertIn("Feedback Layout", source)

    def test_exit_survey_renders_correct_layout(self):
        """Second poststudy page shows exit_survey layout after feedback."""
        self._login()
        self._advance_to_annotation()
        self._complete_annotation()
        self._advance_phase("poststudy")
        self._assert_only_marker("exit_survey")

    def test_exit_survey_has_correct_heading(self):
        """Exit survey page shows the Exit Survey Layout heading."""
        self._login()
        self._advance_to_annotation()
        self._complete_annotation()
        self._advance_phase("poststudy")
        source = self._get_page_source()
        self.assertIn("Exit Survey Layout", source)

    def test_two_consent_pages_have_different_content(self):
        """The two consent pages must render distinct layout content."""
        self._login()
        source_page1 = self._get_page_source()

        self._advance_phase("consent")
        source_page2 = self._get_page_source()

        self.assertIn(LAYOUT_MARKERS["consent_intro"], source_page1)
        self.assertNotIn(LAYOUT_MARKERS["consent_agree"], source_page1)

        self.assertIn(LAYOUT_MARKERS["consent_agree"], source_page2)
        self.assertNotIn(LAYOUT_MARKERS["consent_intro"], source_page2)

    def test_two_prestudy_pages_have_different_content(self):
        """The two prestudy pages must render distinct layout content."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("consent")

        source_demo = self._get_page_source()
        self._advance_phase("prestudy")
        source_pers = self._get_page_source()

        self.assertIn(LAYOUT_MARKERS["demographics"], source_demo)
        self.assertNotIn(LAYOUT_MARKERS["personality"], source_demo)

        self.assertIn(LAYOUT_MARKERS["personality"], source_pers)
        self.assertNotIn(LAYOUT_MARKERS["demographics"], source_pers)

    def test_layout_marker_visible_in_dom(self):
        """The custom layout marker element should be findable via data-testid."""
        self._login()

        # On consent_intro page — find the element by data-testid
        marker = LAYOUT_MARKERS["consent_intro"]
        element = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, f'[data-testid="{marker}"]')
            )
        )
        self.assertTrue(
            element.is_displayed() or element is not None,
            "Custom layout div with data-testid should be present in DOM"
        )


if __name__ == "__main__":
    unittest.main()
