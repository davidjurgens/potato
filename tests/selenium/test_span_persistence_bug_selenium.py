"""
Selenium test to reproduce the span annotation persistence bug.

This test simulates the real user experience where span highlights disappear
from the UI after navigating away and back to an instance.
"""

import pytest
import os
import tempfile
import shutil
import json
import yaml
from tests.selenium.test_base import BaseSeleniumTest

class TestSpanPersistenceBugSelenium(BaseSeleniumTest):
    """Test span annotation persistence bug using Selenium."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server for this specific test."""
        # We'll set up the server in the test method instead
        pass

    @classmethod
    def tearDownClass(cls):
        """Clean up the Flask server."""
        if hasattr(cls, 'server') and cls.server:
            cls.server.stop_server()

    def setUp(self):
        """Set up for each test."""
        # Call parent setUp to initialize browser options
        super().setUpClass()
        super().setUp()

    def test_span_annotation_persistence_bug(self):
        """Test that reproduces the bug where span highlights disappear from UI after navigation."""

        # Create temporary test directory and files
        test_dir = tempfile.mkdtemp(prefix="span_persistence_selenium_", dir=os.path.join(os.path.dirname(__file__), '..', 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "Span Persistence Selenium Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        try:
            # Set up the server for this test
            from tests.helpers.flask_test_setup import FlaskTestServer
            self.server = FlaskTestServer(port=9008, debug=False, config_file=config_file)
            started = self.server.start_server()
            assert started, "Failed to start Flask server"

            # Set up the base URL
            self.base_url = "http://localhost:9008"

            # Set up the browser
            self.setUp()

            # Register and login user
            username = "test_user_selenium_persistence"
            self.register_user(username, "test_password")
            self.login_user(username, "test_password")

            # Navigate to annotation page
            self.driver.get(f"{self.base_url}/annotate")

            # Wait for page to load
            self.wait_for_element("text-content")

            # Verify we're on the first instance
            instance_text = self.driver.find_element("id", "text-content").text
            assert "I am very happy today" in instance_text, f"Expected text not found. Found: {instance_text}"

            # Create a span annotation by selecting text and clicking a label
            # First, find and click the "happy" label checkbox
            happy_checkbox = self.driver.find_element("id", "emotion_happy")
            happy_checkbox.click()

            # Select the text "very " by simulating text selection
            text_content = self.driver.find_element("id", "text-content")

            # Use JavaScript to select the text "very "
            self.driver.execute_script("""
                var textContent = arguments[0];
                var text = textContent.textContent;
                var startIndex = text.indexOf('very ');
                if (startIndex !== -1) {
                    var range = document.createRange();
                    var startNode = textContent.firstChild;
                    var endNode = textContent.firstChild;
                    range.setStart(startNode, startIndex);
                    range.setEnd(endNode, startIndex + 5);

                    var selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                }
            """, text_content)

            # Wait a moment for the selection to be processed
            import time
            time.sleep(1)

            # Check if span highlight appears after selection
            span_highlights = self.driver.find_elements("css selector", ".span-highlight")
            print(f"Span highlights found after selection: {len(span_highlights)}")

            if len(span_highlights) > 0:
                print("✅ Span highlight created successfully")

                # Now navigate to next instance
                next_button = self.driver.find_element("id", "next-btn")
                next_button.click()

                # Wait for navigation
                time.sleep(2)

                # Verify we're on the second instance
                instance_text = self.driver.find_element("id", "text-content").text
                assert "This is a different instance" in instance_text, f"Expected text not found. Found: {instance_text}"

                # Navigate back to previous instance
                prev_button = self.driver.find_element("id", "prev-btn")
                prev_button.click()

                # Wait for navigation
                time.sleep(2)

                # Verify we're back on the first instance
                instance_text = self.driver.find_element("id", "text-content").text
                assert "I am very happy today" in instance_text, f"Expected text not found. Found: {instance_text}"

                # Check if span highlight is still present
                span_highlights_after = self.driver.find_elements("css selector", ".span-highlight")
                print(f"Span highlights found after navigation: {len(span_highlights_after)}")

                if len(span_highlights_after) == 0:
                    print("❌ BUG CONFIRMED: Span highlights disappeared after navigation!")
                    print("Expected: Span highlights should persist after navigation")
                    print("Actual: No span highlights found after navigation")

                    # The test should fail to indicate the bug
                    assert len(span_highlights_after) > 0, "Span highlights disappeared after navigation - this is the bug!"
                else:
                    print("✅ Span highlights persist after navigation - no bug found")
            else:
                print("❌ Could not create span highlight - test setup issue")
                assert len(span_highlights) > 0, "Could not create span highlight for testing"

        finally:
            # Cleanup
            if hasattr(self, 'driver'):
                self.tearDown()
            if hasattr(self, 'server'):
                self.server.stop_server()
            shutil.rmtree(test_dir)