"""Full front-end (Selenium) tests for RBAC-gated admin access.

Verifies in a real browser that:
  * a user with the RBAC ``admin`` role reaches the ``/admin`` dashboard through
    the normal login flow WITHOUT ever entering the shared admin key,
  * a user with only the ``annotator`` role is blocked (shown the key-login form),
  * the shared admin key still works (backward compatibility).

The server runs with debug OFF so the gate is actually exercised (debug would
open the admin-dashboard tier to everyone).
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

ADMIN_KEY = "ui-admin-key-42"

ANNOTATION_SCHEMES = [
    {
        "name": "sentiment",
        "annotation_type": "radio",
        "description": "Sentiment",
        "labels": ["pos", "neg"],
    }
]

RBAC_ADD = {
    "rbac": {
        "enabled": True,
        "user_role_assignments": {
            "carol@x.com": "admin",
            "dan@x.com": "annotator",
        },
    }
}


class TestRBACDashboardUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cfg = TestConfigManager(
            "rbac_ui",
            ANNOTATION_SCHEMES,
            num_instances=3,
            admin_api_key=ADMIN_KEY,
            additional_config=RBAC_ADD,
        )
        cls._cfg.__enter__()
        port = find_free_port(preferred_port=9051)
        cls.server = FlaskTestServer(port=port, config_file=cls._cfg.config_path)
        if not cls.server.start():
            raise RuntimeError("Failed to start RBAC UI server")
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

    # -- helpers -------------------------------------------------------

    def _login_simple(self, username):
        self.driver.get(f"{self.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(username)
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(1)

    def _dashboard_visible(self, timeout=10):
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CLASS_NAME, "admin-tabs"))
            )
            return True
        except TimeoutException:
            return False

    def _key_form_visible(self, timeout=10):
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.ID, "apiKey"))
            )
            return True
        except TimeoutException:
            return False

    # -- tests ---------------------------------------------------------

    def test_role_admin_reaches_dashboard_without_key(self):
        self._login_simple("carol@x.com")
        self.driver.get(f"{self.base_url}/admin")
        assert self._dashboard_visible(), "admin-role user should see the dashboard"
        assert not self.driver.find_elements(
            By.ID, "apiKey"
        ), "admin-role user must NOT be shown the key-login form"

    def test_annotator_blocked_from_dashboard(self):
        self._login_simple("dan@x.com")
        self.driver.get(f"{self.base_url}/admin")
        assert self._key_form_visible(), "annotator should be shown the key-login form"
        assert not self.driver.find_elements(
            By.CLASS_NAME, "admin-tabs"
        ), "annotator must NOT see the dashboard"

    def test_shared_admin_key_still_works(self):
        # Not logged in: /admin shows the key form; entering the shared key works.
        self.driver.get(f"{self.base_url}/admin")
        assert self._key_form_visible(), "unauthenticated user should see the key form"
        key_input = self.driver.find_element(By.ID, "apiKey")
        key_input.send_keys(ADMIN_KEY)
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        assert self._dashboard_visible(), "valid shared key should open the dashboard"


if __name__ == "__main__":
    unittest.main()
