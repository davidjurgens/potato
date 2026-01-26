#!/usr/bin/env python3
"""
Tests for span overlay bugs:
1. Color mismatch between overlay and schema-defined label color
2. Missing padding around overlay segments
3. Delete/navigation bug where overlays remain but label/button disappear

These tests are designed to reproduce and verify fixes for specific bugs.
"""

import os
import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, create_test_config, cleanup_test_directory


def create_span_config_with_colors(test_dir):
    """
    Create a span annotation config with explicitly defined colors.
    """
    test_data = [
        {"id": "1", "text": "I am absolutely thrilled about this new technology."},
        {"id": "2", "text": "The weather is terrible today and I feel sad."},
        {"id": "3", "text": "This is a neutral factual statement about nothing."}
    ]

    data_file = create_test_data_file(test_dir, test_data)

    # Define colors explicitly - these should be visible and distinct
    annotation_schemes = [
        {
            "name": "sentiment",
            "annotation_type": "span",
            "labels": ["positive", "negative", "neutral"],
            "description": "Mark sentiment in text",
            "color_scheme": {
                "positive": "rgba(34, 197, 94, 0.4)",   # Green with transparency
                "negative": "rgba(239, 68, 68, 0.4)",   # Red with transparency
                "neutral": "rgba(156, 163, 175, 0.4)"   # Gray with transparency
            }
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        annotation_task_name="Span Color Bug Test",
        require_password=False
    )

    return config_file, data_file


def create_span_config_default_colors(test_dir):
    """
    Create a span annotation config WITHOUT explicit colors.
    Labels will use the default palette from SPAN_COLOR_PALETTE.

    Default palette order:
    - Index 0: purple (110, 86, 207)
    - Index 1: red (239, 68, 68)
    """
    test_data = [
        {"id": "1", "text": "I am absolutely thrilled about this new technology."},
        {"id": "2", "text": "The weather is terrible today and I feel sad."},
    ]

    data_file = create_test_data_file(test_dir, test_data)

    # NO explicit color_scheme - will use default palette
    annotation_schemes = [
        {
            "name": "emotion",
            "annotation_type": "span",
            "labels": ["happy", "sad"],
            "description": "Mark emotions in text"
            # Note: NO color_scheme defined
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        annotation_task_name="Default Color Test",
        require_password=False
    )

    return config_file, data_file


class TestSpanOverlayBugs(unittest.TestCase):
    """
    Bug reproduction tests for span overlay issues.
    """

    @classmethod
    def setUpClass(cls):
        """Set up Flask server and browser for tests."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "span_overlay_bugs")
        os.makedirs(cls.test_dir, exist_ok=True)

        config_file, data_file = create_span_config_with_colors(cls.test_dir)
        cls.config_file = config_file

        cls.server = FlaskTestServer(debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

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

        timestamp = int(time.time())
        self.test_user = f"bug_test_{timestamp}"
        self._login()
        self._navigate_to_annotation()

    def tearDown(self):
        """Close browser after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login(self):
        """Login a test user (no password required)."""
        self.driver.get(f"{self.server.base_url}/")
        self.wait.until(EC.presence_of_element_located((By.ID, "login-email")))

        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(self.test_user)

        login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()
        time.sleep(0.05)

        self.wait.until(EC.presence_of_element_located((By.ID, "task_layout")))

    def _navigate_to_annotation(self):
        """Navigate to the annotation page."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait.until(EC.presence_of_element_located((By.ID, 'text-content')))
        time.sleep(0.1)

    def _select_word_and_get_rect(self, word):
        """Select a word and return its bounding rect."""
        script = f'''
            const text = document.getElementById('text-content');
            const textContent = text.textContent || text.innerText;
            const wordIndex = textContent.indexOf("{word}");
            if (wordIndex === -1) return null;

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
        """Create a span annotation on the given word with the given label."""
        # Select the label checkbox
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
        time.sleep(0.1)

        return selection_rect

    def _get_overlay_segment(self):
        """Get the first overlay segment element."""
        return self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-overlay-pure .span-highlight-segment, .span-highlight-segment')
        ))

    def _count_overlays(self):
        """Count all span overlays."""
        return len(self.driver.find_elements(By.CSS_SELECTOR, '.span-overlay-pure'))

    def _count_overlay_segments(self):
        """Count all overlay segments."""
        return len(self.driver.find_elements(By.CSS_SELECTOR, '.span-highlight-segment'))

    # ==================== BUG 1: COLOR MISMATCH ====================

    def test_overlay_color_matches_schema_defined_color(self):
        """
        BUG 1: Verify overlay color matches the color defined in the schema.

        The schema defines:
        - positive: rgba(34, 197, 94, 0.4) - green
        - negative: rgba(239, 68, 68, 0.4) - red
        - neutral: rgba(156, 163, 175, 0.4) - gray

        The overlay should use these exact colors, not a fallback.
        """
        self._create_span_on_word("thrilled", "positive")

        segment = self._get_overlay_segment()
        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )

        # The color should be greenish (positive), not purple fallback
        # rgba(34, 197, 94, 0.4) should compute to something with high green component
        # Parse the rgba color
        self.assertIn('rgba', bg_color.lower(), f"Expected rgba color, got: {bg_color}")

        # Extract RGB values
        import re
        match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', bg_color)
        self.assertIsNotNone(match, f"Could not parse color: {bg_color}")

        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))

        # For "positive" (green), green should be the dominant component
        # Allow some tolerance for browser rendering
        self.assertGreater(
            g, r,
            f"Expected green > red for positive label. Got R={r}, G={g}, B={b}"
        )
        self.assertGreater(
            g, b,
            f"Expected green > blue for positive label. Got R={r}, G={g}, B={b}"
        )

    def test_negative_label_has_red_color(self):
        """Verify negative label gets red color from schema."""
        # Navigate to instance with "terrible" text
        next_btn = self.driver.find_element(By.ID, 'next-btn')
        next_btn.click()
        time.sleep(0.5)

        self._create_span_on_word("terrible", "negative")

        segment = self._get_overlay_segment()
        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )

        import re
        match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', bg_color)
        self.assertIsNotNone(match, f"Could not parse color: {bg_color}")

        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))

        # For "negative" (red), red should be the dominant component
        self.assertGreater(
            r, g,
            f"Expected red > green for negative label. Got R={r}, G={g}, B={b}"
        )

    def test_color_correct_immediately_on_creation(self):
        """
        BUG 1 CRITICAL: Verify color is correct IMMEDIATELY when overlay is created,
        not just after re-render from server.

        This test specifically checks that the color doesn't flash yellow/purple
        before showing the correct schema color.
        """
        # Capture colors immediately after creation with no delay
        self._create_span_on_word("thrilled", "positive")

        # Get color immediately (no additional sleep)
        segment = self.driver.find_element(
            By.CSS_SELECTOR, '.span-overlay-pure .span-highlight-segment, .span-highlight-segment'
        )
        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )

        # The color should NOT be the fallback purple or default yellow
        import re
        match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', bg_color)
        self.assertIsNotNone(match, f"Could not parse color: {bg_color}")

        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))

        # Check it's NOT the fallback purple (110, 86, 207)
        is_fallback_purple = (abs(r - 110) < 20 and abs(g - 86) < 20 and abs(b - 207) < 20)
        self.assertFalse(
            is_fallback_purple,
            f"Color is fallback purple on first creation! Got R={r}, G={g}, B={b}"
        )

        # Check it's NOT the default yellow (255, 255, 0)
        is_default_yellow = (r > 200 and g > 200 and b < 50)
        self.assertFalse(
            is_default_yellow,
            f"Color is default yellow on first creation! Got R={r}, G={g}, B={b}"
        )

        # For "positive" (green), green should be dominant
        self.assertGreater(
            g, r,
            f"Expected green > red for positive label on FIRST creation. Got R={r}, G={g}, B={b}"
        )

    def test_second_label_uses_second_color_not_first(self):
        """
        BUG 1 REGRESSION: Verify that clicking the second label uses the second
        label's color, not the first label's color.

        This catches the bug where getSelectedLabel() used document.querySelector()
        which returns the first checkbox in DOM order, not the one just clicked.
        """
        # First, click positive label (green) but don't select text yet
        positive_checkbox = self.driver.find_element(
            By.CSS_SELECTOR, '.shadcn-span-checkbox[value="positive"]'
        )
        positive_checkbox.click()
        time.sleep(0.05)

        # Now click negative label (red) - this is the label we want to use
        negative_checkbox = self.driver.find_element(
            By.CSS_SELECTOR, '.shadcn-span-checkbox[value="negative"]'
        )
        negative_checkbox.click()
        time.sleep(0.05)

        # Now select text and create span - should use NEGATIVE (red) color
        selection_rect = self._select_word_and_get_rect("thrilled")
        self.assertIsNotNone(selection_rect, "Could not find word 'thrilled' in text")

        # Trigger mouseup to create span
        text_element = self.driver.find_element(By.ID, 'text-content')
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self.driver).move_to_element(text_element).release().perform()
        time.sleep(0.1)

        # Get the overlay color
        segment = self._get_overlay_segment()
        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )

        # Parse RGB values
        import re
        match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', bg_color)
        self.assertIsNotNone(match, f"Could not parse color: {bg_color}")

        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))

        # Should be RED (negative), not GREEN (positive)
        # Red should be the dominant color component
        self.assertGreater(
            r, g,
            f"Expected RED (negative label) but got GREEN-dominant color. "
            f"R={r}, G={g}, B={b}. This indicates the first label's color was used instead of the clicked label."
        )

    def test_only_click_second_label_uses_second_color(self):
        """
        CRITICAL BUG REPRODUCTION: Click ONLY the second label (never the first).

        This mimics the exact user workflow where they:
        1. Load page (no checkbox selected)
        2. Click ONLY the second label
        3. Select text
        4. Create span

        The span should use the second label's color, not the first.
        """
        # Enable browser console logging capture
        self.driver.execute_script('''
            window._consoleLogs = [];
            const originalLog = console.log;
            const originalWarn = console.warn;
            console.log = function(...args) {
                window._consoleLogs.push({type: 'log', msg: args.map(a => String(a)).join(' ')});
                originalLog.apply(console, args);
            };
            console.warn = function(...args) {
                window._consoleLogs.push({type: 'warn', msg: args.map(a => String(a)).join(' ')});
                originalWarn.apply(console, args);
            };
        ''')

        # IMPORTANT: Do NOT click the first label at all
        # Just click the second label (negative = red)
        negative_checkbox = self.driver.find_element(
            By.CSS_SELECTOR, '.shadcn-span-checkbox[value="negative"]'
        )
        negative_checkbox.click()
        time.sleep(0.1)

        # Log the state of spanManager after clicking checkbox
        state_before = self.driver.execute_script('''
            if (!window.spanManager) return { error: 'no spanManager' };
            return {
                selectedLabel: window.spanManager.selectedLabel,
                currentSchema: window.spanManager.currentSchema,
                hasColors: !!window.spanManager.colors,
                colorKeys: window.spanManager.colors ? Object.keys(window.spanManager.colors) : [],
                schemaColors: window.spanManager.colors && window.spanManager.currentSchema
                    ? window.spanManager.colors[window.spanManager.currentSchema]
                    : null
            };
        ''')
        print(f"[DEBUG] State BEFORE text selection: {state_before}")

        # Verify selectedLabel is set correctly
        self.assertEqual(
            state_before.get('selectedLabel'), 'negative',
            f"Expected selectedLabel='negative' but got {state_before}"
        )

        # Now select text
        selection_rect = self._select_word_and_get_rect("thrilled")
        self.assertIsNotNone(selection_rect, "Could not find word 'thrilled' in text")

        # Log state right before mouseup
        state_during = self.driver.execute_script('''
            if (!window.spanManager) return { error: 'no spanManager' };
            return {
                selectedLabel: window.spanManager.selectedLabel,
                currentSchema: window.spanManager.currentSchema
            };
        ''')
        print(f"[DEBUG] State DURING (after selection, before mouseup): {state_during}")

        # Trigger mouseup to create span
        text_element = self.driver.find_element(By.ID, 'text-content')
        ActionChains(self.driver).move_to_element(text_element).release().perform()
        time.sleep(0.1)

        # Get the overlay color
        segment = self._get_overlay_segment()
        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )
        print(f"[DEBUG] Overlay background color: {bg_color}")

        # Parse RGB values
        import re
        match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', bg_color)
        self.assertIsNotNone(match, f"Could not parse color: {bg_color}")

        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
        print(f"[DEBUG] Parsed RGB: R={r}, G={g}, B={b}")

        # Print console logs from browser
        console_logs = self.driver.execute_script('return window._consoleLogs || [];')
        print(f"[DEBUG] Browser console logs ({len(console_logs)} entries):")
        for log in console_logs:
            if 'SpanManager' in log.get('msg', ''):
                print(f"  [{log.get('type')}] {log.get('msg')}")

        # Should be RED (negative), not GREEN (positive)
        # Red: rgba(239, 68, 68, 0.4) -> R should be highest
        # Green: rgba(34, 197, 94, 0.4) -> G should be highest
        self.assertGreater(
            r, g,
            f"BUG REPRODUCED! Expected RED (negative label, r>g) but got green-dominant. "
            f"R={r}, G={g}, B={b}. The FIRST label's color is being used instead of the SECOND."
        )

    def test_select_text_first_then_click_label(self):
        """
        ALTERNATIVE WORKFLOW: User selects text FIRST, then clicks label.

        Workflow:
        1. User selects text with mouse
        2. User then clicks the second checkbox (negative/red)
        3. Span should be created with the clicked label's color

        This tests if the mouseup from checkbox click triggers span creation
        with the correct label.
        """
        # Step 1: Select text FIRST (before clicking any checkbox)
        selection_rect = self._select_word_and_get_rect("thrilled")
        self.assertIsNotNone(selection_rect, "Could not find word 'thrilled' in text")
        time.sleep(0.05)

        # Verify selection is active
        has_selection = self.driver.execute_script('''
            const sel = window.getSelection();
            return sel.rangeCount > 0 && !sel.isCollapsed;
        ''')
        self.assertTrue(has_selection, "Text should be selected before clicking checkbox")

        # Step 2: Click the SECOND label (negative/red) while text is selected
        # The onclick handler should trigger changeSpanLabel FIRST, then the mouseup
        # on the checkbox shouldn't trigger span creation (checkbox is outside text container)
        negative_checkbox = self.driver.find_element(
            By.CSS_SELECTOR, '.shadcn-span-checkbox[value="negative"]'
        )

        # Log state before clicking
        state_before = self.driver.execute_script('''
            return {
                selectedLabel: window.spanManager?.selectedLabel,
                currentSchema: window.spanManager?.currentSchema
            };
        ''')
        print(f"[DEBUG] State BEFORE checkbox click: {state_before}")

        negative_checkbox.click()
        time.sleep(0.1)

        # Log state after clicking checkbox
        state_after_click = self.driver.execute_script('''
            return {
                selectedLabel: window.spanManager?.selectedLabel,
                currentSchema: window.spanManager?.currentSchema
            };
        ''')
        print(f"[DEBUG] State AFTER checkbox click: {state_after_click}")

        # Verify selectedLabel is now 'negative'
        self.assertEqual(
            state_after_click.get('selectedLabel'), 'negative',
            f"Expected selectedLabel='negative' after clicking checkbox, got {state_after_click}"
        )

        # Now text should still be selected - trigger mouseup on text to create span
        # Check if a span was already created by the checkbox click
        existing_spans = self.driver.find_elements(By.CSS_SELECTOR, '.span-overlay-pure')
        print(f"[DEBUG] Spans after checkbox click (before explicit mouseup): {len(existing_spans)}")

        if len(existing_spans) == 0:
            # Need to trigger mouseup on text container to create span
            text_element = self.driver.find_element(By.ID, 'text-content')
            ActionChains(self.driver).move_to_element(text_element).release().perform()
            time.sleep(0.1)

        # Get the overlay color
        segment = self._get_overlay_segment()
        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )
        print(f"[DEBUG] Overlay background color: {bg_color}")

        # Parse RGB values
        import re
        match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', bg_color)
        self.assertIsNotNone(match, f"Could not parse color: {bg_color}")

        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
        print(f"[DEBUG] Parsed RGB: R={r}, G={g}, B={b}")

        # Should be RED (negative), not GREEN (positive)
        self.assertGreater(
            r, g,
            f"BUG! Expected RED (negative, r>g) but got green-dominant color. "
            f"R={r}, G={g}, B={b}. This indicates wrong label's color was used."
        )

    def test_span_creation_logs_correct_label_in_callback(self):
        """
        Debug test: Verify the label used in handleTextSelection matches the clicked checkbox.

        This test intercepts the span creation to verify exactly what label/color is used.
        """
        # Add instrumentation to track what happens during span creation
        self.driver.execute_script('''
            window._debugSpanCreation = [];

            // Monkey-patch getSelectedLabel to log what it returns
            const originalGetSelectedLabel = window.spanManager.getSelectedLabel.bind(window.spanManager);
            window.spanManager.getSelectedLabel = function() {
                const result = originalGetSelectedLabel();
                window._debugSpanCreation.push({
                    action: 'getSelectedLabel',
                    result: result,
                    selectedLabel: this.selectedLabel,
                    currentSchema: this.currentSchema
                });
                return result;
            };

            // Monkey-patch getSpanColor to log what color is returned
            const originalGetSpanColor = window.spanManager.getSpanColor.bind(window.spanManager);
            window.spanManager.getSpanColor = function(label) {
                const result = originalGetSpanColor(label);
                window._debugSpanCreation.push({
                    action: 'getSpanColor',
                    label: label,
                    result: result,
                    currentSchema: this.currentSchema,
                    colors: this.colors ? JSON.parse(JSON.stringify(this.colors)) : null
                });
                return result;
            };
        ''')

        # Click ONLY the second label
        negative_checkbox = self.driver.find_element(
            By.CSS_SELECTOR, '.shadcn-span-checkbox[value="negative"]'
        )
        negative_checkbox.click()
        time.sleep(0.1)

        # Select text and create span
        self._select_word_and_get_rect("thrilled")
        text_element = self.driver.find_element(By.ID, 'text-content')
        ActionChains(self.driver).move_to_element(text_element).release().perform()
        time.sleep(0.1)

        # Get debug logs
        debug_logs = self.driver.execute_script('return window._debugSpanCreation;')
        print(f"[DEBUG] Span creation logs: {debug_logs}")

        # Find the getSelectedLabel call
        get_label_calls = [log for log in debug_logs if log.get('action') == 'getSelectedLabel']
        self.assertGreater(len(get_label_calls), 0, "getSelectedLabel was not called during span creation")

        # Verify it returned 'negative' (the clicked label)
        last_label_call = get_label_calls[-1]
        self.assertEqual(
            last_label_call.get('result'), 'negative',
            f"getSelectedLabel returned wrong label: {last_label_call}"
        )

        # Find the getSpanColor call
        get_color_calls = [log for log in debug_logs if log.get('action') == 'getSpanColor']
        self.assertGreater(len(get_color_calls), 0, "getSpanColor was not called during span creation")

        # Verify it was called with 'negative' label
        last_color_call = get_color_calls[-1]
        self.assertEqual(
            last_color_call.get('label'), 'negative',
            f"getSpanColor was called with wrong label: {last_color_call}"
        )

    # ==================== BUG 2: MISSING PADDING ====================

    def test_overlay_has_padding_around_text(self):
        """
        BUG 2: Verify overlay has padding around the text, not tight fit.

        The overlay should extend slightly beyond the text boundaries
        to create visual breathing room.
        """
        text_rect = self._create_span_on_word("thrilled", "positive")

        segment = self._get_overlay_segment()
        overlay_rect = self.driver.execute_script(
            'return arguments[0].getBoundingClientRect();', segment
        )

        # Overlay should be WIDER than the text (horizontal padding)
        # Allow at least 2px padding on each side (4px total)
        width_diff = overlay_rect['width'] - text_rect['width']
        self.assertGreaterEqual(
            width_diff, 4,
            f"Overlay width ({overlay_rect['width']:.1f}) should be at least 4px wider than text ({text_rect['width']:.1f})"
        )

        # Overlay should be TALLER than the text (vertical padding)
        height_diff = overlay_rect['height'] - text_rect['height']
        self.assertGreaterEqual(
            height_diff, 2,
            f"Overlay height ({overlay_rect['height']:.1f}) should be at least 2px taller than text ({text_rect['height']:.1f})"
        )

    def test_overlay_position_accounts_for_padding(self):
        """
        Verify overlay is positioned slightly before the text start (due to padding).
        """
        text_rect = self._create_span_on_word("thrilled", "positive")

        segment = self._get_overlay_segment()
        overlay_rect = self.driver.execute_script(
            'return arguments[0].getBoundingClientRect();', segment
        )

        # With padding, overlay left should be <= text left
        self.assertLessEqual(
            overlay_rect['left'], text_rect['left'] + 1,  # 1px tolerance
            f"Overlay left ({overlay_rect['left']:.1f}) should be <= text left ({text_rect['left']:.1f})"
        )

    # ==================== BUG 3: DELETE NAVIGATION BUG ====================

    def test_delete_removes_overlay_completely(self):
        """
        BUG 3: Verify deleting a span removes the entire overlay, not just parts.
        """
        self._create_span_on_word("thrilled", "positive")

        # Verify overlay exists
        initial_count = self._count_overlays()
        self.assertGreater(initial_count, 0, "Expected at least one overlay after creation")

        # Click delete button
        delete_btn = self.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, '.span-delete-btn')
        ))
        delete_btn.click()
        time.sleep(0.1)  # Wait for delete to complete

        # Verify overlay is completely removed
        final_count = self._count_overlays()
        self.assertEqual(
            final_count, 0,
            f"Expected 0 overlays after delete, got {final_count}"
        )

        # Also verify no orphaned segments
        segment_count = self._count_overlay_segments()
        self.assertEqual(
            segment_count, 0,
            f"Expected 0 segments after delete, got {segment_count}"
        )

    def test_delete_after_navigation_removes_overlay(self):
        """
        BUG 3: Verify deleting a span after navigation removes the overlay completely.

        This is the specific bug where:
        1. Create span
        2. Navigate away
        3. Navigate back
        4. Delete span
        5. Overlay remains but label/button disappear
        """
        # Create span on first instance
        self._create_span_on_word("thrilled", "positive")
        time.sleep(0.1)

        # Verify overlay exists
        initial_count = self._count_overlays()
        self.assertGreater(initial_count, 0, "Expected overlay after creation")

        # Navigate to next instance
        next_btn = self.driver.find_element(By.ID, 'next-btn')
        next_btn.click()
        time.sleep(0.5)

        # Navigate back to first instance
        prev_btn = self.driver.find_element(By.ID, 'prev-btn')
        prev_btn.click()
        time.sleep(0.5)

        # Wait for overlay to be re-rendered
        self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-overlay-pure')
        ))

        # Verify label is still visible
        label = self.driver.find_element(By.CSS_SELECTOR, '.span-overlay-pure .span-label')
        self.assertTrue(label.is_displayed(), "Label should be visible after navigation")
        self.assertEqual(label.text, "positive", "Label text should be 'positive'")

        # Click delete button
        delete_btn = self.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, '.span-delete-btn')
        ))
        delete_btn.click()
        time.sleep(0.1)

        # Verify overlay is COMPLETELY removed (not just label/button)
        overlay_count = self._count_overlays()
        segment_count = self._count_overlay_segments()

        self.assertEqual(
            overlay_count, 0,
            f"Expected 0 overlays after delete, got {overlay_count}"
        )
        self.assertEqual(
            segment_count, 0,
            f"Expected 0 segments after delete, got {segment_count}"
        )

    def test_no_duplicate_overlays_after_navigation(self):
        """
        Verify navigation doesn't create duplicate overlays.
        """
        self._create_span_on_word("thrilled", "positive")
        time.sleep(0.1)

        initial_count = self._count_overlays()

        # Navigate away and back
        next_btn = self.driver.find_element(By.ID, 'next-btn')
        next_btn.click()
        time.sleep(0.5)

        prev_btn = self.driver.find_element(By.ID, 'prev-btn')
        prev_btn.click()
        time.sleep(0.5)

        # Wait for overlay
        self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-overlay-pure')
        ))

        final_count = self._count_overlays()

        self.assertEqual(
            initial_count, final_count,
            f"Expected {initial_count} overlay(s) after navigation, got {final_count} (duplicates?)"
        )

    def test_overlay_label_visible_after_navigation(self):
        """
        Verify the label remains visible after navigation (part of Bug 3).
        """
        self._create_span_on_word("thrilled", "positive")
        time.sleep(0.1)

        # Navigate away and back
        next_btn = self.driver.find_element(By.ID, 'next-btn')
        next_btn.click()
        time.sleep(0.5)

        prev_btn = self.driver.find_element(By.ID, 'prev-btn')
        prev_btn.click()
        time.sleep(0.5)

        # Wait for overlay
        self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-overlay-pure')
        ))

        # Check label visibility
        label = self.driver.find_element(By.CSS_SELECTOR, '.span-overlay-pure .span-label')

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

        self.assertNotEqual(visibility_info['display'], 'none', "Label has display: none")
        self.assertNotEqual(visibility_info['visibility'], 'hidden', "Label has visibility: hidden")
        self.assertGreater(float(visibility_info['opacity']), 0, "Label has opacity: 0")
        self.assertGreater(visibility_info['width'], 0, "Label has zero width")
        self.assertGreater(visibility_info['height'], 0, "Label has zero height")
        self.assertEqual(visibility_info['text'], "positive", "Label text incorrect")

    def test_delete_button_visible_after_navigation(self):
        """
        Verify the delete button remains visible after navigation (part of Bug 3).
        """
        self._create_span_on_word("thrilled", "positive")
        time.sleep(0.1)

        # Navigate away and back
        next_btn = self.driver.find_element(By.ID, 'next-btn')
        next_btn.click()
        time.sleep(0.5)

        prev_btn = self.driver.find_element(By.ID, 'prev-btn')
        prev_btn.click()
        time.sleep(0.5)

        # Wait for overlay
        self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-overlay-pure')
        ))

        # Check delete button exists and is clickable
        delete_btn = self.driver.find_element(By.CSS_SELECTOR, '.span-overlay-pure .span-delete-btn')

        visibility_info = self.driver.execute_script('''
            const btn = arguments[0];
            const style = window.getComputedStyle(btn);
            const rect = btn.getBoundingClientRect();
            return {
                display: style.display,
                visibility: style.visibility,
                opacity: style.opacity,
                width: rect.width,
                height: rect.height,
                pointerEvents: style.pointerEvents
            };
        ''', delete_btn)

        self.assertNotEqual(visibility_info['display'], 'none', "Delete button has display: none")
        self.assertNotEqual(visibility_info['visibility'], 'hidden', "Delete button has visibility: hidden")
        self.assertGreater(float(visibility_info['opacity']), 0, "Delete button has opacity: 0")
        self.assertGreater(visibility_info['width'], 0, "Delete button has zero width")
        self.assertGreater(visibility_info['height'], 0, "Delete button has zero height")
        self.assertNotEqual(visibility_info['pointerEvents'], 'none', "Delete button has pointer-events: none")


class TestSpanOverlayDefaultColors(unittest.TestCase):
    """
    Test span overlay colors when using the DEFAULT palette (no explicit colors defined).

    This tests the case where colors are auto-assigned from SPAN_COLOR_PALETTE:
    - Index 0: purple (110, 86, 207)
    - Index 1: red (239, 68, 68)
    """

    @classmethod
    def setUpClass(cls):
        """Set up Flask server and browser for tests."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "span_overlay_default_colors")
        os.makedirs(cls.test_dir, exist_ok=True)

        config_file, data_file = create_span_config_default_colors(cls.test_dir)
        cls.config_file = config_file

        cls.server = FlaskTestServer(debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

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

        timestamp = int(time.time())
        self.test_user = f"default_color_test_{timestamp}"
        self._login()
        self._navigate_to_annotation()

    def tearDown(self):
        """Close browser after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login(self):
        """Login a test user (no password required)."""
        self.driver.get(f"{self.server.base_url}/")
        self.wait.until(EC.presence_of_element_located((By.ID, "login-email")))

        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(self.test_user)

        login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()
        time.sleep(0.05)

        self.wait.until(EC.presence_of_element_located((By.ID, "task_layout")))

    def _navigate_to_annotation(self):
        """Navigate to the annotation page."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait.until(EC.presence_of_element_located((By.ID, 'text-content')))
        time.sleep(0.1)

    def _select_word_and_get_rect(self, word):
        """Select a word and return its bounding rect."""
        script = f'''
            const text = document.getElementById('text-content');
            const textContent = text.textContent || text.innerText;
            const wordIndex = textContent.indexOf("{word}");
            if (wordIndex === -1) return null;

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

    def test_first_label_uses_first_color_in_palette(self):
        """
        Verify that the first label (happy) gets the first color in the palette (purple).
        """
        # Enable console logging
        self.driver.execute_script('''
            window._consoleLogs = [];
            const originalLog = console.log;
            console.log = function(...args) {
                window._consoleLogs.push({type: 'log', msg: args.map(a => String(a)).join(' ')});
                originalLog.apply(console, args);
            };
        ''')

        # Click the first label (happy)
        happy_checkbox = self.driver.find_element(
            By.CSS_SELECTOR, '.shadcn-span-checkbox[value="happy"]'
        )
        happy_checkbox.click()
        time.sleep(0.1)

        # Check the color that's loaded for this label
        colors = self.driver.execute_script('''
            if (!window.spanManager) return { error: 'no spanManager' };
            return {
                colors: window.spanManager.colors,
                currentSchema: window.spanManager.currentSchema,
                selectedLabel: window.spanManager.selectedLabel
            };
        ''')
        print(f"[DEBUG] Colors for first label: {colors}")

        # Select text and create span
        selection_rect = self._select_word_and_get_rect("thrilled")
        self.assertIsNotNone(selection_rect, "Could not find word 'thrilled' in text")

        text_element = self.driver.find_element(By.ID, 'text-content')
        ActionChains(self.driver).move_to_element(text_element).release().perform()
        time.sleep(0.1)

        # Get the overlay color
        segment = self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-highlight-segment')
        ))
        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )
        print(f"[DEBUG] First label (happy) overlay color: {bg_color}")

        # Print console logs
        console_logs = self.driver.execute_script('return window._consoleLogs || [];')
        for log in console_logs:
            if 'SpanManager' in log.get('msg', ''):
                print(f"  [{log.get('type')}] {log.get('msg')}")

        # Verify it's purple-ish (first color in palette: 110, 86, 207)
        import re
        match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', bg_color)
        self.assertIsNotNone(match, f"Could not parse color: {bg_color}")

        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
        print(f"[DEBUG] Parsed RGB: R={r}, G={g}, B={b}")

        # Purple (110, 86, 207) has high blue component
        self.assertGreater(
            b, g,
            f"Expected blue > green for purple (first palette color). Got R={r}, G={g}, B={b}"
        )

    def test_second_label_uses_second_color_in_palette(self):
        """
        CRITICAL: Verify clicking ONLY the second label (sad) uses second palette color (red),
        NOT the first color (purple).

        Default palette:
        - Index 0: purple (110, 86, 207)
        - Index 1: red (239, 68, 68)
        """
        # Enable console logging
        self.driver.execute_script('''
            window._consoleLogs = [];
            const originalLog = console.log;
            console.log = function(...args) {
                window._consoleLogs.push({type: 'log', msg: args.map(a => String(a)).join(' ')});
                originalLog.apply(console, args);
            };
        ''')

        # Click ONLY the second label (sad) - never click the first
        sad_checkbox = self.driver.find_element(
            By.CSS_SELECTOR, '.shadcn-span-checkbox[value="sad"]'
        )
        sad_checkbox.click()
        time.sleep(0.1)

        # Check the color that's loaded for this label
        colors = self.driver.execute_script('''
            if (!window.spanManager) return { error: 'no spanManager' };
            return {
                colors: window.spanManager.colors,
                currentSchema: window.spanManager.currentSchema,
                selectedLabel: window.spanManager.selectedLabel
            };
        ''')
        print(f"[DEBUG] Colors for second label: {colors}")

        # Verify selectedLabel is 'sad'
        self.assertEqual(
            colors.get('selectedLabel'), 'sad',
            f"Expected selectedLabel='sad' but got {colors}"
        )

        # Select text and create span
        selection_rect = self._select_word_and_get_rect("thrilled")
        self.assertIsNotNone(selection_rect, "Could not find word 'thrilled' in text")

        text_element = self.driver.find_element(By.ID, 'text-content')
        ActionChains(self.driver).move_to_element(text_element).release().perform()
        time.sleep(0.1)

        # Get the overlay color
        segment = self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '.span-highlight-segment')
        ))
        bg_color = self.driver.execute_script(
            'return window.getComputedStyle(arguments[0]).backgroundColor;', segment
        )
        print(f"[DEBUG] Second label (sad) overlay color: {bg_color}")

        # Print console logs
        console_logs = self.driver.execute_script('return window._consoleLogs || [];')
        for log in console_logs:
            if 'SpanManager' in log.get('msg', ''):
                print(f"  [{log.get('type')}] {log.get('msg')}")

        # Verify it's red (second color in palette: 239, 68, 68)
        import re
        match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', bg_color)
        self.assertIsNotNone(match, f"Could not parse color: {bg_color}")

        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
        print(f"[DEBUG] Parsed RGB: R={r}, G={g}, B={b}")

        # Red (239, 68, 68) should have high red component
        # Should NOT be purple (110, 86, 207) which has high blue
        self.assertGreater(
            r, b,
            f"BUG! Expected RED (r > b) for second label but got BLUE-dominant. "
            f"R={r}, G={g}, B={b}. The first label's PURPLE color is being used instead of RED."
        )
        self.assertGreater(
            r, g,
            f"BUG! Expected RED (r > g) for second label. Got R={r}, G={g}, B={b}."
        )


if __name__ == '__main__':
    unittest.main()
