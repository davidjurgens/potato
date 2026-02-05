#!/usr/bin/env python3
"""
Selenium tests for multi-span annotation with instance_display.

Reproduces the bug where text selection in display fields does not trigger
span creation. Tests multiple root cause hypotheses:

1. Event listeners not attached to display fields
2. SpanManager not initialized with field strategies
3. Font metrics fail for elements inside initially-hidden #main-content
4. handleTextSelection() not being called on mouseup
5. createSpanFromSelection() using wrong canonical text
6. changeSpanLabel() only adding listeners to #instance-text
"""

import os
import sys
import time
import json
import yaml
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


def create_multi_span_config(test_dir):
    """Create a multi-span annotation config for testing."""
    os.makedirs(test_dir, exist_ok=True)
    os.makedirs(os.path.join(test_dir, "data"), exist_ok=True)
    os.makedirs(os.path.join(test_dir, "annotation_output"), exist_ok=True)

    data = [
        {
            "id": "test_001",
            "premise": "The cat sat on the mat while the dog slept nearby.",
            "hypothesis": "An animal was resting on a surface."
        },
        {
            "id": "test_002",
            "premise": "Scientists discovered a new species of frog.",
            "hypothesis": "Researchers found an unknown animal."
        }
    ]
    data_file = os.path.join(test_dir, "data", "test_data.json")
    with open(data_file, 'w') as f:
        json.dump(data, f)

    config = {
        "port": 8000,
        "server_name": "test annotator",
        "annotation_task_name": "Multi-Span Test",
        "task_dir": os.path.abspath(test_dir),
        "output_annotation_dir": os.path.join(os.path.abspath(test_dir), "annotation_output"),
        "output_annotation_format": "json",
        "annotation_codebook_url": "",
        "data_files": [os.path.join(os.path.abspath(test_dir), "data", "test_data.json")],
        "item_properties": {
            "id_key": "id",
            "text_key": "premise"
        },
        "user_config": {
            "allow_all_users": True,
            "users": []
        },
        "authentication": {"method": "in_memory"},
        "alert_time_each_instance": 10000000,
        "require_password": False,
        "persist_sessions": False,
        "debug": True,  # Enable debug for console log visibility
        "ui_debug": True,
        "secret_key": "test-secret-key",
        "session_lifetime_days": 1,
        "random_seed": 1234,
        "site_dir": "default",
        "instance_display": {
            "layout": {
                "direction": "vertical",
                "gap": "16px"
            },
            "fields": [
                {
                    "key": "premise",
                    "type": "text",
                    "label": "Premise",
                    "span_target": True
                },
                {
                    "key": "hypothesis",
                    "type": "text",
                    "label": "Hypothesis",
                    "span_target": True
                }
            ]
        },
        "annotation_schemes": [
            {
                "annotation_type": "span",
                "name": "alignment",
                "description": "Highlight aligned phrases",
                "labels": [
                    {"name": "MATCH", "tooltip": "Matching phrases"},
                    {"name": "MISMATCH", "tooltip": "Mismatched phrases"}
                ],
                "sequential_key_binding": True
            }
        ]
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


class TestMultiSpanAnnotation(unittest.TestCase):
    """
    Selenium test for multi-span annotation in instance_display mode.

    Reproduces the bug where selecting text in display fields does not
    create span annotations.
    """

    @classmethod
    def setUpClass(cls):
        """Set up Flask server and Chrome driver."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "multi_span_selenium_test")

        config_file = create_multi_span_config(cls.test_dir)
        port = find_free_port(preferred_port=9025)
        cls.server = FlaskTestServer(port=port, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        cls.server._wait_for_server_ready(timeout=10)

        from selenium.webdriver.chrome.options import Options
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server'):
            cls.server.stop_server()

    def setUp(self):
        """Create driver, register, and login."""
        self.driver = webdriver.Chrome(options=self.chrome_options)

        # Register user
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-content"))
        )

        try:
            # Try simple login (no-password mode)
            username_field = self.driver.find_element(By.ID, "login-email")
            username_field.clear()
            username_field.send_keys(f"testuser_{int(time.time())}")
            login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
            login_form.submit()
        except NoSuchElementException:
            pass

        # Wait for annotation interface
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Give JS time to fully initialize
        time.sleep(2)

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def get_console_logs(self):
        """Get browser console logs."""
        try:
            return self.driver.get_log("browser")
        except Exception:
            return []

    def js(self, script):
        """Execute JavaScript and return result."""
        return self.driver.execute_script(script)

    # ==================== ROOT CAUSE 1: DOM Structure ====================

    def test_display_fields_exist_in_dom(self):
        """Root cause check: display fields should exist after page load."""
        fields = self.driver.find_elements(
            By.CSS_SELECTOR, '.display-field[data-span-target="true"]'
        )
        self.assertGreaterEqual(len(fields), 2,
            f"Should have at least 2 span target fields, found {len(fields)}")

    def test_display_fields_are_visible(self):
        """Root cause check: display fields should be visible (not hidden)."""
        fields = self.driver.find_elements(
            By.CSS_SELECTOR, '.display-field[data-span-target="true"]'
        )
        for field in fields:
            self.assertTrue(field.is_displayed(),
                f"Display field {field.get_attribute('data-field-key')} should be visible")

    def test_text_content_elements_have_ids(self):
        """Root cause check: text content elements should have correct IDs."""
        premise_tc = self.driver.find_elements(By.ID, "text-content-premise")
        hypothesis_tc = self.driver.find_elements(By.ID, "text-content-hypothesis")

        self.assertEqual(len(premise_tc), 1,
            "Should have exactly 1 text-content-premise element")
        self.assertEqual(len(hypothesis_tc), 1,
            "Should have exactly 1 text-content-hypothesis element")

    def test_text_content_has_original_text_data_attr(self):
        """Root cause check: text content should have data-original-text."""
        premise_el = self.driver.find_element(By.ID, "text-content-premise")
        hyp_el = self.driver.find_element(By.ID, "text-content-hypothesis")

        premise_text = premise_el.get_attribute("data-original-text")
        hyp_text = hyp_el.get_attribute("data-original-text")

        self.assertIsNotNone(premise_text,
            "Premise text-content should have data-original-text")
        self.assertIsNotNone(hyp_text,
            "Hypothesis text-content should have data-original-text")
        self.assertTrue(len(premise_text) > 5,
            f"Premise data-original-text should have real content, got: '{premise_text}'")
        self.assertTrue(len(hyp_text) > 5,
            f"Hypothesis data-original-text should have real content, got: '{hyp_text}'")

    def test_text_content_visible_with_text(self):
        """Root cause check: text content elements should be visible with text."""
        premise_el = self.driver.find_element(By.ID, "text-content-premise")
        hyp_el = self.driver.find_element(By.ID, "text-content-hypothesis")

        self.assertTrue(premise_el.is_displayed(),
            "Premise text content should be visible")
        self.assertTrue(hyp_el.is_displayed(),
            "Hypothesis text content should be visible")
        self.assertTrue(len(premise_el.text) > 5,
            f"Premise should have visible text, got: '{premise_el.text}'")
        self.assertTrue(len(hyp_el.text) > 5,
            f"Hypothesis should have visible text, got: '{hyp_el.text}'")

    # ==================== ROOT CAUSE 2: SpanManager Initialization ====================

    def test_span_manager_exists(self):
        """Root cause check: window.spanManager should exist."""
        result = self.js("return !!window.spanManager")
        self.assertTrue(result, "window.spanManager should exist")

    def test_span_manager_is_initialized(self):
        """Root cause check: SpanManager should be initialized."""
        result = self.js("return window.spanManager && window.spanManager.isInitialized")
        self.assertTrue(result,
            "SpanManager should be initialized (isInitialized=true)")

    def test_span_manager_has_field_strategies(self):
        """Root cause check: SpanManager should have field strategies for both fields."""
        result = self.js("""
            if (!window.spanManager) return {error: 'no spanManager'};
            return {
                keys: Object.keys(window.spanManager.fieldStrategies),
                count: Object.keys(window.spanManager.fieldStrategies).length
            };
        """)
        self.assertNotIn("error", result or {},
            f"SpanManager should exist: {result}")
        self.assertIn("premise", result["keys"],
            f"Should have 'premise' field strategy, got: {result['keys']}")
        self.assertIn("hypothesis", result["keys"],
            f"Should have 'hypothesis' field strategy, got: {result['keys']}")

    def test_field_strategies_are_initialized(self):
        """Root cause check: each field strategy should be initialized."""
        result = self.js("""
            if (!window.spanManager) return {error: 'no spanManager'};
            var strats = window.spanManager.fieldStrategies;
            var result = {};
            for (var key in strats) {
                result[key] = {
                    isInitialized: strats[key].isInitialized,
                    hasCanonicalText: !!strats[key].canonicalText,
                    canonicalTextPreview: (strats[key].canonicalText || '').substring(0, 40),
                    hasFontMetrics: !!strats[key].fontMetrics,
                    containerExists: !!strats[key].container,
                    containerId: strats[key].container ? strats[key].container.id : null
                };
            }
            return result;
        """)
        self.assertNotIn("error", result or {})

        for field_key in ["premise", "hypothesis"]:
            self.assertIn(field_key, result,
                f"Should have strategy for '{field_key}'")
            field_info = result[field_key]
            self.assertTrue(field_info["isInitialized"],
                f"Strategy for '{field_key}' should be initialized: {field_info}")
            self.assertTrue(field_info["hasCanonicalText"],
                f"Strategy for '{field_key}' should have canonical text: {field_info}")
            self.assertTrue(len(field_info["canonicalTextPreview"]) > 5,
                f"Strategy for '{field_key}' should have real canonical text, got: '{field_info['canonicalTextPreview']}'")
            self.assertTrue(field_info["hasFontMetrics"],
                f"Strategy for '{field_key}' should have font metrics: {field_info}")

    def test_font_metrics_are_valid(self):
        """Root cause check: font metrics should have non-zero values (not from hidden elements)."""
        result = self.js("""
            if (!window.spanManager) return {error: 'no spanManager'};
            var strats = window.spanManager.fieldStrategies;
            var result = {};
            for (var key in strats) {
                var fm = strats[key].fontMetrics;
                result[key] = fm ? {
                    fontSize: fm.fontSize,
                    lineHeight: fm.lineHeight,
                    averageCharWidth: fm.averageCharWidth
                } : null;
            }
            return result;
        """)
        for field_key in ["premise", "hypothesis"]:
            fm = result.get(field_key)
            self.assertIsNotNone(fm,
                f"Font metrics should exist for '{field_key}'")
            self.assertGreater(fm["fontSize"], 0,
                f"Font size for '{field_key}' should be > 0 (not from hidden element), got: {fm['fontSize']}")
            self.assertGreater(fm["lineHeight"], 0,
                f"Line height for '{field_key}' should be > 0, got: {fm['lineHeight']}")
            self.assertGreater(fm["averageCharWidth"], 0,
                f"Average char width for '{field_key}' should be > 0, got: {fm['averageCharWidth']}")

    # ==================== ROOT CAUSE 3: Event Listeners ====================

    def test_event_listeners_on_display_fields(self):
        """Root cause check: mouseup event listeners should be on display fields.

        We can't directly check event listeners, but we can test if dispatching
        a mouseup event triggers handleTextSelection by checking if an internal
        flag or console log is produced.
        """
        # First, select a label so the span manager is ready
        self.js("""
            if (window.spanManager && window.spanManager.isInitialized) {
                window.spanManager.selectLabel('MATCH', 'alignment', 'premise');
            }
        """)

        # Dispatch a mouseup event on the premise field and check if
        # handleTextSelection was called
        result = self.js("""
            var called = false;
            var origHandler = window.spanManager.handleTextSelection.bind(window.spanManager);
            window.spanManager.handleTextSelection = function() {
                called = true;
                return origHandler.apply(this, arguments);
            };

            // Dispatch mouseup on the display field
            var field = document.querySelector('.display-field[data-field-key="premise"]');
            if (!field) return {error: 'premise field not found'};

            var event = new MouseEvent('mouseup', {bubbles: true});
            field.dispatchEvent(event);

            // Restore original handler
            window.spanManager.handleTextSelection = origHandler;

            return {called: called, fieldFound: !!field};
        """)
        self.assertNotIn("error", result or {},
            f"Should find premise field: {result}")
        self.assertTrue(result["called"],
            "handleTextSelection should be called when mouseup fires on display field")

    def test_event_listeners_on_hypothesis_field(self):
        """Root cause check: mouseup event should also fire on hypothesis field."""
        self.js("""
            if (window.spanManager && window.spanManager.isInitialized) {
                window.spanManager.selectLabel('MATCH', 'alignment', 'hypothesis');
            }
        """)

        result = self.js("""
            var called = false;
            var origHandler = window.spanManager.handleTextSelection.bind(window.spanManager);
            window.spanManager.handleTextSelection = function() {
                called = true;
                return origHandler.apply(this, arguments);
            };

            var field = document.querySelector('.display-field[data-field-key="hypothesis"]');
            if (!field) return {error: 'hypothesis field not found'};

            var event = new MouseEvent('mouseup', {bubbles: true});
            field.dispatchEvent(event);

            window.spanManager.handleTextSelection = origHandler;

            return {called: called};
        """)
        self.assertTrue(result.get("called", False),
            "handleTextSelection should be called when mouseup fires on hypothesis field")

    # ==================== ROOT CAUSE 4: Canonical Text ====================

    def test_canonical_text_is_not_instance_id(self):
        """Root cause check: canonical text should be the actual text, not the ID."""
        result = self.js("""
            if (!window.spanManager) return {error: 'no spanManager'};
            var strats = window.spanManager.fieldStrategies;
            var result = {};
            for (var key in strats) {
                result[key] = strats[key].canonicalText;
            }
            return result;
        """)

        # Canonical text should not be the instance ID
        for field_key in ["premise", "hypothesis"]:
            text = result.get(field_key, "")
            self.assertFalse(text.startswith("test_"),
                f"Canonical text for '{field_key}' should not be the instance ID, got: '{text}'")
            self.assertTrue(len(text) > 10,
                f"Canonical text for '{field_key}' should be real text, got: '{text}'")

    # ==================== ROOT CAUSE 5: Text Selection Flow ====================

    def test_text_selection_in_premise_creates_span(self):
        """E2E: selecting text in premise with a label selected should create a span."""
        # Select the MATCH label
        self.js("""
            window.spanManager.selectLabel('MATCH', 'alignment', 'premise');
        """)

        # Simulate text selection in premise
        premise_el = self.driver.find_element(By.ID, "text-content-premise")

        # Use JavaScript to create a text selection
        result = self.js("""
            var el = document.getElementById('text-content-premise');
            if (!el) return {error: 'element not found'};

            // Create a selection of "The cat"
            var textNode = el.firstChild;
            while (textNode && textNode.nodeType !== 3) {
                textNode = textNode.firstChild || textNode.nextSibling;
            }
            if (!textNode) return {error: 'no text node found'};

            var range = document.createRange();
            range.setStart(textNode, 0);
            range.setEnd(textNode, Math.min(7, textNode.textContent.length));

            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);

            return {
                selectedText: sel.toString(),
                rangeCount: sel.rangeCount,
                isCollapsed: sel.isCollapsed
            };
        """)

        self.assertNotIn("error", result or {},
            f"Should be able to select text: {result}")
        self.assertTrue(len(result.get("selectedText", "")) > 0,
            f"Should have selected text, got: {result}")

        # Now trigger handleTextSelection
        spans_before = self.js("""
            return (window.spanManager.annotations && window.spanManager.annotations.spans)
                ? window.spanManager.annotations.spans.length : 0;
        """)

        # Call handleTextSelection directly (simulates mouseup event)
        handle_result = self.js("""
            try {
                window.spanManager.handleTextSelection();
                return {
                    success: true,
                    spansAfter: window.spanManager.annotations ?
                        (window.spanManager.annotations.spans || []).length : 0
                };
            } catch(e) {
                return {error: e.message, stack: e.stack};
            }
        """)

        self.assertNotIn("error", handle_result or {},
            f"handleTextSelection should not throw: {handle_result}")

        # Wait for async save
        time.sleep(1)

        # Check if span was added
        spans_after = self.js("""
            return (window.spanManager.annotations && window.spanManager.annotations.spans)
                ? window.spanManager.annotations.spans.length : 0;
        """)

        self.assertGreater(spans_after, spans_before,
            f"Span count should increase after selection. Before: {spans_before}, After: {spans_after}")

    def test_text_selection_in_hypothesis_creates_span(self):
        """E2E: selecting text in hypothesis should create a span with correct target_field."""
        # Select the MISMATCH label targeting hypothesis
        self.js("""
            window.spanManager.selectLabel('MISMATCH', 'alignment', 'hypothesis');
        """)

        # Create text selection in hypothesis
        result = self.js("""
            var el = document.getElementById('text-content-hypothesis');
            if (!el) return {error: 'element not found'};

            var textNode = el.firstChild;
            while (textNode && textNode.nodeType !== 3) {
                textNode = textNode.firstChild || textNode.nextSibling;
            }
            if (!textNode) return {error: 'no text node found'};

            var range = document.createRange();
            range.setStart(textNode, 0);
            range.setEnd(textNode, Math.min(9, textNode.textContent.length));

            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);

            return {selectedText: sel.toString()};
        """)

        self.assertNotIn("error", result or {},
            f"Should be able to select text in hypothesis: {result}")

        # Call handleTextSelection
        handle_result = self.js("""
            try {
                window.spanManager.handleTextSelection();
                return {success: true};
            } catch(e) {
                return {error: e.message};
            }
        """)

        self.assertNotIn("error", handle_result or {},
            f"handleTextSelection should not throw for hypothesis: {handle_result}")

        # Wait for async save
        time.sleep(1)

        # Check target_field on the created span
        result = self.js("""
            var spans = (window.spanManager.annotations && window.spanManager.annotations.spans) || [];
            var hypSpans = spans.filter(function(s) { return s.target_field === 'hypothesis'; });
            return {
                totalSpans: spans.length,
                hypothesisSpans: hypSpans.length,
                allTargetFields: spans.map(function(s) { return s.target_field || 'NONE'; })
            };
        """)

        self.assertGreater(result.get("hypothesisSpans", 0), 0,
            f"Should have at least 1 span with target_field='hypothesis': {result}")

    # ==================== ROOT CAUSE 6: Span Overlay Containers ====================

    def test_span_overlay_containers_created(self):
        """Root cause check: per-field span overlay containers should exist."""
        result = self.js("""
            return {
                premiseOverlays: !!document.getElementById('span-overlays-premise'),
                hypothesisOverlays: !!document.getElementById('span-overlays-hypothesis'),
                legacyOverlays: !!document.getElementById('span-overlays')
            };
        """)

        self.assertTrue(result["premiseOverlays"],
            "Should have span-overlays-premise container")
        self.assertTrue(result["hypothesisOverlays"],
            "Should have span-overlays-hypothesis container")

    # ==================== ROOT CAUSE 7: changeSpanLabel Integration ====================

    def test_change_span_label_selects_label_in_manager(self):
        """Root cause check: changeSpanLabel should set label in SpanManager."""
        # Find a span label checkbox
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="checkbox"][name*="span_label"]'
        )

        self.assertGreater(len(checkboxes), 0,
            "Should have span label checkboxes on the page")

        # Click the first checkbox
        checkboxes[0].click()
        time.sleep(0.5)

        # Verify the label was set in SpanManager
        result = self.js("""
            return {
                selectedLabel: window.spanManager ? window.spanManager.selectedLabel : null,
                currentSchema: window.spanManager ? window.spanManager.currentSchema : null,
                selectedTargetField: window.spanManager ? window.spanManager.selectedTargetField : null
            };
        """)

        self.assertIsNotNone(result.get("selectedLabel"),
            f"SpanManager should have a selected label after checkbox click: {result}")
        self.assertIsNotNone(result.get("currentSchema"),
            f"SpanManager should have a current schema after checkbox click: {result}")

    # ==================== ROOT CAUSE 8: Full Integration ====================

    def test_checkbox_click_then_text_select_premise(self):
        """Full integration: click label checkbox, select text in premise."""
        # Click the MATCH checkbox
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="checkbox"][name*="span_label"]'
        )
        if checkboxes:
            checkboxes[0].click()
            time.sleep(0.5)

        # Select text in premise using ActionChains
        premise_el = self.driver.find_element(By.ID, "text-content-premise")
        actions = ActionChains(self.driver)
        actions.move_to_element(premise_el)
        actions.click_and_hold()
        actions.move_by_offset(100, 0)
        actions.release()
        actions.perform()

        # Wait for span creation
        time.sleep(2)

        # Check for overlays
        overlays = self.js("""
            var container = document.getElementById('span-overlays-premise');
            if (!container) return {error: 'no overlay container',
                                    allOverlayContainers: document.querySelectorAll('[id^="span-overlays"]').length};
            return {
                overlayCount: container.querySelectorAll('.span-overlay-pure').length,
                containerExists: true
            };
        """)

        # This is the key assertion - if this fails, the bug is reproduced
        if overlays.get("error"):
            self.fail(f"Overlay container issue: {overlays}")

    def test_checkbox_click_then_text_select_hypothesis(self):
        """Full integration: click label checkbox, select text in hypothesis."""
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="checkbox"][name*="span_label"]'
        )
        if checkboxes:
            checkboxes[0].click()
            time.sleep(0.5)

        # Select text in hypothesis
        hyp_el = self.driver.find_element(By.ID, "text-content-hypothesis")
        actions = ActionChains(self.driver)
        actions.move_to_element(hyp_el)
        actions.click_and_hold()
        actions.move_by_offset(80, 0)
        actions.release()
        actions.perform()

        time.sleep(2)

        overlays = self.js("""
            var container = document.getElementById('span-overlays-hypothesis');
            if (!container) return {error: 'no overlay container'};
            return {
                overlayCount: container.querySelectorAll('.span-overlay-pure').length,
                containerExists: true
            };
        """)

        if overlays.get("error"):
            self.fail(f"Overlay container issue for hypothesis: {overlays}")

    # ==================== ROOT CAUSE 9: Sequential Field Usage ====================

    def test_premise_then_hypothesis_sequential(self):
        """Reproduce exact user bug: create span in premise, then try hypothesis.

        The user reported premise works but hypothesis doesn't. This test
        creates a span in premise first, then tries hypothesis to check
        if the first span creation somehow blocks the second.
        """
        # Step 1: Click the MATCH checkbox
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="checkbox"][name*="span_label"]'
        )
        self.assertGreater(len(checkboxes), 0, "Should have checkboxes")
        checkboxes[0].click()
        time.sleep(0.5)

        # Step 2: Create span in PREMISE via JS (simulating text selection)
        result = self.js("""
            window.spanManager.selectLabel('MATCH', 'alignment', 'premise');

            var el = document.getElementById('text-content-premise');
            var textNode = el.firstChild;
            while (textNode && textNode.nodeType !== 3) textNode = textNode.firstChild || textNode.nextSibling;

            var range = document.createRange();
            range.setStart(textNode, 0);
            range.setEnd(textNode, 7);  // "The cat"

            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);

            window.spanManager.handleTextSelection();

            return {
                premiseSpans: (window.spanManager.annotations.spans || []).filter(
                    function(s) { return s.target_field === 'premise'; }
                ).length,
                selectedLabel: window.spanManager.selectedLabel,
                currentSchema: window.spanManager.currentSchema
            };
        """)

        self.assertGreater(result.get("premiseSpans", 0), 0,
            f"Should have created premise span: {result}")

        # Step 3: Wait for async save
        time.sleep(1)

        # Step 4: Now try HYPOTHESIS - this is where the user's bug occurs
        result2 = self.js("""
            // Verify label is still selected
            var labelBefore = window.spanManager.selectedLabel;
            var schemaBefore = window.spanManager.currentSchema;

            var el = document.getElementById('text-content-hypothesis');
            if (!el) return {error: 'hypothesis element not found'};

            var textNode = el.firstChild;
            while (textNode && textNode.nodeType !== 3) textNode = textNode.firstChild || textNode.nextSibling;
            if (!textNode) return {error: 'no text node in hypothesis'};

            var range = document.createRange();
            range.setStart(textNode, 0);
            range.setEnd(textNode, 9);  // "An animal"

            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);

            var selectedText = sel.toString();

            // Check strategy state
            var strat = window.spanManager.fieldStrategies['hypothesis'];
            var stratInfo = strat ? {
                isInitialized: strat.isInitialized,
                containerId: strat.container ? strat.container.id : null,
                canonicalTextPreview: (strat.canonicalText || '').substring(0, 40)
            } : null;

            // Call handleTextSelection
            window.spanManager.handleTextSelection();

            var hypSpans = (window.spanManager.annotations.spans || []).filter(
                function(s) { return s.target_field === 'hypothesis'; }
            );

            // Check overlay container
            var overlayContainer = document.getElementById('span-overlays-hypothesis');
            var overlayCount = overlayContainer ?
                overlayContainer.querySelectorAll('.span-overlay-pure').length : -1;

            return {
                labelBefore: labelBefore,
                schemaBefore: schemaBefore,
                selectedText: selectedText,
                strategyInfo: stratInfo,
                hypothesisSpanCount: hypSpans.length,
                overlayCount: overlayCount,
                totalSpans: (window.spanManager.annotations.spans || []).length,
                allFields: (window.spanManager.annotations.spans || []).map(
                    function(s) { return s.target_field; }
                )
            };
        """)

        self.assertNotIn("error", result2 or {},
            f"Hypothesis flow should not error: {result2}")

        # The key assertion: hypothesis span should be created
        self.assertGreater(result2.get("hypothesisSpanCount", 0), 0,
            f"Should have created hypothesis span after premise. Full state: {json.dumps(result2, indent=2)}")

        # Verify overlay was also created in the DOM
        self.assertGreater(result2.get("overlayCount", 0), 0,
            f"Should have overlay in hypothesis container. Full state: {json.dumps(result2, indent=2)}")

    def test_hypothesis_overlay_persists_after_save(self):
        """Verify hypothesis overlay survives the save+reload cycle.

        This reproduces the exact bug: overlay appears briefly then vanishes
        because saveSpan() calls loadAnnotations() which re-renders from
        server data. If the API returns wrong text for the field, the
        overlay is lost during re-render.
        """
        # Create span in hypothesis
        self.js("""
            window.spanManager.selectLabel('MATCH', 'alignment', 'hypothesis');
        """)

        result = self.js("""
            var el = document.getElementById('text-content-hypothesis');
            var textNode = el.firstChild;
            while (textNode && textNode.nodeType !== 3) textNode = textNode.firstChild || textNode.nextSibling;

            var range = document.createRange();
            range.setStart(textNode, 3);
            range.setEnd(textNode, 9);  // "animal"

            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);

            window.spanManager.handleTextSelection();

            // Count overlays immediately (before async save completes)
            var container = document.getElementById('span-overlays-hypothesis');
            return {
                immediateOverlays: container ? container.querySelectorAll('.span-overlay-pure').length : 0
            };
        """)

        self.assertGreater(result.get("immediateOverlays", 0), 0,
            "Overlay should appear immediately after creation")

        # Wait for async saveSpan() + loadAnnotations() to complete
        time.sleep(3)

        # Check overlays AFTER the save+reload cycle
        result2 = self.js("""
            var container = document.getElementById('span-overlays-hypothesis');
            return {
                overlaysAfterSave: container ? container.querySelectorAll('.span-overlay-pure').length : 0,
                spanCount: (window.spanManager.annotations.spans || []).length,
                hypSpans: (window.spanManager.annotations.spans || []).filter(
                    function(s) { return s.target_field === 'hypothesis'; }
                ).length
            };
        """)

        self.assertGreater(result2.get("overlaysAfterSave", 0), 0,
            f"Overlay should PERSIST after save+reload cycle. State: {result2}")

    def test_label_positioning_has_padding(self):
        """Verify that span target text containers have padding-top for labels."""
        result = self.js("""
            var containers = document.querySelectorAll('.text-display-content.span-target-text');
            var results = [];
            containers.forEach(function(c) {
                var style = window.getComputedStyle(c);
                results.push({
                    paddingTop: style.paddingTop,
                    position: style.position,
                    paddingTopPx: parseFloat(style.paddingTop)
                });
            });
            return results;
        """)

        self.assertGreater(len(result), 0,
            "Should have span target text containers")
        for i, container in enumerate(result):
            self.assertGreaterEqual(container["paddingTopPx"], 20,
                f"Container {i} should have at least 20px padding-top for labels, got: {container['paddingTop']}")

    # ==================== Diagnostic Helpers ====================

    def test_collect_all_diagnostics(self):
        """Collects comprehensive diagnostic information for debugging.

        This test always passes but prints detailed state that helps
        identify the root cause.
        """
        diag = self.js("""
            var result = {};

            // SpanManager state
            result.spanManager = {
                exists: !!window.spanManager,
                isInitialized: window.spanManager ? window.spanManager.isInitialized : false,
                selectedLabel: window.spanManager ? window.spanManager.selectedLabel : null,
                currentSchema: window.spanManager ? window.spanManager.currentSchema : null,
                selectedTargetField: window.spanManager ? window.spanManager.selectedTargetField : null,
                fieldStrategyKeys: window.spanManager ? Object.keys(window.spanManager.fieldStrategies) : [],
                currentInstanceId: window.spanManager ? window.spanManager.currentInstanceId : null
            };

            // DOM state
            result.dom = {
                mainContentVisible: document.getElementById('main-content') ?
                    document.getElementById('main-content').style.display !== 'none' : false,
                instanceTextVisible: document.getElementById('instance-text') ?
                    document.getElementById('instance-text').style.display !== 'none' : false,
                displayFieldCount: document.querySelectorAll('.display-field[data-span-target="true"]').length,
                textContentPremise: !!document.getElementById('text-content-premise'),
                textContentHypothesis: !!document.getElementById('text-content-hypothesis'),
                spanOverlaysPremise: !!document.getElementById('span-overlays-premise'),
                spanOverlaysHypothesis: !!document.getElementById('span-overlays-hypothesis'),
                legacySpanOverlays: !!document.getElementById('span-overlays'),
                instanceDisplayContainer: !!document.querySelector('.instance-display-container')
            };

            // Instance display manager
            result.instanceDisplayManager = {
                exists: !!window.instanceDisplayManager,
                spanTargets: window.instanceDisplayManager ?
                    window.instanceDisplayManager.getSpanTargets() : [],
                isMultiSpanMode: window.instanceDisplayManager ?
                    window.instanceDisplayManager.isMultiSpanMode() : false
            };

            // Positioning strategy diagnostics
            if (window.spanManager && window.spanManager.fieldStrategies) {
                result.strategies = {};
                for (var key in window.spanManager.fieldStrategies) {
                    var s = window.spanManager.fieldStrategies[key];
                    result.strategies[key] = {
                        isInitialized: s.isInitialized,
                        canonicalTextLength: s.canonicalText ? s.canonicalText.length : 0,
                        canonicalTextPreview: s.canonicalText ? s.canonicalText.substring(0, 50) : null,
                        fontSize: s.fontMetrics ? s.fontMetrics.fontSize : 0,
                        lineHeight: s.fontMetrics ? s.fontMetrics.lineHeight : 0,
                        containerId: s.container ? s.container.id : null,
                        containerVisible: s.container ? s.container.offsetHeight > 0 : false
                    };
                }
            }

            // Check for span checkboxes
            var checkboxes = document.querySelectorAll('input[type="checkbox"][name*="span_label"]');
            result.checkboxes = {
                count: checkboxes.length,
                details: Array.from(checkboxes).map(function(cb) {
                    return {
                        id: cb.id,
                        name: cb.name,
                        checked: cb.checked,
                        hasTargetField: cb.hasAttribute('data-target-field'),
                        targetField: cb.getAttribute('data-target-field'),
                        hasOnclick: !!cb.getAttribute('onclick')
                    };
                })
            };

            return result;
        """)

        # Print diagnostics for debugging
        print("\n=== MULTI-SPAN DIAGNOSTIC REPORT ===")
        print(json.dumps(diag, indent=2))
        print("=== END DIAGNOSTIC REPORT ===\n")

        # Also capture browser console logs
        logs = self.get_console_logs()
        if logs:
            print("\n=== BROWSER CONSOLE LOGS ===")
            for log in logs[-30:]:  # Last 30 entries
                print(f"[{log.get('level', '?')}] {log.get('message', '')}")
            print("=== END CONSOLE LOGS ===\n")


if __name__ == "__main__":
    unittest.main()
