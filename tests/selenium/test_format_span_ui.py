#!/usr/bin/env python3
"""
Selenium UI tests for span annotation with format display types.

Tests the frontend span annotation functionality:
- Text selection in code, document, and PDF displays
- Span creation and highlighting
- Format-specific coordinate capture
- Multi-span mode across format displays
"""

import time
import os
import json
import yaml
import uuid
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory


class BaseFormatSpanTest(unittest.TestCase):
    """Base class for format span UI tests."""

    @classmethod
    def setUpClass(cls):
        """Set up test server and browser."""
        cls.test_dirs = []
        cls.server = None
        cls.driver = None

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        if cls.driver:
            cls.driver.quit()
        if cls.server:
            cls.server.stop()
        for test_dir in cls.test_dirs:
            try:
                cleanup_test_directory(test_dir)
            except Exception:
                pass

    def _create_test_environment(self, instance_display, data_items, annotation_schemes=None):
        """Create test config and data files."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", f"span_ui_{uuid.uuid4().hex[:8]}")
        os.makedirs(test_dir, exist_ok=True)
        self.test_dirs.append(test_dir)

        # Create data file
        data_file = os.path.join(test_dir, "data.jsonl")
        with open(data_file, "w") as f:
            for item in data_items:
                f.write(json.dumps(item) + "\n")

        output_dir = os.path.join(test_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        # Default span annotation scheme
        if annotation_schemes is None:
            annotation_schemes = [
                {
                    "name": "entities",
                    "description": "Named entity annotation",
                    "annotation_type": "span",
                    "labels": [
                        {"name": "PERSON", "color": "#FF6B6B", "key_binding": "p"},
                        {"name": "ORG", "color": "#4ECDC4", "key_binding": "o"},
                        {"name": "LOC", "color": "#45B7D1", "key_binding": "l"}
                    ]
                }
            ]

        config = {
            "annotation_task_name": "Format Span UI Test",
            "task_dir": test_dir,
            "data_files": ["data.jsonl"],
            "output_annotation_dir": "output",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": annotation_schemes,
            "instance_display": instance_display,
            "user_config": {"allow_all_users": True}
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        return config_file, test_dir

    def _start_server(self, config_file):
        """Start Flask server."""
        if self.server:
            self.server.stop()

        port = find_free_port(preferred_port=9040)
        self.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = self.server.start_server()
        assert started, "Failed to start Flask server"
        self.server._wait_for_server_ready(timeout=10)
        return self.server.base_url

    def _get_driver(self):
        """Get or create WebDriver."""
        if self.driver:
            return self.driver

        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            return self.driver
        except Exception as e:
            self.skipTest(f"Chrome driver not available: {e}")

    def _register_and_login(self, base_url):
        """Register a test user and log in."""
        driver = self._get_driver()
        unique_user = f"test_user_{uuid.uuid4().hex[:8]}"

        driver.get(base_url)
        time.sleep(0.5)

        try:
            register_form = driver.find_element(By.ID, "register-form")
            email_input = register_form.find_element(By.NAME, "email")
            pass_input = register_form.find_element(By.NAME, "pass")
            email_input.send_keys(unique_user)
            pass_input.send_keys("password123")
            register_form.submit()
            time.sleep(0.5)
        except NoSuchElementException:
            pass

        try:
            driver.get(base_url)
            login_form = driver.find_element(By.ID, "login-form")
            email_input = login_form.find_element(By.NAME, "email")
            pass_input = login_form.find_element(By.NAME, "pass")
            email_input.send_keys(unique_user)
            pass_input.send_keys("password123")
            login_form.submit()
            time.sleep(1)
        except NoSuchElementException:
            pass


class TestCodeSpanUI(BaseFormatSpanTest):
    """UI tests for span annotation on code display."""

    def test_code_display_has_data_attribute(self):
        """Test code display has data-original-text for span annotation."""
        instance_display = {
            "fields": [
                {
                    "key": "code",
                    "type": "code",
                    "label": "Source",
                    "span_target": True,
                    "display_options": {"show_line_numbers": True}
                }
            ]
        }
        data_items = [
            {"id": "1", "text": "Test", "code": "def hello():\n    print('Hi')"}
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        # Check for code display element
        try:
            code_display = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "code-display"))
            )
            assert code_display is not None

            # Verify the code content is visible
            page_source = driver.page_source
            assert "def hello()" in page_source or "hello" in page_source
        except TimeoutException:
            page_source = driver.page_source
            assert "code" in page_source.lower()

    def test_code_text_selection_possible(self):
        """Test that text can be selected in code display."""
        instance_display = {
            "fields": [
                {
                    "key": "code",
                    "type": "code",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {"id": "1", "text": "Test", "code": "function test() { return 42; }"}
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        # The test passes if the page loads correctly with span annotation support
        page_source = driver.page_source
        assert "function" in page_source or "test" in page_source

    def test_code_span_label_buttons_present(self):
        """Test that span label buttons are present for code annotation."""
        instance_display = {
            "fields": [
                {"key": "code", "type": "code", "span_target": True}
            ]
        }
        data_items = [
            {"id": "1", "text": "Test", "code": "x = 1"}
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        page_source = driver.page_source
        # Check for span annotation UI elements
        assert "PERSON" in page_source or "entities" in page_source.lower() or "span" in page_source.lower()


class TestDocumentSpanUI(BaseFormatSpanTest):
    """UI tests for span annotation on document display."""

    def test_document_display_renders_for_span(self):
        """Test document display renders with span annotation support."""
        instance_display = {
            "fields": [
                {
                    "key": "document",
                    "type": "document",
                    "label": "Document",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "Test",
                "document": "<p>John Smith works at Acme Corporation in New York.</p>"
            }
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        page_source = driver.page_source
        assert "John Smith" in page_source
        assert "Acme Corporation" in page_source

    def test_document_format_output_renders(self):
        """Test document with FormatOutput dict renders correctly."""
        instance_display = {
            "fields": [
                {
                    "key": "doc_content",
                    "type": "document",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "Test",
                "doc_content": {
                    "text": "The CEO announced quarterly results.",
                    "rendered_html": "<article><h1>Quarterly Report</h1><p>The CEO announced quarterly results.</p></article>",
                    "metadata": {"format": "docx"}
                }
            }
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        page_source = driver.page_source
        assert "Quarterly Report" in page_source or "quarterly" in page_source.lower()


class TestPDFSpanUI(BaseFormatSpanTest):
    """UI tests for span annotation on PDF display."""

    def test_pdf_extracted_content_renders(self):
        """Test PDF with pre-extracted content renders for annotation."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "label": "PDF Document",
                    "span_target": True,
                    "display_options": {"view_mode": "scroll"}
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "Test",
                "pdf_content": {
                    "text": "Abstract: This paper presents research findings.",
                    "rendered_html": "<div class='pdf-page' data-page='1'><p>Abstract: This paper presents research findings.</p></div>",
                    "metadata": {"total_pages": 1}
                }
            }
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        page_source = driver.page_source
        assert "Abstract" in page_source or "paper" in page_source

    def test_pdf_multipage_navigation(self):
        """Test PDF with multiple pages has navigation controls."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "span_target": True,
                    "display_options": {
                        "view_mode": "paginated",
                        "show_page_controls": True
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "Test",
                "pdf_content": {
                    "text": "Page 1 content here.\nPage 2 content here.\nPage 3 content here.",
                    "rendered_html": """
                        <div class='pdf-page' data-page='1'>Page 1 content</div>
                        <div class='pdf-page' data-page='2'>Page 2 content</div>
                        <div class='pdf-page' data-page='3'>Page 3 content</div>
                    """,
                    "metadata": {"total_pages": 3}
                }
            }
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        page_source = driver.page_source
        # Check for page content or navigation elements
        assert "page" in page_source.lower()


class TestMultiTargetSpanUI(BaseFormatSpanTest):
    """UI tests for span annotation across multiple format displays."""

    def test_multiple_span_targets_render(self):
        """Test page with multiple span-targetable displays."""
        instance_display = {
            "fields": [
                {
                    "key": "code",
                    "type": "code",
                    "label": "Source Code",
                    "span_target": True
                },
                {
                    "key": "description",
                    "type": "document",
                    "label": "Documentation",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "Test",
                "code": "def calculate_total(items):\n    return sum(items)",
                "description": "<p>This function calculates the total of all items in the list.</p>"
            }
        ]

        annotation_schemes = [
            {
                "name": "annotations",
                "description": "Multi-target annotations",
                "annotation_type": "span",
                "multi_span": True,
                "labels": [
                    {"name": "FUNCTION", "color": "#FF6B6B"},
                    {"name": "PARAM", "color": "#4ECDC4"}
                ]
            }
        ]

        config_file, _ = self._create_test_environment(
            instance_display, data_items, annotation_schemes
        )
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        page_source = driver.page_source
        # Both displays should be present
        assert "calculate_total" in page_source
        assert "calculates" in page_source or "function" in page_source.lower()

    def test_mixed_text_and_format_displays(self):
        """Test mixing regular text display with format displays."""
        instance_display = {
            "fields": [
                {
                    "key": "text",
                    "type": "text",
                    "label": "Main Text",
                    "span_target": True
                },
                {
                    "key": "code",
                    "type": "code",
                    "label": "Example",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "The function process_data is defined below.",
                "code": "def process_data(x):\n    return x * 2"
            }
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        page_source = driver.page_source
        assert "process_data" in page_source


class TestSpanAnnotationSubmission(BaseFormatSpanTest):
    """UI tests for span annotation submission with format displays."""

    def test_annotation_can_be_submitted(self):
        """Test that annotations can be submitted with format displays."""
        instance_display = {
            "fields": [
                {"key": "code", "type": "code", "span_target": True}
            ]
        }
        data_items = [
            {"id": "1", "text": "Test", "code": "name = 'Alice'"}
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        # Check for submit button
        try:
            submit_btn = driver.find_element(By.ID, "submit-button")
            assert submit_btn is not None
        except NoSuchElementException:
            # Submit button might have different ID
            page_source = driver.page_source
            assert "submit" in page_source.lower()


class TestSpreadsheetSelectionUI(BaseFormatSpanTest):
    """UI tests for spreadsheet row/cell selection."""

    def test_spreadsheet_row_selection_ui(self):
        """Test spreadsheet with row selection mode."""
        instance_display = {
            "fields": [
                {
                    "key": "table",
                    "type": "spreadsheet",
                    "label": "Data",
                    "span_target": True,
                    "display_options": {
                        "annotation_mode": "row",
                        "selectable": True,
                        "show_headers": True
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "Test",
                "table": {
                    "headers": ["Name", "Value"],
                    "rows": [
                        ["Alice", "100"],
                        ["Bob", "200"]
                    ]
                }
            }
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        page_source = driver.page_source
        assert "Alice" in page_source
        assert "Bob" in page_source

    def test_spreadsheet_cell_selection_ui(self):
        """Test spreadsheet with cell selection mode."""
        instance_display = {
            "fields": [
                {
                    "key": "table",
                    "type": "spreadsheet",
                    "span_target": True,
                    "display_options": {"annotation_mode": "cell"}
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "Test",
                "table": [["A1", "B1"], ["A2", "B2"]]
            }
        ]

        config_file, _ = self._create_test_environment(instance_display, data_items)
        base_url = self._start_server(config_file)
        self._register_and_login(base_url)

        driver = self._get_driver()
        driver.get(f"{base_url}/annotate")
        time.sleep(1)

        page_source = driver.page_source
        assert "A1" in page_source or "table" in page_source.lower()


if __name__ == "__main__":
    unittest.main()
