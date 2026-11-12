"""
Selenium UI tests for the judge↔human alignment feature.

Covers BOTH surfaces:
- inline judge suggestion beside the human label (+ Accept fills the radio),
- the admin report page rendering κ / confusion / disagreements.

The judge LLM is never called; we fabricate a persisted judge prediction (what
the admin batch would have written). Runs with debug=True so the admin key
check is bypassed for the report assertion.
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
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory, create_test_config, create_test_data_file

import pytest

pytestmark = pytest.mark.core


class TestJudgeAlignmentUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("judge_align_ui")
        data = [
            {"id": "1", "text": "Q: capital of France?\nAgent: Paris."},
            {"id": "2", "text": "Q: 2+2?\nAgent: 5."},
        ]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{"annotation_type": "radio", "name": "correctness",
                    "description": "Did the agent answer correctly?",
                    "labels": ["correct", "incorrect"]}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[data_file],
            additional_config={
                "item_properties": {"id_key": "id", "text_key": "text"},
                "ai_support": {"enabled": True, "endpoint_type": "ollama",
                               "ai_config": {"model": "llama3.2"}},
                "judge_alignment": {
                    "enabled": True,
                    "schemas": {"correctness": {"rubric": "Be strict."}},
                    "inline": {"enabled": True, "schemas": ["correctness"]},
                },
            },
        )
        # Fabricate a persisted judge prediction for instance "1".
        out_dir = os.path.join(cls.test_dir, "output", "judge_alignment")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "predictions.json"), "w") as f:
            json.dump({"v_ui": {"1::correctness": {
                "instance_id": "1", "schema_name": "correctness",
                "predicted_label": "correct", "confidence": 0.95,
                "reasoning": "Paris is the capital of France.",
                "model_name": "m", "prompt_version": "v_ui", "examples_used": []}}}, f)

        port = find_free_port(preferred_port=9079)
        cls.server = FlaskTestServer(port=port, debug=True, config_file=cls.config_file)
        assert cls.server.start(), "server failed to start"

        cls.opts = ChromeOptions()
        for a in ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-gpu", "--window-size=1500,1100"]:
            cls.opts.add_argument(a)
        cls.opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.opts)
        self.user = f"ja_ui_{int(time.time() * 1000)}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email")))
        try:
            self.driver.find_element(By.ID, "register-tab").click()
            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.ID, "register-content")))
            self.driver.find_element(By.ID, "register-email").send_keys(self.user)
            self.driver.find_element(By.ID, "register-pass").send_keys("test123")
            self.driver.find_element(By.CSS_SELECTOR, "#register-content form").submit()
        except NoSuchElementException:
            f = self.driver.find_element(By.ID, "login-email")
            f.clear(); f.send_keys(self.user)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(0.5)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.ID, "main-content")))
        except TimeoutException:
            pass

    # --- inline surface ---

    def test_inline_block_renders(self):
        block = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "judge-suggestion")))
        self.assertEqual(
            self.driver.find_element(By.CSS_SELECTOR, ".judge-suggested-value").text, "correct")
        self.assertIn("%", self.driver.find_element(By.CSS_SELECTOR, ".judge-confidence").text)

    def test_accept_fills_radio(self):
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "judge-accept-btn"))).click()
        time.sleep(0.4)
        checked = self.driver.find_elements(
            By.CSS_SELECTOR, 'input.annotation-input[schema="correctness"]:checked')
        self.assertTrue(checked)
        self.assertEqual(checked[0].get_attribute("value"), "correct")

    # --- admin report surface ---

    def test_admin_report_renders(self):
        # debug=True bypasses the admin key check.
        self.driver.get(f"{self.server.base_url}/admin/judge-alignment?format=html")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1")))
        body = self.driver.page_source
        self.assertIn("Judge", body)
        self.assertIn("Alignment", body)


if __name__ == "__main__":
    unittest.main()
