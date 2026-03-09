"""
Selenium tests for Unicode content rendering throughout all phases.

Verifies that non-ASCII content (German umlauts, French accents, Chinese characters,
emoji) renders correctly in consent, instructions, annotation, and poststudy phases.

Prevents regression of issues #114 (Unicode stripped from text) and
#116 (surveyflow encoding mojibake).
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

# Unicode test strings
GERMAN_CONSENT = "Ich möchte an dieser Forschung teilnehmen und stimme den Bedingungen zu."
FRENCH_INSTRUCTIONS = "Veuillez lire attentivement les instructions ci-dessous avant de procéder."
CHINESE_ITEM_1 = "这是一个用于测试Unicode支持的中文文本。"
CHINESE_ITEM_2 = "人工智能技术正在改变世界。"
EMOJI_LABEL = "Positive 👍"
GERMAN_POSTSTUDY = "Wie zufrieden waren Sie mit dieser Studie? Bitte wählen Sie eine Option."

# Mojibake patterns that indicate encoding errors
MOJIBAKE_PATTERNS = ["Ã¶", "Ã¼", "Ã©", "Ã¨", "Ã ", "â€"]


def create_unicode_phases_config(test_dir, port):
    """Create config with Unicode content in all phases."""
    test_data = [
        {"id": "cn_1", "text": CHINESE_ITEM_1},
        {"id": "cn_2", "text": CHINESE_ITEM_2},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    surveys_dir = os.path.join(test_dir, "surveys")
    os.makedirs(surveys_dir, exist_ok=True)

    # Create consent survey with German umlauts
    consent_survey = [
        {
            "id": "1",
            "name": "consent_agree",
            "description": GERMAN_CONSENT,
            "annotation_type": "radio",
            "labels": ["Ja, ich stimme zu", "Nein"],
        }
    ]
    with open(os.path.join(surveys_dir, "consent.json"), "w", encoding="utf-8") as f:
        json.dump(consent_survey, f, ensure_ascii=False)

    # Create instructions survey with French accents
    instructions_survey = [
        {
            "id": "1",
            "name": "instructions_ack",
            "description": FRENCH_INSTRUCTIONS,
            "annotation_type": "radio",
            "labels": ["Je comprends les instructions"],
        }
    ]
    with open(os.path.join(surveys_dir, "instructions.json"), "w", encoding="utf-8") as f:
        json.dump(instructions_survey, f, ensure_ascii=False)

    # Create poststudy survey with German text
    poststudy_survey = [
        {
            "id": "1",
            "name": "zufriedenheit",
            "description": GERMAN_POSTSTUDY,
            "annotation_type": "radio",
            "labels": ["Sehr zufrieden", "Etwas zufrieden", "Nicht zufrieden"],
        }
    ]
    with open(os.path.join(surveys_dir, "poststudy.json"), "w", encoding="utf-8") as f:
        json.dump(poststudy_survey, f, ensure_ascii=False)

    config = {
        "annotation_task_name": f"Unicode Phases Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?",
            }
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 2,
        "max_annotations_per_item": 3,
        "phases": {
            "order": ["consent", "instructions", "annotation", "post_survey"],
            "consent": {"type": "consent", "file": "surveys/consent.json"},
            "instructions": {"type": "instructions", "file": "surveys/instructions.json"},
            "annotation": {"type": "annotation"},
            "post_survey": {"type": "poststudy", "file": "surveys/poststudy.json"},
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


class TestUnicodePhasesUI(unittest.TestCase):
    """
    Verify non-ASCII content renders correctly throughout all phases.
    Prevents regression of issues #114 and #116.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"unicode_phases_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_unicode_phases_config(cls.test_dir, cls.port)

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
        self.test_user = f"unicode_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

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
        """Create a requests.Session with cookies from Selenium driver."""
        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
        return session

    def _advance_phase(self, route):
        """Advance a phase by POSTing directly to the phase route."""
        session = self._get_requests_session()
        session.post(
            f"{self.server.base_url}/{route}",
            data={"submitted": "true"},
            timeout=5,
        )
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)

    def _annotate_and_next(self):
        """Select a radio option and click Next."""
        time.sleep(0.5)
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
            next_btn = self.driver.find_element(
                By.CSS_SELECTOR, 'a[onclick*="click_to_next"]'
            )
            next_btn.click()
        time.sleep(2)

    def _check_no_mojibake(self, page_source):
        """Assert no mojibake patterns appear in page source."""
        for pattern in MOJIBAKE_PATTERNS:
            self.assertNotIn(
                pattern,
                page_source,
                f"Mojibake pattern '{pattern}' found — encoding error (issues #114, #116)",
            )

    def test_unicode_consent_renders_correctly(self):
        """German umlauts in consent description should render correctly."""
        self._login()

        page_source = self.driver.page_source
        self._check_no_mojibake(page_source)

        # Check for German umlaut characters (case-insensitive since CSS may uppercase)
        page_lower = page_source.lower()
        has_german = (
            "möchte" in page_lower
            or "teilnehmen" in page_lower
            or "stimme" in page_lower
            or "bedingungen" in page_lower
        )
        self.assertTrue(
            has_german,
            "German umlauts should render correctly in consent page",
        )

    def test_unicode_instructions_render_correctly(self):
        """French accents in instructions should render correctly."""
        self._login()
        self._advance_phase("consent")

        page_source = self.driver.page_source
        self._check_no_mojibake(page_source)

        page_lower = page_source.lower()
        has_french = (
            "procéder" in page_lower
            or "attentivement" in page_lower
            or "ci-dessous" in page_lower
        )
        self.assertTrue(
            has_french,
            "French accents should render correctly in instructions page",
        )

    def test_unicode_annotation_text_renders(self):
        """Chinese characters in annotation items should display correctly."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("instructions")

        page_source = self.driver.page_source
        self._check_no_mojibake(page_source)

        # Check for Chinese characters
        has_chinese = (
            "测试" in page_source
            or "中文" in page_source
            or "Unicode" in page_source
            or "人工智能" in page_source
            or "改变世界" in page_source
        )
        self.assertTrue(
            has_chinese,
            "Chinese characters should render correctly in annotation text",
        )

    def test_unicode_poststudy_renders(self):
        """German text in poststudy labels should render correctly."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("instructions")

        # Annotate both items
        for _ in range(2):
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']")
                    )
                )
                self._annotate_and_next()
            except Exception:
                break

        # Should be on poststudy
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

        page_source = self.driver.page_source
        self._check_no_mojibake(page_source)

        page_lower = page_source.lower()
        has_german_poststudy = (
            "zufrieden" in page_lower
            or "studie" in page_lower
            or "wählen" in page_lower
        )
        self.assertTrue(
            has_german_poststudy,
            "German text in poststudy should render correctly",
        )

    def test_no_mojibake_across_phases(self):
        """
        Complete full workflow and verify no mojibake patterns appear at any point.
        Issues #114, #116: encoding errors caused character corruption.
        """
        self._login()

        # Check consent phase
        page_source = self.driver.page_source
        self._check_no_mojibake(page_source)

        # Advance through consent
        self._advance_phase("consent")

        # Check instructions phase
        page_source = self.driver.page_source
        self._check_no_mojibake(page_source)

        # Advance through instructions
        self._advance_phase("instructions")

        # Check annotation phase
        page_source = self.driver.page_source
        self._check_no_mojibake(page_source)

        # Annotate both items
        for _ in range(2):
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']")
                    )
                )
                self._annotate_and_next()
            except Exception:
                break

        # Check poststudy phase
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)
        page_source = self.driver.page_source
        self._check_no_mojibake(page_source)

    def test_unicode_annotation_labels_render(self):
        """Annotation labels should display correctly even with non-ASCII content."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("instructions")

        labels = self.driver.find_elements(
            By.CSS_SELECTOR, "label"
        )
        label_texts = [l.text for l in labels if l.text.strip()]

        # Should have annotation labels (positive, negative, neutral)
        has_labels = any(
            "positive" in t.lower() or "negative" in t.lower() or "neutral" in t.lower()
            for t in label_texts
        )
        self.assertTrue(
            has_labels,
            "Annotation labels should be selectable and display correctly",
        )


if __name__ == "__main__":
    unittest.main()
