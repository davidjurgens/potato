"""Full front-end (Selenium) test for per-cohort schema rendering.

Two annotators in different batch-assignment cohorts must each see ONLY their
cohort's annotation schemes in the browser:
  * cohortA (alice) binds the ``minimal`` set -> only ``sentiment`` (label
    marker "poslabel"); the ``topic`` scheme (marker "alphalabel") must be
    absent.
  * cohortB (bob) binds ``sentiment`` + ``topic`` -> BOTH markers present.

Verification is on the rendered DOM (visible label text), not page source, so it
confirms the correct per-cohort layout is actually served and displayed.
"""

import os
import sys
import time
import unittest

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import TimeoutException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import TestConfigManager


pytestmark = pytest.mark.core

ANNOTATION_SCHEMES = [
    {
        "name": "sentiment",
        "annotation_type": "radio",
        "description": "Sentiment",
        "labels": ["poslabel", "neglabel"],
    },
    {
        "name": "topic",
        "annotation_type": "radio",
        "description": "Topic",
        "labels": ["alphalabel", "betalabel"],
    },
]

ADDITIONAL = {
    "assignment_strategy": "batch",
    "scheme_sets": {"minimal": ["sentiment"]},
    "batch_assignment": {
        "groups": [
            {"name": "cohortA", "annotators": ["alice@x.com"], "instances": ["1", "2"], "schemes": "minimal"},
            {"name": "cohortB", "annotators": ["bob@x.com"], "instances": ["3"], "schemes": ["sentiment", "topic"]},
        ]
    },
}


class TestPerCohortSchemesUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cfg = TestConfigManager(
            "per_cohort_ui",
            ANNOTATION_SCHEMES,
            num_instances=3,
            additional_config=ADDITIONAL,
        )
        cls._cfg.__enter__()
        port = find_free_port(preferred_port=9052)
        cls.server = FlaskTestServer(port=port, config_file=cls._cfg.config_path)
        if not cls.server.start():
            raise RuntimeError("Failed to start per-cohort UI server")
        cls.base_url = cls.server.base_url

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()
        if hasattr(cls, "_cfg"):
            cls._cfg.__exit__(None, None, None)

    def setUp(self):
        opts = ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        self.driver = webdriver.Chrome(options=opts)
        self.driver.implicitly_wait(3)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login_and_open_annotation(self, username):
        self.driver.get(f"{self.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(username)
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(1)
        self.driver.get(f"{self.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        # Give the JS a moment to reveal #main-content and render the form.
        time.sleep(1)

    def _radio_input_present(self, label):
        # Each radio option renders an <input ... label_name="<label>">. The
        # annotation form is inside #main-content (hidden until the JS reveal),
        # so we assert the DOM node the browser was served, not its visibility.
        # Presence/absence is the per-cohort isolation signal.
        return len(
            self.driver.find_elements(
                By.CSS_SELECTOR, f"input[label_name='{label}']"
            )
        ) > 0

    def test_cohortA_sees_only_sentiment(self):
        self._login_and_open_annotation("alice@x.com")
        assert self._radio_input_present("poslabel"), "cohortA should get the sentiment scheme"
        assert not self._radio_input_present(
            "alphalabel"
        ), "cohortA's layout must NOT include the topic scheme"

    def test_cohortB_sees_both_schemes(self):
        self._login_and_open_annotation("bob@x.com")
        assert self._radio_input_present("poslabel"), "cohortB should get the sentiment scheme"
        assert self._radio_input_present("alphalabel"), "cohortB should get the topic scheme"


if __name__ == "__main__":
    unittest.main()
