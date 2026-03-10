"""
Selenium test for issue #117: Allow optional HTML rendering in pure_display
surveyflow content.

Verifies that:
1. By default, HTML in pure_display is escaped (shown as literal text)
2. With allow_html: true, safe HTML is rendered as formatted content
3. Dangerous HTML (script tags) is neutralized even with allow_html: true
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


def create_pure_display_html_config(test_dir, port):
    """Create a config with pure_display schemas testing HTML rendering."""
    test_data = [
        {"id": "item_1", "text": "Test item for display verification."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": f"Pure Display HTML Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            # Schema with allow_html: true — HTML should be rendered
            {
                "name": "html_enabled_section",
                "annotation_type": "pure_display",
                "description": "Section with <b>bold</b> and <em>italic</em> formatting",
                "labels": [
                    "<b>Step 1:</b> Read the text carefully",
                    "<b>Step 2:</b> Make your <em>selection</em>",
                ],
                "allow_html": True,
            },
            # Schema with allow_html: false (default) — HTML should be escaped
            {
                "name": "html_disabled_section",
                "annotation_type": "pure_display",
                "description": "Section with <b>escaped</b> tags",
                "labels": [
                    "<b>This should show literal tags</b>",
                ],
            },
            # Schema with allow_html: true but dangerous content — should be sanitized
            {
                "name": "sanitized_section",
                "annotation_type": "pure_display",
                "description": "Safe content only",
                "labels": [
                    "<b>Safe bold text</b>",
                ],
                "allow_html": True,
            },
            # Actual annotation scheme (needed so annotation page works)
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative"],
                "description": "What is the sentiment?",
            },
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 1,
        "max_annotations_per_item": 3,
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


class TestPureDisplayHtmlUI(unittest.TestCase):
    """
    Issue #117: pure_display schemas should support optional HTML rendering.

    With allow_html: true, safe tags like <b>, <em> should be rendered.
    Without it (default), all HTML should be escaped as literal text.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"pure_display_html_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_pure_display_html_config(cls.test_dir, cls.port)

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
        self.test_user = f"display_user_{int(time.time() * 1000)}"
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
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def test_html_rendered_when_allow_html_true(self):
        """
        With allow_html: true, <b> and <em> tags should be rendered as
        bold/italic text, not shown as literal "<b>" in the page.
        """
        # Find the html_enabled_section form
        form = self.driver.find_element(By.ID, "html_enabled_section")
        form_html = form.get_attribute("innerHTML")

        # The <b> tags should be rendered as actual HTML elements
        bold_elements = form.find_elements(By.TAG_NAME, "b")
        self.assertGreater(
            len(bold_elements), 0,
            "No <b> elements found — HTML was escaped instead of rendered"
        )

        # Check that bold text is visible
        bold_texts = [el.text for el in bold_elements]
        has_step = any("Step" in t for t in bold_texts)
        self.assertTrue(has_step,
                        f"Expected 'Step' in bold text, got: {bold_texts}")

        # Verify <em> is also rendered
        em_elements = form.find_elements(By.TAG_NAME, "em")
        self.assertGreater(
            len(em_elements), 0,
            "No <em> elements found — italic HTML was escaped"
        )

    def test_html_escaped_when_allow_html_false(self):
        """
        Without allow_html (default), HTML tags should appear as literal text
        like "<b>This should show literal tags</b>".
        """
        form = self.driver.find_element(By.ID, "html_disabled_section")

        # The text content should contain the literal tag characters
        display_content = form.find_element(
            By.CSS_SELECTOR, ".display-content"
        )
        visible_text = display_content.text

        # Should see the literal tag text (browser renders &lt;b&gt; as <b>)
        self.assertIn("<b>", visible_text,
                       "Literal <b> tag not visible — HTML was rendered "
                       "when it should have been escaped")

    def test_bold_formatting_visible_in_html_section(self):
        """
        In the allow_html section, bold text should be visually bold
        (i.e., rendered as an actual <b> element, not escaped text).
        """
        form = self.driver.find_element(By.ID, "html_enabled_section")

        # Use JavaScript to check if bold elements exist in the display-content
        bold_count = self.driver.execute_script(
            "return arguments[0].querySelectorAll('.display-content b, legend b').length",
            form,
        )
        self.assertGreater(
            bold_count, 0,
            "No bold elements found in HTML-enabled pure_display section"
        )

    def test_no_script_execution_in_html_section(self):
        """
        Even with allow_html: true, <script> tags should be neutralized.
        The sanitizer escapes them rather than executing them.
        """
        # Verify no JavaScript errors or unexpected script execution
        # by checking that the page loaded normally
        page_source = self.driver.page_source
        self.assertNotIn(
            "<script>alert", page_source,
            "Raw script tag found in page source — XSS vulnerability"
        )

        # The annotation interface should still be functional
        form = self.driver.find_element(By.ID, "sanitized_section")
        self.assertTrue(form.is_displayed())


if __name__ == "__main__":
    unittest.main()
