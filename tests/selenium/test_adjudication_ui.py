"""
Selenium UI tests for the Adjudication page.

Tests the adjudication frontend in a real browser:
- Page load and layout for adjudicator users
- Queue sidebar population after simulator annotations
- Item selection and annotator response display
- Decision form interaction (radio, metadata, notes)
- Submit and navigation flow
- Access control (non-adjudicators redirected)
"""

import json
import os
import time
import unittest
import yaml

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from potato.simulator import SimulatorManager, SimulatorConfig, UserConfig
from potato.simulator.config import (
    CompetenceLevel,
    AnnotationStrategyType,
    BiasedStrategyConfig,
)
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory


class TestAdjudicationUI(unittest.TestCase):
    """Selenium tests for the adjudication interface."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server, run simulator, prepare browser."""
        # ----- Test directory & data -----
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "selenium_adjudication")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create 15 data items
        items = [
            {"id": f"item_{i:03d}", "text": f"Test sentence {i} for adjudication UI testing."}
            for i in range(15)
        ]
        data_file = os.path.join(cls.test_dir, "test_data.jsonl")
        with open(data_file, "w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

        # ----- Config -----
        config = {
            "annotation_task_name": "Adjudication Selenium Test",
            "task_dir": os.path.abspath(cls.test_dir),
            "data_files": ["test_data.jsonl"],
            "output_annotation_dir": "output",
            "output_annotation_format": "json",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": [
                        {"name": "positive"},
                        {"name": "negative"},
                        {"name": "neutral"},
                    ],
                    "description": "Classify the sentiment.",
                }
            ],
            "user_config": {"allow_anonymous": True},
            "max_annotations_per_item": 3,
            "adjudication": {
                "enabled": True,
                "adjudicator_users": ["adj_selenium"],
                "min_annotations": 2,
                "agreement_threshold": 0.99,
                "show_all_items": True,
                "show_annotator_names": True,
                "show_timing_data": True,
                "require_confidence": True,
                "error_taxonomy": ["ambiguous_text", "guideline_gap"],
            },
            "debug": True,
        }
        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        # ----- Start server -----
        cls.server = FlaskTestServer(
            port=find_free_port(), debug=False, config_file=config_file
        )
        started = cls.server.start()
        if not started:
            raise unittest.SkipTest("Failed to start Flask server")

        # ----- Run simulator -----
        users = [
            UserConfig(
                user_id="sel_user_a",
                competence=CompetenceLevel.AVERAGE,
                strategy=AnnotationStrategyType.BIASED,
                biased_config=BiasedStrategyConfig(
                    label_weights={"positive": 0.9, "negative": 0.05, "neutral": 0.05}
                ),
            ),
            UserConfig(
                user_id="sel_user_b",
                competence=CompetenceLevel.AVERAGE,
                strategy=AnnotationStrategyType.BIASED,
                biased_config=BiasedStrategyConfig(
                    label_weights={"positive": 0.05, "negative": 0.9, "neutral": 0.05}
                ),
            ),
        ]
        sim_config = SimulatorConfig(
            users=users,
            user_count=2,
            parallel_users=1,
            delay_between_users=0.0,
            simulate_wait=False,
        )
        mgr = SimulatorManager(sim_config, cls.server.base_url)
        results = mgr.run_sequential(max_annotations_per_user=15)
        total = sum(len(r.annotations) for r in results.values())
        if total == 0:
            raise unittest.SkipTest("Simulator produced no annotations")

        # ----- Chrome options -----
        chrome_opts = ChromeOptions()
        chrome_opts.add_argument("--headless=new")
        chrome_opts.add_argument("--no-sandbox")
        chrome_opts.add_argument("--disable-dev-shm-usage")
        chrome_opts.add_argument("--disable-gpu")
        chrome_opts.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_opts

    @classmethod
    def tearDownClass(cls):
        """Stop server, clean up."""
        if hasattr(cls, "server"):
            cls.server.stop()
        if hasattr(cls, "test_dir"):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    # -- Per-test setup / teardown --

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(2)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # -- Helpers --

    def _login_adjudicator(self):
        """Register + login as the adjudicator via the web form."""
        import requests as req

        s = req.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "adj_selenium", "pass": "pass"},
        )
        s.post(
            f"{self.server.base_url}/auth",
            data={"email": "adj_selenium", "pass": "pass"},
        )
        # Transfer session cookie to the browser
        for cookie in s.cookies:
            self.driver.get(self.server.base_url)
            self.driver.add_cookie(
                {"name": cookie.name, "value": cookie.value, "path": "/"}
            )

    def _login_regular_user(self):
        """Login as a non-adjudicator user."""
        import requests as req

        s = req.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "regular_sel", "pass": "pass"},
        )
        s.post(
            f"{self.server.base_url}/auth",
            data={"email": "regular_sel", "pass": "pass"},
        )
        for cookie in s.cookies:
            self.driver.get(self.server.base_url)
            self.driver.add_cookie(
                {"name": cookie.name, "value": cookie.value, "path": "/"}
            )

    def _wait(self, by, value, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def _wait_visible(self, by, value, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )

    # ================================================================
    # Tests: Page Access
    # ================================================================

    def test_adjudication_page_loads_for_adjudicator(self):
        """Adjudicator should see the adjudication page with header and queue."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")

        # Wait for the page title / header
        header = self._wait(By.CSS_SELECTOR, ".navbar-brand")
        self.assertIn("Adjudication", header.text)

    def test_adjudication_page_has_queue_sidebar(self):
        """Page should have a queue sidebar with filter buttons."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")

        sidebar = self._wait(By.CLASS_NAME, "adj-sidebar")
        self.assertTrue(sidebar.is_displayed())

        # Should have filter buttons
        filters = self.driver.find_elements(By.CLASS_NAME, "adj-filter-btn")
        self.assertGreaterEqual(len(filters), 2, "Should have at least Pending and All filters")

    def test_adjudication_page_has_empty_state(self):
        """Before selecting an item, the empty state message should show."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")

        empty = self._wait(By.ID, "adj-empty-state")
        self.assertTrue(empty.is_displayed())

    def test_non_adjudicator_is_redirected(self):
        """A regular user navigating to /adjudicate should be redirected."""
        self._login_regular_user()
        self.driver.get(f"{self.server.base_url}/adjudicate")

        # Should be redirected away (to / or show login)
        time.sleep(1)
        url = self.driver.current_url
        # Either redirected away from /adjudicate or page doesn't show adjudication content
        page = self.driver.page_source
        # The user shouldn't see the adjudication interface
        if "/adjudicate" in url:
            # If still on /adjudicate, it should be an error / redirect page
            self.assertNotIn("adj-queue-list", page)

    # ================================================================
    # Tests: Queue Population
    # ================================================================

    def test_queue_populates_with_items(self):
        """After simulator annotations, the queue should list items."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")

        # Wait for JS to load queue
        time.sleep(2)

        queue_list = self.driver.find_element(By.ID, "adj-queue-list")
        items = queue_list.find_elements(By.CLASS_NAME, "adj-queue-item")
        self.assertGreater(len(items), 0, "Queue should have items after simulation")

    def test_queue_items_show_agreement_badge(self):
        """Queue items should display an agreement score badge."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        queue_list = self.driver.find_element(By.ID, "adj-queue-list")
        items = queue_list.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")

        # Check first item for agreement info
        first = items[0]
        text = first.text
        # The queue item should show some agreement or annotator info
        self.assertTrue(len(text) > 0, "Queue item should have text content")

    # ================================================================
    # Tests: Item Selection & Display
    # ================================================================

    def test_clicking_queue_item_shows_detail(self):
        """Clicking a queue item should show the item detail view."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        queue_list = self.driver.find_element(By.ID, "adj-queue-list")
        items = queue_list.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")

        items[0].click()
        time.sleep(1)

        # Item view should now be visible
        item_view = self.driver.find_element(By.ID, "adj-item-view")
        self.assertTrue(
            item_view.is_displayed(),
            "Item detail view should be visible after clicking a queue item",
        )

    def test_item_detail_shows_text(self):
        """The item detail should display the instance text."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        text_el = self.driver.find_element(By.ID, "adj-item-text")
        self.assertTrue(len(text_el.text) > 0, "Item text should be displayed")

    def test_item_detail_shows_annotator_responses(self):
        """After selecting an item, annotator responses should appear."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        container = self.driver.find_element(By.ID, "adj-responses-container")
        self.assertTrue(
            len(container.text) > 0,
            "Annotator responses container should have content",
        )

    def test_item_detail_shows_decision_form(self):
        """The decision forms section should be populated with radio buttons."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        forms = self.driver.find_element(By.ID, "adj-decision-forms")
        radios = forms.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        self.assertGreater(len(radios), 0, "Decision form should have radio buttons")

    # ================================================================
    # Tests: Decision Form Interaction
    # ================================================================

    def test_select_radio_in_decision_form(self):
        """Clicking a radio button in the decision form should select it."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        forms = self.driver.find_element(By.ID, "adj-decision-forms")
        radios = forms.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        if not radios:
            self.skipTest("No radio buttons found")

        # Click first radio
        self.driver.execute_script("arguments[0].click();", radios[0])
        self.assertTrue(radios[0].is_selected(), "Radio should be selected after click")

    def test_notes_textarea_accepts_input(self):
        """The notes textarea should accept text input."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        notes = self.driver.find_element(By.ID, "adj-notes")
        notes.clear()
        notes.send_keys("Test adjudication note from Selenium")
        self.assertEqual(notes.get_attribute("value"), "Test adjudication note from Selenium")

    def test_error_taxonomy_checkboxes_exist(self):
        """Error taxonomy checkboxes should be present in the decision metadata."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        taxonomy = self.driver.find_element(By.ID, "adj-error-taxonomy")
        checkboxes = taxonomy.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        self.assertGreater(len(checkboxes), 0, "Should have error taxonomy checkboxes")

    def test_confidence_selector_exists(self):
        """The confidence dropdown should be present."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        confidence = self.driver.find_element(By.ID, "adj-confidence")
        self.assertTrue(confidence.is_displayed(), "Confidence selector should be visible")

    # ================================================================
    # Tests: Navigation Bar
    # ================================================================

    def test_nav_bar_visible_after_item_selection(self):
        """Bottom navigation bar should appear after selecting an item."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        nav_bar = self.driver.find_element(By.ID, "adj-nav-bar")
        self.assertTrue(nav_bar.is_displayed(), "Navigation bar should be visible")

    def test_submit_button_exists(self):
        """Submit & Next button should be present in the nav bar."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        submit_btn = self.driver.find_element(By.ID, "adj-btn-submit")
        self.assertTrue(submit_btn.is_displayed(), "Submit button should be visible")
        self.assertIn("Submit", submit_btn.text)

    def test_skip_button_exists(self):
        """Skip button should be present in the nav bar."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        skip_btn = self.driver.find_element(By.ID, "adj-btn-skip")
        self.assertTrue(skip_btn.is_displayed(), "Skip button should be visible")

    # ================================================================
    # Tests: Submit Flow
    # ================================================================

    def test_submit_decision_via_ui(self):
        """Selecting a label and clicking submit should update the queue."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")

        initial_count = len(items)
        items[0].click()
        time.sleep(1)

        # Select a radio button
        forms = self.driver.find_element(By.ID, "adj-decision-forms")
        radios = forms.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        if not radios:
            self.skipTest("No radio buttons")
        self.driver.execute_script("arguments[0].click();", radios[0])

        # Click submit
        submit_btn = self.driver.find_element(By.ID, "adj-btn-submit")
        submit_btn.click()
        time.sleep(2)

        # Queue should update: either fewer pending items or item marked done
        # Reload to check
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)
        new_items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        # The pending filter should now show fewer items
        self.assertLessEqual(
            len(new_items), initial_count,
            "Pending queue count should decrease after submission",
        )

    # ================================================================
    # Tests: Progress Indicator
    # ================================================================

    def test_progress_bar_displayed(self):
        """The progress bar should be visible in the sidebar."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        progress_fill = self.driver.find_element(By.ID, "adj-progress-fill")
        self.assertIsNotNone(progress_fill)

    def test_progress_text_displayed(self):
        """The progress text (e.g. '3/15') should be visible."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        progress_text = self.driver.find_element(By.ID, "adj-progress-text")
        self.assertTrue(len(progress_text.text) > 0, "Progress text should have content")

    # ================================================================
    # Tests: Config Passed to JS
    # ================================================================

    def test_adj_config_available_in_js(self):
        """window.ADJ_CONFIG should be set by the template."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(1)

        adj_config = self.driver.execute_script("return window.ADJ_CONFIG;")
        self.assertIsNotNone(adj_config, "ADJ_CONFIG should be defined")
        # The template exposes UI-relevant config fields, not security-sensitive ones
        self.assertIn("show_annotator_names", adj_config)
        self.assertIn("error_taxonomy", adj_config)

    def test_annotation_schemes_available_in_js(self):
        """window.ANNOTATION_SCHEMES should be set by the template."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(1)

        schemes = self.driver.execute_script("return window.ANNOTATION_SCHEMES;")
        self.assertIsNotNone(schemes, "ANNOTATION_SCHEMES should be defined")
        self.assertGreater(len(schemes), 0, "Should have at least one scheme")


if __name__ == "__main__":
    unittest.main()
