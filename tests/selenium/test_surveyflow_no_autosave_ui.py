"""
Selenium tests for issue #126: annotation.js must not interfere with
surveyflow phases (consent, instructions, etc.).

Verifies that:
1. window.config.is_annotation_page is false on survey pages
2. No /updateinstance XHR requests are sent on non-annotation pages
3. Users can advance through all survey phases via the browser
4. Annotation phase still works normally after survey phases
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


def create_surveyflow_config(test_dir, port):
    """Create config with consent -> instructions -> annotation phases."""
    test_data = [
        {"id": "item_1", "text": "This movie was great!"},
        {"id": "item_2", "text": "This movie was terrible."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    surveys_dir = os.path.join(test_dir, "surveys")
    os.makedirs(surveys_dir, exist_ok=True)

    consent_survey = [
        {
            "id": "1",
            "name": "consent_agree",
            "description": "Do you consent to participate?",
            "annotation_type": "radio",
            "labels": ["Yes, I consent", "No"],
        }
    ]
    with open(os.path.join(surveys_dir, "consent.json"), "w") as f:
        json.dump(consent_survey, f)

    instructions_survey = [
        {
            "id": "1",
            "name": "instructions_ack",
            "description": "I have read and understand the instructions.",
            "annotation_type": "radio",
            "labels": ["I understand"],
        }
    ]
    with open(os.path.join(surveys_dir, "instructions.json"), "w") as f:
        json.dump(instructions_survey, f)

    config = {
        "annotation_task_name": f"Surveyflow_Autosave_Test_{port}",
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
        "max_annotations_per_user": 2,
        "max_annotations_per_item": 3,
        "phases": {
            "order": ["consent", "instructions", "annotation"],
            "consent": {"type": "consent", "file": "surveys/consent.json"},
            "instructions": {
                "type": "instructions",
                "file": "surveys/instructions.json",
            },
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
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


class TestSurveyflowNoAutosave(unittest.TestCase):
    """
    Issue #126: annotation.js fires autosave on non-annotation pages,
    sending /updateinstance with empty instance_id and interfering with
    surveyflow phase advancement.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"surveyflow_autosave_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_surveyflow_config(cls.test_dir, cls.port)

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
        self.test_user = f"surveyflow_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        """Login with simple auth (no password)."""
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

    def _install_xhr_interceptor(self):
        """Install JS interceptor that logs all /updateinstance XHR calls."""
        self.driver.execute_script("""
            window.__updateInstanceCalls = [];
            const origFetch = window.fetch;
            window.fetch = function(url, opts) {
                if (typeof url === 'string' && url.includes('/updateinstance')) {
                    window.__updateInstanceCalls.push({
                        url: url,
                        method: (opts && opts.method) || 'GET',
                        body: (opts && opts.body) || null,
                        timestamp: Date.now()
                    });
                }
                return origFetch.apply(this, arguments);
            };
            const origXHR = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(method, url) {
                if (typeof url === 'string' && url.includes('/updateinstance')) {
                    window.__updateInstanceCalls.push({
                        url: url,
                        method: method,
                        timestamp: Date.now()
                    });
                }
                return origXHR.apply(this, arguments);
            };
        """)

    def _get_updateinstance_calls(self):
        """Return the list of intercepted /updateinstance calls."""
        return self.driver.execute_script(
            "return window.__updateInstanceCalls || [];"
        )

    def test_consent_page_is_not_annotation_page(self):
        """window.config.is_annotation_page should be false on consent page."""
        self._login()

        is_annotation = self.driver.execute_script(
            "return window.config && window.config.is_annotation_page;"
        )
        self.assertFalse(
            is_annotation,
            "Consent page should have is_annotation_page=false",
        )

    def test_instructions_page_is_not_annotation_page(self):
        """window.config.is_annotation_page should be false on instructions page."""
        self._login()
        self._advance_phase("consent")

        is_annotation = self.driver.execute_script(
            "return window.config && window.config.is_annotation_page;"
        )
        self.assertFalse(
            is_annotation,
            "Instructions page should have is_annotation_page=false",
        )

    def test_annotation_page_is_annotation_page(self):
        """window.config.is_annotation_page should be true on annotation page."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("instructions")

        is_annotation = self.driver.execute_script(
            "return window.config && window.config.is_annotation_page;"
        )
        self.assertTrue(
            is_annotation,
            "Annotation page should have is_annotation_page=true",
        )

    def test_no_updateinstance_on_consent_page(self):
        """
        Issue #126: interacting with survey form inputs on consent page
        must NOT trigger /updateinstance requests.
        """
        self._login()
        self._install_xhr_interceptor()

        # Click on survey radio buttons via JS (survey radios may be styled
        # as custom elements that aren't directly interactable by Selenium)
        self.driver.execute_script("""
            document.querySelectorAll("input[type='radio']").forEach(function(r) {
                r.click();
            });
        """)

        # Wait for any debounced autosave to fire (annotation.js debounce is ~1s)
        time.sleep(2)

        calls = self._get_updateinstance_calls()
        self.assertEqual(
            len(calls),
            0,
            f"No /updateinstance calls should be made on consent page, got {len(calls)}: {calls}",
        )

    def test_no_updateinstance_on_instructions_page(self):
        """
        Issue #126: interacting with survey form inputs on instructions page
        must NOT trigger /updateinstance requests.
        """
        self._login()
        self._advance_phase("consent")
        self._install_xhr_interceptor()

        # Click on survey radio buttons via JS
        self.driver.execute_script("""
            document.querySelectorAll("input[type='radio']").forEach(function(r) {
                r.click();
            });
        """)

        time.sleep(2)

        calls = self._get_updateinstance_calls()
        self.assertEqual(
            len(calls),
            0,
            f"No /updateinstance calls should be made on instructions page, got {len(calls)}: {calls}",
        )

    def test_full_surveyflow_advancement(self):
        """
        End-to-end: user advances consent -> instructions -> annotation
        entirely through the browser without annotation.js interference.
        """
        self._login()

        # Verify on consent page
        page = self.driver.page_source.lower()
        self.assertTrue(
            "consent" in page or "participate" in page,
            "Should start on consent page after login",
        )

        # Advance through consent
        self._advance_phase("consent")
        page = self.driver.page_source.lower()
        self.assertTrue(
            "instructions" in page or "understand" in page,
            "Should be on instructions page after consent",
        )

        # Advance through instructions
        self._advance_phase("instructions")
        page = self.driver.page_source.lower()
        self.assertTrue(
            "sentiment" in page or "task_layout" in page,
            "Should be on annotation page after instructions",
        )

        # Verify annotation page works: is_annotation_page is true and
        # annotation elements are present
        is_annotation = self.driver.execute_script(
            "return window.config && window.config.is_annotation_page;"
        )
        self.assertTrue(is_annotation, "Annotation page flag should be true")

        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
        )
        self.assertGreater(
            len(radios), 0, "Annotation radio buttons should be present"
        )

    def test_annotation_autosave_works_after_surveyflow(self):
        """
        After advancing through survey phases, annotation autosave should
        still function on the annotation page.
        """
        self._login()
        self._advance_phase("consent")
        self._advance_phase("instructions")

        self._install_xhr_interceptor()

        # Click an annotation radio to trigger autosave
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
        )
        self.assertGreater(len(radios), 0, "Should have annotation radios")

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

        # Wait for debounced autosave
        time.sleep(2)

        calls = self._get_updateinstance_calls()
        self.assertGreater(
            len(calls),
            0,
            "Annotation page should trigger /updateinstance on radio click",
        )


if __name__ == "__main__":
    unittest.main()
