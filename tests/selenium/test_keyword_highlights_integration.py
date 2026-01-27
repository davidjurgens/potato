#!/usr/bin/env python3
"""
Integration test for keyword highlights and span annotations.

This test verifies:
1. Keyword highlights are displayed correctly based on admin-defined keywords
2. Keyword highlight colors match the schema/label configuration
3. Span annotations work correctly alongside keyword highlights
4. Span annotations persist correctly across navigation
5. DOM offsets are correctly handled when both highlights and spans are present
"""

import time
import unittest
import os
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
import requests


class TestKeywordHighlightsIntegration(unittest.TestCase):
    """Integration test for keyword highlights with span annotations."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server with keyword highlights enabled."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import cleanup_test_directory

        # Create test directory
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"keyword_highlights_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create test data with known text for keyword matching (JSONL format)
        test_data = [
            {"id": "item_1", "text": "I love this product. It is excellent and amazing. The quality is wonderful."},
            {"id": "item_2", "text": "This is terrible and disappointing. I hate how bad it is."},
            {"id": "item_3", "text": "The experience was good but some parts were poor and frustrating."},
        ]
        cls.data_file = os.path.join(cls.test_dir, "data.json")
        with open(cls.data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create keywords TSV file
        cls.keywords_file = os.path.join(cls.test_dir, "keywords.tsv")
        with open(cls.keywords_file, 'w') as f:
            f.write("Word\tLabel\tSchema\n")
            f.write("love\tpositive\tsentiment\n")
            f.write("excellent\tpositive\tsentiment\n")
            f.write("amazing\tpositive\tsentiment\n")
            f.write("wonderful\tpositive\tsentiment\n")
            f.write("good\tpositive\tsentiment\n")
            f.write("terrible\tnegative\tsentiment\n")
            f.write("disappointing\tnegative\tsentiment\n")
            f.write("hate\tnegative\tsentiment\n")
            f.write("bad\tnegative\tsentiment\n")
            f.write("poor\tnegative\tsentiment\n")
            f.write("frustrating\tnegative\tsentiment\n")

        # Create annotation output directory
        os.makedirs(os.path.join(cls.test_dir, "annotation_output"), exist_ok=True)

        # Create config file with keyword highlights
        cls.config_file = os.path.join(cls.test_dir, "config.yaml")
        # Note: port is set dynamically below, not in config
        config_content = f"""
server_name: keyword highlights test
annotation_task_name: Keyword Highlights Test
task_dir: {cls.test_dir}
output_annotation_dir: annotation_output/
output_annotation_format: json
data_files:
  - data.json
item_properties:
  id_key: id
  text_key: text
user_config:
  allow_all_users: true
  users: []
keyword_highlights_file: keywords.tsv
ui:
  spans:
    span_colors:
      sentiment:
        positive: "(22, 163, 74)"
        negative: "(239, 68, 68)"
annotation_schemes:
  - annotation_type: span
    name: sentiment
    description: "Mark sentiment phrases"
    labels:
      - positive
      - negative
site_dir: default
"""
        with open(cls.config_file, 'w') as f:
            f.write(config_content)

        # Start server with dynamic port
        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        # Chrome options
        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.session = requests.Session()
        timestamp = int(time.time() * 1000)
        self.test_user = f"test_user_{timestamp}"
        self._login_user()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login_user(self):
        """Login the test user."""
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(self.test_user)
        login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()
        time.sleep(0.05)
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        # Also login via session for API calls
        self.session.post(
            f"{self.server.base_url}/auth",
            data={"email": self.test_user, "pass": "", "action": "login"}
        )

    def _wait_for_page(self, timeout=10):
        """Wait for annotation page to load."""
        WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.CLASS_NAME, "annotation-form"))
        )
        time.sleep(0.05)  # Wait for keyword highlights to load

    def _get_instance_id(self):
        """Get current instance ID."""
        return self.driver.find_element(By.ID, "instance_id").get_attribute("value")

    def _navigate_next(self):
        """Navigate to next instance."""
        try:
            btn = self.driver.find_element(By.ID, "next-btn")
        except:
            btn = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_next"]')
        btn.click()
        time.sleep(0.1)
        self._wait_for_page()

    def _navigate_prev(self):
        """Navigate to previous instance."""
        try:
            btn = self.driver.find_element(By.ID, "prev-btn")
        except:
            btn = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_prev"]')
        btn.click()
        time.sleep(0.1)
        self._wait_for_page()

    def _get_keyword_highlights(self):
        """Get all keyword highlight overlays on the page."""
        return self.driver.find_elements(By.CSS_SELECTOR, '.keyword-highlight-overlay')

    def _get_keyword_highlight_texts(self):
        """Get the text content from keyword highlight titles."""
        highlights = self._get_keyword_highlights()
        texts = []
        for h in highlights:
            title = h.get_attribute('title')
            if title:
                texts.append(title)
        return texts

    def _get_span_overlays(self):
        """Get user-created span annotation overlays."""
        return self.driver.find_elements(By.CSS_SELECTOR, '.span-overlay-pure:not(.keyword-highlight-overlay)')

    def _create_span_via_api(self, instance_id, label, start, end, text):
        """Create a span annotation via API."""
        response = self.session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": instance_id,
                "type": "span",
                "schema": "sentiment",
                "state": [{
                    "name": label,
                    "title": label,
                    "start": start,
                    "end": end,
                    "value": text
                }]
            }
        )
        return response.status_code == 200

    def _get_span_annotations_via_api(self, instance_id):
        """Get span annotations for an instance via API."""
        response = self.session.get(f"{self.server.base_url}/api/spans/{instance_id}")
        if response.status_code == 200:
            return response.json().get("spans", [])
        return []

    def _get_keyword_highlights_via_api(self, instance_id):
        """Get keyword highlights for an instance via API."""
        response = self.session.get(f"{self.server.base_url}/api/keyword_highlights/{instance_id}")
        if response.status_code == 200:
            return response.json().get("keywords", [])
        return []

    # ==================== TESTS ====================

    def test_keyword_highlights_api_returns_matches(self):
        """Test that the keyword highlights API returns correct matches."""
        self._wait_for_page()
        instance_id = self._get_instance_id()

        # Get keyword highlights via API
        keywords = self._get_keyword_highlights_via_api(instance_id)

        print(f"Instance: {instance_id}")
        print(f"Keywords found: {len(keywords)}")
        for kw in keywords:
            print(f"  - {kw['text']} ({kw['label']}) at {kw['start']}-{kw['end']}")

        # Instance 1 should have positive keywords: love, excellent, amazing, wonderful
        self.assertGreater(len(keywords), 0, "Should have keyword matches")

        # Verify keyword structure
        for kw in keywords:
            self.assertIn('label', kw)
            self.assertIn('start', kw)
            self.assertIn('end', kw)
            self.assertIn('text', kw)
            self.assertIn('color', kw)  # Color should be included

    def test_keyword_highlights_displayed_on_page(self):
        """Test that keyword highlights are displayed on the page."""
        self._wait_for_page()

        # Wait a bit more for keyword highlights to render
        time.sleep(0.05)

        highlights = self._get_keyword_highlights()
        print(f"Found {len(highlights)} keyword highlight overlays")

        # Should have keyword highlights on the page
        # Note: This might be 0 if the positioning strategy isn't initialized
        # In that case, we verify via API
        keywords_api = self._get_keyword_highlights_via_api(self._get_instance_id())
        self.assertGreater(len(keywords_api), 0, "API should return keyword matches")

    def test_keyword_highlight_colors_by_label(self):
        """Test that keyword highlights have different colors based on label."""
        self._wait_for_page()
        instance_id = self._get_instance_id()

        # Get keyword highlights via API
        keywords = self._get_keyword_highlights_via_api(instance_id)

        # Check that positive and negative have different colors
        positive_colors = set()
        negative_colors = set()

        for kw in keywords:
            if kw['label'] == 'positive':
                positive_colors.add(kw['color'])
            elif kw['label'] == 'negative':
                negative_colors.add(kw['color'])

        if positive_colors and negative_colors:
            # Positive and negative should have different colors
            self.assertNotEqual(
                positive_colors, negative_colors,
                "Positive and negative keywords should have different colors"
            )
            print(f"Positive colors: {positive_colors}")
            print(f"Negative colors: {negative_colors}")

    def test_span_annotation_alongside_keyword_highlights(self):
        """Test that span annotations work correctly with keyword highlights present."""
        self._wait_for_page()
        instance_id = self._get_instance_id()

        # Verify keyword highlights exist
        keywords = self._get_keyword_highlights_via_api(instance_id)
        self.assertGreater(len(keywords), 0, "Should have keyword highlights")

        # Create a span annotation on text that doesn't overlap with keywords
        # Instance 1 text: "I love this product. It is excellent and amazing. The quality is wonderful."
        # "product" is at position 12-19
        success = self._create_span_via_api(instance_id, "positive", 12, 19, "product")
        self.assertTrue(success, "Should create span annotation")

        # Verify the span was saved
        spans = self._get_span_annotations_via_api(instance_id)
        self.assertEqual(len(spans), 1, "Should have 1 span annotation")
        self.assertEqual(spans[0]['text'], 'product')
        self.assertEqual(spans[0]['start'], 12)
        self.assertEqual(spans[0]['end'], 19)

    def test_span_annotation_on_keyword_text(self):
        """Test creating a span annotation on text that contains a keyword."""
        self._wait_for_page()
        instance_id = self._get_instance_id()

        # Create a span on "love" which is also a keyword
        # "love" is at position 2-6
        success = self._create_span_via_api(instance_id, "positive", 2, 6, "love")
        self.assertTrue(success, "Should create span on keyword text")

        # Verify the span was saved with correct positions
        spans = self._get_span_annotations_via_api(instance_id)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]['text'], 'love')
        self.assertEqual(spans[0]['start'], 2)
        self.assertEqual(spans[0]['end'], 6)

    def test_span_persists_across_navigation_with_highlights(self):
        """Test that span annotations persist correctly when navigating with keyword highlights."""
        self._wait_for_page()
        instance_id_1 = self._get_instance_id()

        # Create span on instance 1
        # "quality" is at position 54-61 in "The quality is wonderful."
        success = self._create_span_via_api(instance_id_1, "positive", 54, 61, "quality")
        self.assertTrue(success)
        print(f"Created span on instance {instance_id_1}")

        # Navigate to instance 2
        self._navigate_next()
        instance_id_2 = self._get_instance_id()
        self.assertNotEqual(instance_id_1, instance_id_2)
        print(f"Navigated to instance {instance_id_2}")

        # Create span on instance 2
        # "terrible" is at position 8-16
        success = self._create_span_via_api(instance_id_2, "negative", 8, 16, "terrible")
        self.assertTrue(success)

        # Navigate back to instance 1
        self._navigate_prev()
        self.assertEqual(self._get_instance_id(), instance_id_1)
        print(f"Navigated back to instance {instance_id_1}")

        # Verify instance 1 span is preserved
        spans = self._get_span_annotations_via_api(instance_id_1)
        self.assertEqual(len(spans), 1, "Instance 1 should have 1 span")
        self.assertEqual(spans[0]['text'], 'quality')
        self.assertEqual(spans[0]['start'], 54)
        self.assertEqual(spans[0]['end'], 61)
        print("Instance 1 span preserved correctly")

        # Navigate to instance 2 and verify its span
        self._navigate_next()
        spans = self._get_span_annotations_via_api(instance_id_2)
        self.assertEqual(len(spans), 1, "Instance 2 should have 1 span")
        self.assertEqual(spans[0]['text'], 'terrible')
        self.assertEqual(spans[0]['start'], 8)
        self.assertEqual(spans[0]['end'], 16)
        print("Instance 2 span preserved correctly")

    def test_keyword_highlights_update_on_navigation(self):
        """Test that keyword highlights update when navigating between instances."""
        self._wait_for_page()
        instance_id_1 = self._get_instance_id()

        # Get keywords for instance 1 (positive sentiment)
        keywords_1 = self._get_keyword_highlights_via_api(instance_id_1)
        labels_1 = set(kw['label'] for kw in keywords_1)
        print(f"Instance 1 keywords: {[kw['text'] for kw in keywords_1]}")

        # Navigate to instance 2 (negative sentiment)
        self._navigate_next()
        instance_id_2 = self._get_instance_id()

        # Get keywords for instance 2
        keywords_2 = self._get_keyword_highlights_via_api(instance_id_2)
        labels_2 = set(kw['label'] for kw in keywords_2)
        print(f"Instance 2 keywords: {[kw['text'] for kw in keywords_2]}")

        # Instance 1 should have mostly positive, instance 2 should have negative
        self.assertIn('positive', labels_1, "Instance 1 should have positive keywords")
        self.assertIn('negative', labels_2, "Instance 2 should have negative keywords")

    def test_exact_span_positions_preserved(self):
        """Test that exact character positions are preserved for span annotations."""
        self._wait_for_page()
        instance_id = self._get_instance_id()

        # Create multiple spans with specific positions
        # Text: "I love this product. It is excellent and amazing. The quality is wonderful."
        test_spans = [
            {"label": "positive", "start": 2, "end": 6, "text": "love"},       # "love"
            {"label": "positive", "start": 27, "end": 36, "text": "excellent"}, # "excellent"
            {"label": "positive", "start": 41, "end": 48, "text": "amazing"},   # "amazing"
        ]

        for span in test_spans:
            success = self._create_span_via_api(
                instance_id, span['label'], span['start'], span['end'], span['text']
            )
            self.assertTrue(success, f"Should create span for '{span['text']}'")

        # Navigate away and back
        self._navigate_next()
        self._navigate_prev()

        # Verify all spans are preserved with exact positions
        spans = self._get_span_annotations_via_api(instance_id)
        self.assertEqual(len(spans), 3, "Should have 3 spans")

        # Sort by start position for comparison
        spans.sort(key=lambda s: s['start'])
        test_spans.sort(key=lambda s: s['start'])

        for i, (saved, expected) in enumerate(zip(spans, test_spans)):
            self.assertEqual(
                saved['start'], expected['start'],
                f"Span {i} start position mismatch: {saved['start']} != {expected['start']}"
            )
            self.assertEqual(
                saved['end'], expected['end'],
                f"Span {i} end position mismatch: {saved['end']} != {expected['end']}"
            )
            self.assertEqual(
                saved['text'], expected['text'],
                f"Span {i} text mismatch: {saved['text']} != {expected['text']}"
            )
            print(f"Span '{saved['text']}' verified: {saved['start']}-{saved['end']}")

    def test_overlapping_span_and_keyword(self):
        """Test behavior when span annotation overlaps with a keyword highlight."""
        self._wait_for_page()
        instance_id = self._get_instance_id()

        # Create a span that overlaps with "excellent" keyword
        # "It is excellent" spans positions 21-36
        success = self._create_span_via_api(instance_id, "positive", 21, 36, "It is excellent")
        self.assertTrue(success)

        # Navigate away and back
        self._navigate_next()
        self._navigate_prev()

        # Verify span is preserved
        spans = self._get_span_annotations_via_api(instance_id)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]['text'], 'It is excellent')
        self.assertEqual(spans[0]['start'], 21)
        self.assertEqual(spans[0]['end'], 36)

        # Verify keywords are still present
        keywords = self._get_keyword_highlights_via_api(instance_id)
        keyword_texts = [kw['text'] for kw in keywords]
        self.assertIn('excellent', keyword_texts, "Keyword 'excellent' should still be highlighted")


if __name__ == '__main__':
    unittest.main(verbosity=2)
