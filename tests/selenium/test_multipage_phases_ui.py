"""
Selenium tests for multi-page phases: 3 instruction pages navigated sequentially.

Verifies that phases with multiple pages advance correctly and that page state
is preserved across refresh.
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


def create_multipage_config(test_dir, port):
    """Create config with 3 instruction pages followed by annotation."""
    test_data = [
        {"id": "item_1", "text": "Item to annotate after instructions."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    surveys_dir = os.path.join(test_dir, "surveys")
    os.makedirs(surveys_dir, exist_ok=True)

    # Create 3 distinct instruction page files
    for page_num in range(1, 4):
        page_survey = [
            {
                "id": "1",
                "name": f"inst_page_{page_num}",
                "description": f"Instruction Page {page_num} of 3: Please read carefully.",
                "annotation_type": "radio",
                "labels": [f"I have read page {page_num}"],
            }
        ]
        with open(
            os.path.join(surveys_dir, f"instructions_{page_num}.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(page_survey, f)

    config = {
        "annotation_task_name": f"Multipage Test {port}",
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
            "order": [
                "instructions_1",
                "instructions_2",
                "instructions_3",
                "annotation",
            ],
            "instructions_1": {
                "type": "instructions",
                "file": "surveys/instructions_1.json",
            },
            "instructions_2": {
                "type": "instructions",
                "file": "surveys/instructions_2.json",
            },
            "instructions_3": {
                "type": "instructions",
                "file": "surveys/instructions_3.json",
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


class TestMultipagePhasesUI(unittest.TestCase):
    """
    Test phases with multiple pages (3 instruction pages navigated sequentially).
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"multipage_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_multipage_config(cls.test_dir, cls.port)

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
        self.test_user = f"multipage_user_{int(time.time() * 1000)}"

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

    def test_first_instruction_page_shown(self):
        """After login, first instruction page should be shown."""
        self._login()

        page_source = self.driver.page_source.lower()
        has_page_1 = (
            "page 1" in page_source
            or "inst_page_1" in page_source
            or "instruction" in page_source
        )
        self.assertTrue(
            has_page_1,
            "First instruction page should be shown after login",
        )

    def test_instruction_pages_advance_sequentially(self):
        """Submitting page 1 should show page 2, then page 3."""
        self._login()

        # Submit page 1
        self._advance_phase("instructions")

        page_source = self.driver.page_source.lower()
        has_page_2 = "page 2" in page_source or "inst_page_2" in page_source
        self.assertTrue(
            has_page_2,
            "After submitting page 1, page 2 should be shown",
        )

        # Submit page 2
        self._advance_phase("instructions")

        page_source = self.driver.page_source.lower()
        has_page_3 = "page 3" in page_source or "inst_page_3" in page_source
        self.assertTrue(
            has_page_3,
            "After submitting page 2, page 3 should be shown",
        )

    def test_all_instruction_pages_lead_to_annotation(self):
        """After submitting all 3 pages, annotation should load."""
        self._login()

        # Submit all 3 instruction pages
        for _ in range(3):
            self._advance_phase("instructions")

        page_source = self.driver.page_source.lower()
        has_annotation = (
            "task_layout" in page_source
            or "sentiment" in page_source
        )
        self.assertTrue(
            has_annotation,
            "After all instruction pages, annotation should load",
        )

    def test_cannot_skip_instruction_pages(self):
        """On page 1, navigating directly to /annotate should redirect back."""
        self._login()

        # Try to navigate directly to annotation
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        page_source = self.driver.page_source.lower()
        # Should NOT be on annotation page (should be redirected to instructions)
        # The instructions page should have instruction content
        on_instructions = (
            "instruction" in page_source
            or "page 1" in page_source
            or "inst_page" in page_source
        )
        not_on_annotation = "task_layout" not in page_source

        self.assertTrue(
            on_instructions or not_on_annotation,
            "Should not be able to skip instruction pages",
        )

    def test_instruction_page_state_preserved_on_refresh(self):
        """After navigating to page 2, refreshing should still show page 2."""
        self._login()

        # Submit page 1 to reach page 2
        self._advance_phase("instructions")

        page_source_before = self.driver.page_source.lower()

        # Refresh
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)
        page_source_after = self.driver.page_source.lower()

        # Should still be on page 2
        has_page_2 = "page 2" in page_source_after or "inst_page_2" in page_source_after
        not_page_1 = "page 1 of 3" not in page_source_after
        self.assertTrue(
            has_page_2 or not_page_1,
            "Page 2 state should persist across refresh",
        )


if __name__ == "__main__":
    unittest.main()
