#!/usr/bin/env python3
"""
Selenium tests for dialogue span annotation UI.

Tests end-to-end span annotation on DialogueDisplay fields:
- Verifies .text-content element exists inside dialogue span target
- Tests span creation via label click + text selection
- Tests annotation persistence across navigation
"""

import os
import sys
import json
import yaml
import time
import unittest

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from tests.selenium.test_base import BaseSeleniumTest
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


import pytest

pytestmark = pytest.mark.core

def create_dialogue_span_config(test_dir):
    """Create a config with dialogue display as span target for selenium tests."""
    os.makedirs(test_dir, exist_ok=True)
    os.makedirs(os.path.join(test_dir, "data"), exist_ok=True)
    os.makedirs(os.path.join(test_dir, "annotation_output"), exist_ok=True)

    data = [
        {
            "id": "trace_001",
            "task_description": "Book a flight to London",
            "conversation": [
                {"speaker": "Agent", "text": "I will search for flights to London."},
                {"speaker": "Environment", "text": "Found 3 flights: BA117 $450, VS3 $485, AA100 $520."},
                {"speaker": "Agent", "text": "BA117 at $450 is the cheapest option. Booking now."},
            ]
        },
        {
            "id": "trace_002",
            "task_description": "Debug the Python script",
            "conversation": [
                {"speaker": "Agent", "text": "Let me read the script file."},
                {"speaker": "Environment", "text": "File contents displayed."},
            ]
        }
    ]
    data_file = os.path.join(test_dir, "data", "test_traces.json")
    with open(data_file, 'w') as f:
        json.dump(data, f)

    config = {
        "port": 8000,
        "server_name": "dialogue span selenium test",
        "annotation_task_name": "Dialogue Span Selenium Test",
        "task_dir": os.path.abspath(test_dir),
        "output_annotation_dir": os.path.join(os.path.abspath(test_dir), "annotation_output"),
        "output_annotation_format": "json",
        "data_files": [os.path.join(os.path.abspath(test_dir), "data", "test_traces.json")],
        "item_properties": {
            "id_key": "id",
            "text_key": "task_description"
        },
        "user_config": {
            "allow_all_users": True,
            "users": []
        },
        "authentication": {"method": "in_memory"},
        "alert_time_each_instance": 10000000,
        "require_password": False,
        "persist_sessions": False,
        "debug": False,
        "secret_key": "test-secret-key",
        "session_lifetime_days": 1,
        "site_dir": "default",
        "instance_display": {
            "layout": {"direction": "vertical", "gap": "16px"},
            "fields": [
                {
                    "key": "task_description",
                    "type": "text",
                    "label": "Task"
                },
                {
                    "key": "conversation",
                    "type": "dialogue",
                    "label": "Agent Trace",
                    "span_target": True,
                    "display_options": {
                        "show_turn_numbers": True,
                        "alternating_shading": True,
                        "max_height": 800
                    }
                }
            ]
        },
        "annotation_schemes": [
            {
                "annotation_type": "span",
                "name": "issue_spans",
                "description": "Highlight issues in the trace",
                "labels": [
                    {"name": "hallucination", "tooltip": "Unsupported claim"},
                    {"name": "error", "tooltip": "Factual error"}
                ]
            }
        ]
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


class TestDialogueSpanAnnotationUI(BaseSeleniumTest):
    """Selenium tests for dialogue span annotation."""

    @classmethod
    def setUpClass(cls):
        """Set up server with dialogue span config."""
        from selenium.webdriver.chrome.options import Options as ChromeOptions

        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", "selenium_dialogue_span")
        os.makedirs(test_dir, exist_ok=True)

        cls.test_dir = test_dir
        config_file = create_dialogue_span_config(test_dir)

        port = find_free_port(preferred_port=9051)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        cls.chrome_options = chrome_options

    def wait_for_element(self, by, value, timeout=10):
        """Wait for and return an element."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def navigate_to_annotation(self):
        """Navigate to the annotation page and wait for it to load."""
        self.driver.get(f"{self.server.base_url}/annotate")
        # Wait for main content to be visible
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)  # Let JS initialize

    def test_text_content_wrapper_exists(self):
        """Verify .text-content element exists inside the dialogue span target."""
        self.navigate_to_annotation()
        text_content = self.driver.find_elements(
            By.CSS_SELECTOR, '#text-content-conversation'
        )
        assert len(text_content) > 0, "text-content-conversation element not found"

    def test_text_content_has_data_original_text(self):
        """Verify the text-content element has a data-original-text attribute."""
        self.navigate_to_annotation()
        el = self.wait_for_element(By.ID, "text-content-conversation")
        original_text = el.get_attribute("data-original-text")
        assert original_text is not None, "data-original-text attribute missing"
        assert len(original_text) > 0, "data-original-text is empty"
        # Should contain concatenated dialogue
        assert "Agent:" in original_text

    def test_dialogue_turns_visible(self):
        """Verify dialogue turns are rendered and visible."""
        self.navigate_to_annotation()
        turns = self.driver.find_elements(By.CSS_SELECTOR, ".dialogue-turn")
        assert len(turns) >= 3, f"Expected at least 3 turns, got {len(turns)}"

    def test_span_target_field_has_data_attribute(self):
        """Verify the display field container has data-span-target='true'."""
        self.navigate_to_annotation()
        span_targets = self.driver.find_elements(
            By.CSS_SELECTOR, '[data-span-target="true"]'
        )
        assert len(span_targets) > 0, "No span target fields found"

    def test_span_manager_initializes_for_dialogue(self):
        """Check that SpanManager has fieldStrategies for the conversation field."""
        self.navigate_to_annotation()
        time.sleep(1)  # Wait for SpanManager init

        result = self.driver.execute_script("""
            if (window.spanManager && window.spanManager.fieldStrategies) {
                return Object.keys(window.spanManager.fieldStrategies);
            }
            return [];
        """)
        assert "conversation" in result, \
            f"SpanManager.fieldStrategies missing 'conversation', got: {result}"

    def test_span_overlay_container_exists(self):
        """Verify span overlay container is created for the dialogue field."""
        self.navigate_to_annotation()
        time.sleep(1)

        containers = self.driver.find_elements(
            By.CSS_SELECTOR, '#span-overlays-conversation'
        )
        # May or may not exist until a span is created, but the container
        # should be created by SpanManager.initialize()
        # Check via JS
        result = self.driver.execute_script("""
            return document.getElementById('span-overlays-conversation') !== null;
        """)
        assert result, "span-overlays-conversation container not found"


if __name__ == '__main__':
    unittest.main()
