"""
Selenium test for issue #116: Surveyflow text rendered with incorrect encoding.

Verifies that consent/instructions phase pages with non-ASCII content
(German umlauts, accented characters) render correctly in the browser,
not as mojibake (e.g., "möchte" should not appear as "mÃ¶chte").
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

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    cleanup_test_directory,
)


def create_utf8_consent_config(test_dir, port):
    """Create a config with a consent phase containing German/Unicode text."""
    test_data = [{"id": "item_1", "text": "Test item."}]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Create consent survey JSON with German text
    surveys_dir = os.path.join(test_dir, "surveys")
    os.makedirs(surveys_dir, exist_ok=True)

    # Consent survey in Potato's annotation scheme format
    consent_survey = [
        {
            "id": "1",
            "name": "consent_agreement",
            "description": "Ich möchte an dieser Forschung teilnehmen und mit der Studie fortfahren.",
            "annotation_type": "radio",
            "labels": [
                "Ja, natürlich möchte ich teilnehmen",
                "Nein, ich möchte nicht fortfahren",
            ],
            "label_requirement": {
                "required_label": ["Ja, natürlich möchte ich teilnehmen"]
            },
        },
        {
            "id": "2",
            "name": "bridge_consent",
            "description": "Stimmen Sie zu, über die Brücke zu gehen?",
            "annotation_type": "radio",
            "labels": ["Ja", "Nein"],
        },
    ]

    consent_file = os.path.join(surveys_dir, "consent.json")
    with open(consent_file, "w", encoding="utf-8") as f:
        json.dump(consent_survey, f, ensure_ascii=False)

    config = {
        "annotation_task_name": f"UTF-8 Consent Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "rating",
                "annotation_type": "radio",
                "labels": ["good", "bad"],
                "description": "Rate this",
            }
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 1,
        "max_annotations_per_item": 3,
        "phases": {
            "order": ["consent", "annotation"],
            "consent": {"type": "consent", "file": "surveys/consent.json"},
            "annotation": {"type": "annotation"},
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
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)

    return config_file


class TestSurveyflowEncodingUI(unittest.TestCase):
    """
    Issue #116: Surveyflow content with non-ASCII characters must render
    correctly (no mojibake like "mÃ¶chte" for "möchte").

    The fix adds encoding='utf-8' to all file open() calls that load
    survey JSON files.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"surveyflow_encoding_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_utf8_consent_config(cls.test_dir, cls.port)

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
        self.test_user = f"encoding_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        """Login the test user — should land on consent phase page."""
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
        # Wait for the consent phase page to load
        # Don't wait for annotation-specific elements since we expect the consent page
        time.sleep(2)
        # Navigate to home to ensure we're on the current phase page
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)

    def test_german_umlauts_in_consent_page(self):
        """
        Issue #116: German umlauts in consent survey should not be mojibake.

        "möchte" must NOT render as "mÃ¶chte".
        "Brücke" must NOT render as "BrÃ¼cke".
        """
        self._login()

        page_text = self.driver.find_element(By.TAG_NAME, "body").text
        # Descriptions may be CSS-uppercased (text-transform), so compare lowercase
        page_lower = page_text.lower()

        # Verify correct characters are present (case-insensitive for CSS transforms)
        self.assertIn("möchte", page_lower,
                       "German umlaut ö was corrupted or missing in consent page")
        self.assertIn("brücke", page_lower,
                       "German umlaut ü was corrupted or missing in consent page")

        # Verify mojibake is NOT present
        self.assertNotIn("mã¶chte", page_lower,
                          "Mojibake detected: 'mÃ¶chte' instead of 'möchte'")
        self.assertNotIn("brã¼cke", page_lower,
                          "Mojibake detected: 'BrÃ¼cke' instead of 'Brücke'")

    def test_consent_description_rendered_correctly(self):
        """The consent description with ü should render correctly."""
        self._login()

        page_text = self.driver.find_element(By.TAG_NAME, "body").text
        # Descriptions may be CSS-uppercased (text-transform), so compare lowercase
        page_lower = page_text.lower()

        self.assertIn("brücke", page_lower,
                       "Consent description with ü was corrupted")
        self.assertNotIn("brã¼cke", page_lower,
                          "Mojibake detected in consent description")

    def test_consent_options_rendered_correctly(self):
        """Radio option labels with umlauts should display correctly."""
        self._login()

        page_text = self.driver.find_element(By.TAG_NAME, "body").text

        self.assertIn("natürlich", page_text,
                       "Option label with ü was corrupted")
        self.assertNotIn("natÃ¼rlich", page_text,
                          "Mojibake detected in option label")


if __name__ == "__main__":
    unittest.main()
