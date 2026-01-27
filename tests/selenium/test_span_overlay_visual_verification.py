#!/usr/bin/env python3
"""
=============================================================================
CANONICAL VISUAL VERIFICATION TESTS FOR SPAN ANNOTATION OVERLAYS
=============================================================================

This is THE authoritative test suite for span overlay visual correctness.
Other span test files may test API behavior or edge cases, but this file
tests what the user actually SEES.

WHAT THESE TESTS VERIFY:
1. Overlay position matches selected text position (within 10px tolerance)
2. Labels are visible (not clipped, not transparent, correct text)
3. Colors match schema definition on first creation (not fallback)
4. Padding provides visual breathing room around highlights
5. Overlays appear immediately after selection (no page reload needed)
6. Delete removes overlay completely and immediately
7. Position and visibility persist correctly after navigation

WHY THIS FILE EXISTS:
- Jest/jsdom tests CANNOT verify positioning (getBoundingClientRect returns zeros)
- Many existing Selenium tests only check "element exists in DOM", not position
- This file uses actual browser coordinates to verify visual correctness

WHEN A TEST HERE FAILS:
- It indicates a user-visible bug, not just implementation detail
- Fix the underlying code, don't weaken the assertions

COORDINATE SYSTEM REFERENCE:
- Overlays are positioned relative to #instance-text
- #text-content may have padding that must be accounted for
- All rect comparisons use viewport coordinates from getBoundingClientRect()
"""

import os
import re
import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_span_annotation_config, cleanup_test_directory


class TestSpanOverlayVisualVerification(unittest.TestCase):
    """
    Visual verification tests for span overlay positioning and visibility.

    These tests use getBoundingClientRect() to verify actual screen positions,
    not just DOM existence. This catches bugs where overlays exist but are
    positioned incorrectly or invisible.
    """

    @classmethod
    def setUpClass(cls):
        """Set up Flask server and browser for tests."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "span_visual_verification")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create span annotation config with known text
        config_file, data_file = create_span_annotation_config(
            cls.test_dir,
            annotation_task_name="Span Visual Verification Test",
            require_password=False
        )
        cls.config_file = config_file

        cls.server = FlaskTestServer(debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        """Clean up server and test directory."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Set up browser and authenticate for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, 10)

        # Register and login
        timestamp = int(time.time())
        self.test_user = f"visual_test_{timestamp}"
        self._register_and_login()

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait.until(EC.presence_of_element_located((By.ID, 'text-content')))
        time.sleep(0.1)  # Wait for JS to initialize

    def tearDown(self):
        """Close browser after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _register_and_login(self):
        """Login a test user (no password required in test config)."""
        self.driver.get(f"{self.server.base_url}/")

        # Wait for page to load - with require_password=False, there's just a username field
        self.wait.until(EC.presence_of_element_located((By.ID, "login-email")))

        # Fill in username (no password needed)
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(self.test_user)

        # Submit the form
        login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()

        # Wait for redirect to annotation page
        time.sleep(0.05)

        # Verify we're on the annotation interface
        self.wait.until(EC.presence_of_element_located((By.ID, "task_layout")))

    def _select_word_and_get_rect(self, word):
        """
        Select a word in the text and return its bounding rectangle.

        Returns:
            dict with keys: left, top, right, bottom, width, height
        """
        script = f'''
            const text = document.getElementById('text-content');
            const textContent = text.textContent || text.innerText;
            const wordIndex = textContent.indexOf("{word}");
            if (wordIndex === -1) return null;

            // Find the text node containing the word
            const walker = document.createTreeWalker(text, NodeFilter.SHOW_TEXT);
            let node;
            let offset = 0;
            while (node = walker.nextNode()) {{
                if (offset + node.length > wordIndex) {{
                    const range = document.createRange();
                    range.setStart(node, wordIndex - offset);
                    range.setEnd(node, wordIndex - offset + {len(word)});
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                    return range.getBoundingClientRect();
                }}
                offset += node.length;
            }}
            return null;
        '''
        return self.driver.execute_script(script)

    def _create_span_on_word(self, word, label):
        """
        Select a word and create a span annotation with the given label.

        Args:
            word: The word to select in the text
            label: The label name to apply (e.g., "positive")
        """
        # First, select the label checkbox
        # Span annotation checkboxes use .shadcn-span-checkbox class with value attribute
        label_checkbox = self.driver.find_element(
            By.CSS_SELECTOR, f'.shadcn-span-checkbox[value="{label}"]'
        )
        if not label_checkbox.is_selected():
            label_checkbox.click()
            time.sleep(0.05)

        # Select the word
        selection_rect = self._select_word_and_get_rect(word)
        assert selection_rect is not None, f"Could not find word '{word}' in text"

        # Trigger mouseup to create span
        text_element = self.driver.find_element(By.ID, 'text-content')
        ActionChains(self.driver).move_to_element(text_element).release().perform()
        time.sleep(0.1)  # Wait for span to be created

        return selection_rect

    def _get_overlay_segment_rect(self):
        """Get the bounding rectangle of the first overlay segment."""
        segment = self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-overlay-pure .span-highlight-segment, .span-highlight-segment')
        ))
        return self.driver.execute_script(
            'return arguments[0].getBoundingClientRect();', segment
        )

    def _get_overlay_label(self):
        """Get the label element from the overlay."""
        try:
            return self.driver.find_element(
                By.CSS_SELECTOR, '.span-overlay-pure .span-label, .span-label'
            )
        except Exception:
            return None

    def test_overlay_position_aligns_with_selected_text(self):
        """
        CRITICAL: Verify overlay appears at same coordinates as selected text.

        This is the test that would have caught the positioning bug.
        The overlay's left/top coordinates must be within 10px of the text's coordinates.
        """
        # Get the text content to find a suitable word
        text_element = self.driver.find_element(By.ID, 'text-content')
        text_content = text_element.text

        # Use "thrilled" if present, otherwise first significant word
        word = "thrilled" if "thrilled" in text_content else text_content.split()[2]

        # Create span and get text position
        text_rect = self._create_span_on_word(word, "positive")

        # Get overlay position
        overlay_rect = self._get_overlay_segment_rect()

        # CRITICAL ASSERTION: Overlay must be within 10px of selected text
        left_diff = abs(overlay_rect['left'] - text_rect['left'])
        top_diff = abs(overlay_rect['top'] - text_rect['top'])

        self.assertLess(
            left_diff, 10,
            f"Overlay left ({overlay_rect['left']:.1f}) differs from text left ({text_rect['left']:.1f}) by {left_diff:.1f}px"
        )
        self.assertLess(
            top_diff, 10,
            f"Overlay top ({overlay_rect['top']:.1f}) differs from text top ({text_rect['top']:.1f}) by {top_diff:.1f}px"
        )

    def test_span_label_is_visible(self):
        """
        CRITICAL: Verify the label element is visible and has correct text.

        This catches the "gray box with no text" bug where the label exists
        but CSS selectors don't match so it's not styled correctly.
        """
        text_element = self.driver.find_element(By.ID, 'text-content')
        text_content = text_element.text
        word = "thrilled" if "thrilled" in text_content else text_content.split()[2]

        self._create_span_on_word(word, "positive")

        # Find label element
        label = self._get_overlay_label()
        self.assertIsNotNone(label, "Label element not found in overlay")

        # Verify label text content
        label_text = label.text
        self.assertEqual(
            label_text, "positive",
            f"Label text '{label_text}' does not match expected 'positive'"
        )

        # Verify label is actually visible (not clipped, not transparent)
        visibility_info = self.driver.execute_script('''
            const label = arguments[0];
            const style = window.getComputedStyle(label);
            const rect = label.getBoundingClientRect();
            return {
                display: style.display,
                visibility: style.visibility,
                opacity: style.opacity,
                width: rect.width,
                height: rect.height,
                top: rect.top,
                left: rect.left
            };
        ''', label)

        self.assertNotEqual(
            visibility_info['display'], 'none',
            "Label has display: none"
        )
        self.assertNotEqual(
            visibility_info['visibility'], 'hidden',
            "Label has visibility: hidden"
        )
        self.assertGreater(
            float(visibility_info['opacity']), 0,
            "Label has opacity: 0"
        )
        self.assertGreater(
            visibility_info['width'], 0,
            "Label has zero width (likely not styled correctly)"
        )
        self.assertGreater(
            visibility_info['height'], 0,
            "Label has zero height (likely not styled correctly)"
        )

    def test_overlay_has_correct_color(self):
        """
        Verify overlay segment has a visible color, not the broken fallback.

        The broken fallback was #f0f0f0 (rgb(240, 240, 240)) which is nearly
        invisible against a white background.
        """
        text_element = self.driver.find_element(By.ID, 'text-content')
        text_content = text_element.text
        word = "thrilled" if "thrilled" in text_content else text_content.split()[2]

        self._create_span_on_word(word, "positive")

        segment = self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-highlight-segment')
        ))

        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )

        # Should NOT be the broken fallback colors
        broken_colors = [
            'rgb(240, 240, 240)',  # #f0f0f0 - broken fallback
            'rgba(0, 0, 0, 0)',     # transparent
            'transparent',
        ]

        self.assertNotIn(
            bg_color, broken_colors,
            f"Overlay has broken/invisible color: {bg_color}"
        )

        # Verify it has SOME color (not empty)
        self.assertTrue(
            bg_color and len(bg_color) > 0,
            "Overlay has no background color"
        )

    def test_overlay_width_includes_padding(self):
        """
        Verify overlay width is wider than text to provide padding/breathing room.

        The overlay should include horizontal padding (approximately 3px on each side).
        This is intentional for better visual appearance.
        """
        text_element = self.driver.find_element(By.ID, 'text-content')
        text_content = text_element.text
        word = "thrilled" if "thrilled" in text_content else text_content.split()[2]

        text_rect = self._create_span_on_word(word, "positive")
        overlay_rect = self._get_overlay_segment_rect()

        width_diff = overlay_rect['width'] - text_rect['width']

        # Overlay should be WIDER than text (padding adds approximately 6px total)
        self.assertGreater(
            width_diff, 4,
            f"Overlay width ({overlay_rect['width']:.1f}) should be at least 4px wider than text ({text_rect['width']:.1f}) for padding"
        )
        # But not excessively wider (catch bugs where width is way off)
        self.assertLess(
            width_diff, 15,
            f"Overlay width ({overlay_rect['width']:.1f}) is too much wider than text ({text_rect['width']:.1f})"
        )

    def test_overlay_appears_immediately_after_selection(self):
        """
        Verify overlay appears immediately after text selection, not after navigation.

        This catches the bug where overlays only appeared after page reload.
        """
        text_element = self.driver.find_element(By.ID, 'text-content')
        text_content = text_element.text
        word = "thrilled" if "thrilled" in text_content else text_content.split()[2]

        # Count overlays before
        overlays_before = len(self.driver.find_elements(
            By.CSS_SELECTOR, '.span-overlay-pure, .span-highlight-segment'
        ))

        # Create span
        self._create_span_on_word(word, "positive")

        # Count overlays after (should increase)
        overlays_after = len(self.driver.find_elements(
            By.CSS_SELECTOR, '.span-overlay-pure, .span-highlight-segment'
        ))

        self.assertGreater(
            overlays_after, overlays_before,
            "Overlay did not appear immediately after selection"
        )

    def test_delete_removes_overlay_immediately(self):
        """
        CRITICAL: Verify delete button removes overlay completely from DOM.

        This catches the bug where delete removed label/button but left the
        highlight segment as a ghost element.
        """
        text_element = self.driver.find_element(By.ID, 'text-content')
        text_content = text_element.text
        word = "thrilled" if "thrilled" in text_content else text_content.split()[2]

        # Create span
        self._create_span_on_word(word, "positive")

        # Verify overlay exists
        overlays = self.driver.find_elements(By.CSS_SELECTOR, '.span-overlay-pure')
        self.assertGreater(len(overlays), 0, "Overlay should exist before delete")

        # Click delete button
        delete_btn = self.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, '.span-delete-btn')
        ))
        delete_btn.click()
        time.sleep(0.1)

        # Verify overlay is COMPLETELY removed
        overlays_after = self.driver.find_elements(By.CSS_SELECTOR, '.span-overlay-pure')
        segments_after = self.driver.find_elements(By.CSS_SELECTOR, '.span-highlight-segment')

        self.assertEqual(
            len(overlays_after), 0,
            f"Expected 0 overlays after delete, got {len(overlays_after)}"
        )
        self.assertEqual(
            len(segments_after), 0,
            f"Expected 0 segments after delete, got {len(segments_after)} (ghost elements)"
        )

    def test_overlay_position_correct_after_navigation(self):
        """
        CRITICAL: Verify overlay position is still correct after navigating away and back.

        This catches bugs where overlays are re-created with wrong coordinates.
        """
        text_element = self.driver.find_element(By.ID, 'text-content')
        text_content = text_element.text
        word = "thrilled" if "thrilled" in text_content else text_content.split()[2]

        # Create span and get initial position
        text_rect = self._create_span_on_word(word, "positive")
        initial_overlay_rect = self._get_overlay_segment_rect()

        # Navigate away
        next_btn = self.driver.find_element(By.ID, 'next-btn')
        next_btn.click()
        time.sleep(0.1)

        # Navigate back
        prev_btn = self.driver.find_element(By.ID, 'prev-btn')
        prev_btn.click()
        time.sleep(0.1)

        # Wait for overlay to re-render
        self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-overlay-pure')
        ))

        # Get position after navigation
        after_overlay_rect = self._get_overlay_segment_rect()

        # Position should be nearly the same (within tolerance for re-render)
        # Allow 8px tolerance to account for font rendering differences between renders
        left_diff = abs(after_overlay_rect['left'] - initial_overlay_rect['left'])
        top_diff = abs(after_overlay_rect['top'] - initial_overlay_rect['top'])

        self.assertLess(
            left_diff, 8,
            f"Overlay left changed by {left_diff:.1f}px after navigation"
        )
        self.assertLess(
            top_diff, 8,
            f"Overlay top changed by {top_diff:.1f}px after navigation"
        )

    def test_label_visible_after_navigation(self):
        """
        CRITICAL: Verify label remains visible after navigation.

        This catches the bug where label/button disappeared but overlay remained.
        """
        text_element = self.driver.find_element(By.ID, 'text-content')
        text_content = text_element.text
        word = "thrilled" if "thrilled" in text_content else text_content.split()[2]

        self._create_span_on_word(word, "positive")

        # Navigate away and back
        next_btn = self.driver.find_element(By.ID, 'next-btn')
        next_btn.click()
        time.sleep(0.1)

        prev_btn = self.driver.find_element(By.ID, 'prev-btn')
        prev_btn.click()
        time.sleep(0.1)

        # Wait for overlay
        self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-overlay-pure')
        ))

        # Verify label is visible
        label = self._get_overlay_label()
        self.assertIsNotNone(label, "Label not found after navigation")

        visibility_info = self.driver.execute_script('''
            const label = arguments[0];
            const style = window.getComputedStyle(label);
            const rect = label.getBoundingClientRect();
            return {
                display: style.display,
                visibility: style.visibility,
                opacity: style.opacity,
                width: rect.width,
                height: rect.height,
                text: label.textContent
            };
        ''', label)

        self.assertNotEqual(visibility_info['display'], 'none', "Label has display: none after navigation")
        self.assertGreater(visibility_info['width'], 0, "Label has zero width after navigation")
        self.assertEqual(visibility_info['text'], "positive", "Label text incorrect after navigation")

    def test_color_not_fallback_on_first_creation(self):
        """
        CRITICAL: Verify color is schema-defined on first creation, not fallback.

        This catches the bug where currentSchema wasn't set before color lookup,
        causing the fallback purple color to appear.
        """
        text_element = self.driver.find_element(By.ID, 'text-content')
        text_content = text_element.text
        word = "thrilled" if "thrilled" in text_content else text_content.split()[2]

        self._create_span_on_word(word, "positive")

        segment = self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-highlight-segment')
        ))

        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )

        # Parse the color
        import re
        match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', bg_color)
        self.assertIsNotNone(match, f"Could not parse color: {bg_color}")

        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))

        # Should NOT be fallback purple (110, 86, 207)
        is_fallback_purple = (abs(r - 110) < 20 and abs(g - 86) < 20 and abs(b - 207) < 20)
        self.assertFalse(
            is_fallback_purple,
            f"Color is fallback purple on first creation! RGB=({r}, {g}, {b}). "
            "This indicates currentSchema was not set before getSpanColor() was called."
        )

        # Should NOT be default yellow (255, 255, 0)
        is_default_yellow = (r > 200 and g > 200 and b < 50)
        self.assertFalse(
            is_default_yellow,
            f"Color is default yellow on first creation! RGB=({r}, {g}, {b})"
        )


if __name__ == '__main__':
    unittest.main()
