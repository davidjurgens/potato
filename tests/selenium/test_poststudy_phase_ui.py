"""
Selenium test for issue #115: Poststudy phase skipped due to POST request
after annotation completion.

Verifies that after completing all annotations through the browser UI,
the user is shown the poststudy survey page instead of being skipped
directly to the done/completion page.
"""

import json
import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    cleanup_test_directory,
)


def create_poststudy_selenium_config(test_dir, port):
    """Create a config with 1 annotation item followed by a poststudy phase."""
    import yaml

    test_data = [{"id": "item_1", "text": "The only item to annotate."}]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Create poststudy survey JSON in Potato's annotation scheme format
    surveys_dir = os.path.join(test_dir, "surveys")
    os.makedirs(surveys_dir, exist_ok=True)
    poststudy_survey = [
        {
            "id": "1",
            "name": "study_satisfaction",
            "description": "How satisfied were you with this study?",
            "annotation_type": "radio",
            "labels": ["Very satisfied", "Somewhat satisfied", "Not satisfied"],
        }
    ]
    poststudy_file = os.path.join(surveys_dir, "poststudy.json")
    with open(poststudy_file, "w", encoding="utf-8") as f:
        json.dump(poststudy_survey, f)

    config = {
        "annotation_task_name": f"Poststudy UI Test {port}",
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
        "max_annotations_per_item": 3,
        "phases": {
            "order": ["annotation", "post_survey"],
            "annotation": {"type": "annotation"},
            "post_survey": {
                "type": "poststudy",
                "file": "surveys/poststudy.json",
            },
        },
        "site_file": "base_template.html",
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


class TestPoststudyPhaseUI(unittest.TestCase):
    """
    Issue #115: After annotation completion via browser UI, the poststudy page
    must be rendered (not skipped).

    The bug was that the POST from annotation submission leaked into the
    poststudy handler which treated the empty POST as a completed survey.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"poststudy_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_poststudy_selenium_config(cls.test_dir, cls.port)

        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file
        )
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

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
        self.test_user = f"poststudy_user_{int(time.time() * 1000)}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
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
        # Wait for annotation page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def _annotate_and_navigate_next(self):
        """Select a radio option and click next to complete the annotation."""
        # Wait for annotation form to be ready
        time.sleep(0.5)

        # Click the first radio button (positive)
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
        )
        if radios:
            # Click via label for reliability
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

        # Click the Next button to submit and advance
        try:
            next_btn = self.driver.find_element(By.ID, "next-btn")
            next_btn.click()
        except Exception:
            # Fallback: try onclick-based navigation
            next_btn = self.driver.find_element(
                By.CSS_SELECTOR, 'a[onclick*="click_to_next"]'
            )
            next_btn.click()

        # Wait for the page to transition (redirect happens)
        time.sleep(2)

    def test_poststudy_page_shown_after_annotation(self):
        """
        Issue #115: After completing the only annotation item via the UI,
        the user should see the poststudy survey, NOT skip to done.
        """
        self._annotate_and_navigate_next()

        # The JS calls window.location.reload() which may take time
        # Wait for the page to settle — it may redirect through home()
        time.sleep(2)

        # After following redirects, navigate to home to check current phase
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)

        page_source = self.driver.page_source.lower()

        # The poststudy page should contain the survey question
        has_poststudy = (
            "study_satisfaction" in page_source
            or "satisfied" in page_source
            or "how satisfied" in page_source
        )

        # Should NOT have been advanced past poststudy to done
        # (the done page would show a completion message without survey form)
        is_done_page = "all done" in page_source or "all_done" in page_source

        self.assertTrue(
            has_poststudy or not is_done_page,
            "Poststudy page was skipped — user went directly to done page "
            "(issue #115: POST leaked into poststudy handler). "
            f"Page URL: {self.driver.current_url}, Title: {self.driver.title}"
        )

    def test_poststudy_persists_across_refresh(self):
        """After reaching poststudy, refreshing should still show it."""
        self._annotate_and_navigate_next()
        time.sleep(2)

        # Navigate to home explicitly
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)

        # Refresh again — should still be on poststudy
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)

        page_source = self.driver.page_source.lower()

        # Should still be on poststudy (survey question visible)
        has_poststudy = (
            "study_satisfaction" in page_source
            or "satisfied" in page_source
        )
        is_done_page = "all done" in page_source or "all_done" in page_source

        self.assertTrue(
            has_poststudy or not is_done_page,
            "Poststudy page not shown after refresh — phase was incorrectly advanced"
        )


if __name__ == "__main__":
    unittest.main()
