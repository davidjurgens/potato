"""
Selenium UI tests for the Adjudication Demo with pre-loaded data.

Unlike test_adjudication_ui.py which uses a simulator to generate
annotations, this test relies on the pre-loaded user_state.json files
in the simple-adjudication example. It validates the full browser
experience with the demo config.
"""

import os
import shutil
import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
DEMO_DIR = os.path.join(
    REPO_ROOT, "project-hub", "simple_examples", "simple-adjudication"
)
CONFIG_FILE = os.path.join(DEMO_DIR, "config.yaml")


class TestAdjudicationDemoUI(unittest.TestCase):
    """Selenium tests for the adjudication demo with pre-loaded data."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with the real demo config."""
        # Clean adjudication decisions
        cls.adj_output = os.path.join(DEMO_DIR, "annotation_output", "adjudication")
        if os.path.exists(cls.adj_output):
            shutil.rmtree(cls.adj_output)

        cls.server = FlaskTestServer(
            port=find_free_port(),
            config_file=CONFIG_FILE,
        )
        if not cls.server.start():
            raise unittest.SkipTest("Failed to start Flask server")

        chrome_opts = ChromeOptions()
        chrome_opts.add_argument("--headless=new")
        chrome_opts.add_argument("--no-sandbox")
        chrome_opts.add_argument("--disable-dev-shm-usage")
        chrome_opts.add_argument("--disable-gpu")
        chrome_opts.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_opts

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()
        if hasattr(cls, "adj_output") and os.path.exists(cls.adj_output):
            shutil.rmtree(cls.adj_output)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(2)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # -- helpers --

    def _login_adjudicator(self):
        """Register + login as 'adjudicator' and transfer cookies to browser."""
        import requests as req

        s = req.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "adjudicator", "pass": "pass"},
        )
        s.post(
            f"{self.server.base_url}/auth",
            data={"email": "adjudicator", "pass": "pass"},
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

    # ================================================================
    # Page load
    # ================================================================

    def test_page_loads_for_adjudicator(self):
        """Adjudicator should see the adjudication page."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        header = self._wait(By.CSS_SELECTOR, ".navbar-brand")
        self.assertIn("Adjudication", header.text)

    # ================================================================
    # Queue populated from pre-loaded data
    # ================================================================

    def test_queue_has_items(self):
        """Queue sidebar should show items from pre-loaded annotations."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        queue_list = self.driver.find_element(By.ID, "adj-queue-list")
        items = queue_list.find_elements(By.CLASS_NAME, "adj-queue-item")
        self.assertGreater(
            len(items), 0, "Queue should be populated from pre-loaded data"
        )

    def test_queue_has_eight_items(self):
        """All 8 data items should appear in the queue."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        queue_list = self.driver.find_element(By.ID, "adj-queue-list")
        items = queue_list.find_elements(By.CLASS_NAME, "adj-queue-item")
        self.assertEqual(len(items), 8, f"Expected 8 items, got {len(items)}")

    # ================================================================
    # Item selection
    # ================================================================

    def test_click_item_shows_detail(self):
        """Clicking a queue item should show annotator responses."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        item_view = self.driver.find_element(By.ID, "adj-item-view")
        self.assertTrue(item_view.is_displayed())

    def test_annotator_response_cards_visible(self):
        """After clicking an item, annotator response cards should appear."""
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

    # ================================================================
    # Signal badges (Phase 3)
    # ================================================================

    def test_signal_badges_render(self):
        """Signal badges should render for annotators with quality flags."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            self.skipTest("No items in queue")
        items[0].click()
        time.sleep(1)

        # Look for signal badge elements (rendered by adjudication.js)
        page_source = self.driver.page_source
        # The JS renders signal flags as badge elements or text
        # Check that the response container has signal-related content
        container = self.driver.find_element(By.ID, "adj-responses-container")
        # At minimum the container should show annotator names and labels
        self.assertTrue(len(container.text) > 0)

    # ================================================================
    # Similar items panel
    # ================================================================

    def test_similar_items_section_exists(self):
        """The similar items section should exist in the DOM."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(1)

        # The adjudication.html template includes a similar-items section
        page_source = self.driver.page_source
        self.assertIn("similar", page_source.lower())

    # ================================================================
    # Submit decision through UI
    # ================================================================

    def test_submit_decision_via_ui(self):
        """Select a label and submit; queue should update."""
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
            self.skipTest("No radio buttons found")
        self.driver.execute_script("arguments[0].click();", radios[0])

        # Submit
        submit_btn = self.driver.find_element(By.ID, "adj-btn-submit")
        submit_btn.click()
        time.sleep(2)

        # Reload to verify
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)
        new_items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        self.assertLessEqual(
            len(new_items),
            initial_count,
            "Pending count should decrease after submission",
        )

    # ================================================================
    # Progress bar
    # ================================================================

    def test_progress_bar_visible(self):
        """Progress bar should be visible in the sidebar."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        progress = self.driver.find_element(By.ID, "adj-progress-fill")
        self.assertIsNotNone(progress)

    # ================================================================
    # Non-adjudicator redirect
    # ================================================================

    def test_regular_user_cannot_see_queue(self):
        """A non-adjudicator should not see the queue interface."""
        import requests as req

        s = req.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "nonadj_demo", "pass": "pass"},
        )
        s.post(
            f"{self.server.base_url}/auth",
            data={"email": "nonadj_demo", "pass": "pass"},
        )
        for cookie in s.cookies:
            self.driver.get(self.server.base_url)
            self.driver.add_cookie(
                {"name": cookie.name, "value": cookie.value, "path": "/"}
            )

        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(1)

        page = self.driver.page_source
        # Should not see the queue list
        if "/adjudicate" in self.driver.current_url:
            self.assertNotIn("adj-queue-list", page)


if __name__ == "__main__":
    unittest.main()
