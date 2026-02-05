"""
Selenium UI tests for the MACE Competence Estimation Demo.

Uses the pre-loaded user_state.json files from the simple-mace-demo
example. Tests the annotation UI workflow and verifies MACE API
results are accessible and correct.

Tests:
- Server starts and annotation page loads with MACE enabled
- User can login and see the annotation interface
- Annotation submission works and stores data
- MACE admin API returns competence scores after trigger
- MACE predictions accessible via JavaScript fetch in browser
- Competence ordering: spammer < reliable annotators
"""

import json
import os
import shutil
import time
import unittest

import requests as req
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
    REPO_ROOT, "project-hub", "simple_examples", "simple-mace-demo"
)
CONFIG_FILE = os.path.join(DEMO_DIR, "config.yaml")
ADMIN_KEY = "demo-mace-key"


class TestMACEDemoUI(unittest.TestCase):
    """Selenium tests for the MACE demo with pre-loaded data."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with the real MACE demo config."""
        # Clean cached MACE results
        cls.mace_output = os.path.join(DEMO_DIR, "annotation_output", "mace")
        if os.path.exists(cls.mace_output):
            shutil.rmtree(cls.mace_output)

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
        if hasattr(cls, "mace_output") and os.path.exists(cls.mace_output):
            shutil.rmtree(cls.mace_output)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(2)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # -- helpers --

    def _login(self, username="demo_user"):
        """Register + login a user and transfer cookies to browser."""
        s = req.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": username, "pass": "pass"},
        )
        s.post(
            f"{self.server.base_url}/auth",
            data={"email": username, "pass": "pass"},
        )
        # Transfer session cookies to browser
        self.driver.get(self.server.base_url)
        for cookie in s.cookies:
            self.driver.add_cookie(
                {"name": cookie.name, "value": cookie.value, "path": "/"}
            )
        return s

    def _wait(self, by, value, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def _trigger_mace(self):
        """Trigger MACE via admin API."""
        resp = req.post(
            f"{self.server.base_url}/admin/api/mace/trigger",
            headers={"X-API-Key": ADMIN_KEY},
            timeout=10,
        )
        return resp.json()

    def _get_overview(self):
        """Get MACE overview via admin API."""
        resp = req.get(
            f"{self.server.base_url}/admin/api/mace/overview",
            headers={"X-API-Key": ADMIN_KEY},
            timeout=10,
        )
        return resp.json()

    def _get_predictions(self, schema="sentiment"):
        """Get MACE predictions via admin API."""
        resp = req.get(
            f"{self.server.base_url}/admin/api/mace/predictions",
            headers={"X-API-Key": ADMIN_KEY},
            params={"schema": schema},
            timeout=10,
        )
        return resp.json()

    # ================================================================
    # Page load and server health
    # ================================================================

    def test_server_health_check(self):
        """Server should respond to health check."""
        resp = req.get(f"{self.server.base_url}/", timeout=10)
        self.assertEqual(resp.status_code, 200)

    def test_login_page_loads(self):
        """Login page should load correctly."""
        self.driver.get(self.server.base_url)
        login_content = self._wait(By.ID, "login-content")
        self.assertTrue(login_content.is_displayed())

    def test_annotation_page_loads_after_login(self):
        """After login, annotation page should load with content."""
        self._login("page_load_user")
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        # Wait for main content to appear
        page_source = self.driver.page_source
        # The annotation page should have the task content
        self.assertIn("sentiment", page_source.lower())

    # ================================================================
    # Annotation submission through UI
    # ================================================================

    def test_radio_buttons_visible(self):
        """Radio buttons for sentiment annotation should be visible."""
        self._login("radio_user")
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        # Look for radio inputs for sentiment schema
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name='sentiment']"
        )
        self.assertGreater(
            len(radios), 0, "Should have radio buttons for sentiment schema"
        )

    def test_annotation_submission_via_api(self):
        """Submitting an annotation via the API should succeed."""
        s = req.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "api_annotator", "pass": "pass"},
        )
        s.post(
            f"{self.server.base_url}/auth",
            data={"email": "api_annotator", "pass": "pass"},
        )

        # Submit an annotation using the backend label format
        resp = s.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "review_01",
                "type": "label",
                "schema": "sentiment",
                "state": [{"name": "positive", "value": "positive"}],
            },
            timeout=10,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")

    # ================================================================
    # MACE API verification from browser context
    # ================================================================

    def test_mace_trigger_via_api(self):
        """MACE trigger should process schemas."""
        data = self._trigger_mace()
        self.assertEqual(data["status"], "success")
        self.assertGreaterEqual(data["schemas_processed"], 1)
        self.assertIn("sentiment", data["schemas"])

    def test_mace_overview_has_competence_scores(self):
        """After trigger, overview should have competence scores."""
        self._trigger_mace()
        data = self._get_overview()

        self.assertTrue(data["has_results"])
        self.assertIn("annotator_competence", data)
        competence = data["annotator_competence"]

        # All 5 pre-loaded annotators should have scores
        expected = {"reliable_1", "reliable_2", "moderate", "spammer", "biased"}
        self.assertTrue(
            expected.issubset(set(competence.keys())),
            f"Expected {expected} in competence keys, got {set(competence.keys())}",
        )

    def test_mace_spammer_detected(self):
        """MACE should detect the spammer as having lowest competence."""
        self._trigger_mace()
        data = self._get_overview()
        competence = data["annotator_competence"]

        spammer_score = competence["spammer"]["average"]
        reliable_1_score = competence["reliable_1"]["average"]
        reliable_2_score = competence["reliable_2"]["average"]

        self.assertLess(
            spammer_score, reliable_1_score,
            f"Spammer ({spammer_score:.3f}) should be lower than "
            f"reliable_1 ({reliable_1_score:.3f})",
        )
        self.assertLess(
            spammer_score, reliable_2_score,
            f"Spammer ({spammer_score:.3f}) should be lower than "
            f"reliable_2 ({reliable_2_score:.3f})",
        )

    def test_mace_predictions_correct(self):
        """MACE predictions should be correct for clearly labeled items."""
        self._trigger_mace()
        data = self._get_predictions()

        preds = data["predicted_labels"]
        # Clearly positive items
        self.assertEqual(preds["review_01"], "positive")
        self.assertEqual(preds["review_03"], "positive")
        self.assertEqual(preds["review_09"], "positive")
        # Clearly negative items
        self.assertEqual(preds["review_05"], "negative")
        self.assertEqual(preds["review_10"], "negative")

    def test_mace_api_from_browser_fetch(self):
        """Verify MACE API is accessible via JavaScript fetch from browser."""
        self._trigger_mace()

        self._login("fetch_user")
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        # Use JavaScript fetch to call the MACE overview API
        result = self.driver.execute_script(f"""
            var response = await fetch(
                '{self.server.base_url}/admin/api/mace/overview',
                {{headers: {{'X-API-Key': '{ADMIN_KEY}'}}}}
            );
            var data = await response.json();
            return JSON.stringify(data);
        """)

        data = json.loads(result)
        self.assertTrue(data["enabled"])
        self.assertTrue(data["has_results"])
        self.assertIn("annotator_competence", data)

    def test_mace_predictions_from_browser_fetch(self):
        """Verify MACE predictions API is accessible via JavaScript fetch."""
        self._trigger_mace()

        self._login("pred_fetch_user")
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        result = self.driver.execute_script(f"""
            var response = await fetch(
                '{self.server.base_url}/admin/api/mace/predictions?schema=sentiment',
                {{headers: {{'X-API-Key': '{ADMIN_KEY}'}}}}
            );
            var data = await response.json();
            return JSON.stringify(data);
        """)

        data = json.loads(result)
        self.assertIn("predicted_labels", data)
        self.assertIn("label_entropy", data)
        self.assertEqual(len(data["predicted_labels"]), 10)


if __name__ == "__main__":
    unittest.main()
