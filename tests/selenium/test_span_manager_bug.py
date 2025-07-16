#!/usr/bin/env python3
"""
Test to reproduce the span manager bug where currentInstanceId is not set.
This test should fail initially, then pass after the fix is applied.
"""

import time
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest


class TestSpanManagerBug(BaseSeleniumTest):
    """
    Test to reproduce the span manager bug where currentInstanceId is not set.

    The bug occurs when:
    1. User loads the annotation page
    2. SpanManager is initialized but currentInstanceId is null
    3. User tries to create a span annotation
    4. createAnnotation() fails with "No instance loaded" error
    """

    def test_span_manager_current_instance_id_bug(self):
        """
        Test that reproduces the bug where SpanManager.currentInstanceId is not set,
        causing span creation to fail with "No instance loaded" error.
        """
        print("\n" + "="*80)
        print("🐛 TESTING SPAN MANAGER BUG: currentInstanceId not set")
        print("="*80)

        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        # Wait for span manager to be ready
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        print(f"🔧 SpanManager ready: {span_manager_ready}")

        if not span_manager_ready:
            pytest.skip("SpanManager not ready")

        # Check if currentInstance is available
        current_instance_available = self.execute_script_safe("""
            return window.currentInstance !== null && window.currentInstance !== undefined;
        """)
        print(f"🔧 Current instance available: {current_instance_available}")

        # Check current instance ID
        current_instance_id = self.execute_script_safe("""
            return window.currentInstance ? window.currentInstance.id : null;
        """)
        print(f"🔧 Current instance ID: {current_instance_id}")

        # Check SpanManager's currentInstanceId
        span_manager_instance_id = self.execute_script_safe("""
            return window.spanManager ? window.spanManager.currentInstanceId : null;
        """)
        print(f"🔧 SpanManager currentInstanceId: {span_manager_instance_id}")

        # This is the bug: SpanManager.currentInstanceId should be set to the current instance ID
        # but it's not being set, so it remains null
        self.assertIsNotNone(current_instance_id, "Current instance ID should be available")
        self.assertIsNone(span_manager_instance_id, "SpanManager.currentInstanceId should be null (this is the bug)")

        # Try to create a span annotation - this should fail with "No instance loaded"
        # First, select a label
        label_selected = self.execute_script_safe("""
            if (window.spanManager) {
                window.spanManager.selectLabel('happy');
                return true;
            }
            return false;
        """)
        print(f"🔧 Label selected: {label_selected}")

        # Now try to create a span annotation
        create_result = self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.createAnnotation('test text', 0, 9, 'happy');
            }
            return null;
        """)
        print(f"🔧 Create annotation result: {create_result}")

        # The createAnnotation should fail because currentInstanceId is null
        # We expect it to return a rejected promise with "No instance loaded" error
        self.assertIsNotNone(create_result, "Create annotation should return a result")

        # Check if the error message contains "No instance loaded"
        error_message = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.currentInstanceId === null) {
                return "No instance loaded";
            }
            return "Instance loaded";
        """)
        print(f"🔧 Expected error message: {error_message}")

        # This test should fail initially because the bug exists
        # After the fix, SpanManager.currentInstanceId should be set to the current instance ID
        # and createAnnotation should work properly
        self.assertEqual(error_message, "No instance loaded",
                        "This test should fail initially due to the bug. "
                        "After the fix, SpanManager.currentInstanceId should be set and this should pass.")

        print("✅ Test completed - this should fail initially, then pass after the fix")

    def test_span_label_selector_visible(self):
        """
        Test that the span label selector and label buttons are visible after page load.
        """
        print("\n" + "="*80)
        print("🧪 TESTING SPAN LABEL SELECTOR VISIBILITY")
        print("="*80)

        # User is already authenticated by BaseSeleniumTest.setUp()
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        # Wait for main content to be visible
        main_content_visible = self.driver.find_element(By.ID, "main-content").is_displayed()
        self.assertTrue(main_content_visible, "Main content should be visible")

        # Check if span label selector is visible
        label_selector = self.driver.find_element(By.ID, "span-label-selector")
        self.assertTrue(label_selector.is_displayed(), "Span label selector should be visible")

        # Check if label buttons are present and visible
        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, "#label-buttons button")
        self.assertGreater(len(label_buttons), 0, "There should be at least one label button")
        for btn in label_buttons:
            self.assertTrue(btn.is_displayed(), f"Label button '{btn.text}' should be visible")

        print(f"✅ Found {len(label_buttons)} label buttons, all visible.")

    def test_span_label_selector_debug_output(self):
        """
        Test to capture JavaScript console logs and debug output to understand why
        setupSpanLabelSelector is not working.
        """
        print("\n" + "="*80)
        print("🔍 DEBUGGING SPAN LABEL SELECTOR SETUP")
        print("="*80)

        # User is already authenticated by BaseSeleniumTest.setUp()
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(3)  # Wait for all JavaScript to load

        # Get JavaScript console logs
        console_logs = self.driver.get_log('browser')
        print(f"\n📋 Console logs ({len(console_logs)} entries):")
        for log in console_logs:
            if '[DEBUG]' in log['message'] or 'annotation_scheme' in log['message']:
                print(f"  {log['level']}: {log['message']}")

        # Execute JavaScript to get debug information
        debug_info = self.driver.execute_script("""
            return {
                currentInstance: window.currentInstance ? {
                    id: window.currentInstance.id,
                    annotation_scheme: window.currentInstance.annotation_scheme,
                    hasAnnotationScheme: !!window.currentInstance.annotation_scheme
                } : null,
                spanManager: window.spanManager ? {
                    currentInstanceId: window.spanManager.currentInstanceId,
                    colors: window.spanManager.colors,
                    annotations: window.spanManager.annotations
                } : null,
                labelSelector: document.getElementById('span-label-selector') ? {
                    visible: document.getElementById('span-label-selector').style.display !== 'none',
                    display: document.getElementById('span-label-selector').style.display
                } : null,
                labelButtons: document.getElementById('label-buttons') ? {
                    visible: document.getElementById('label-buttons').style.display !== 'none',
                    display: document.getElementById('label-buttons').style.display,
                    children: document.getElementById('label-buttons').children.length
                } : null,
                hasSpanAnnotations: typeof checkForSpanAnnotations === 'function' ? checkForSpanAnnotations() : 'function not found',
                getSpanLabelsFromScheme: typeof getSpanLabelsFromScheme === 'function' ? getSpanLabelsFromScheme() : 'function not found'
            };
        """)

        print(f"\n🔧 Debug Info:")
        print(f"  Current Instance: {debug_info['currentInstance']}")
        print(f"  SpanManager: {debug_info['spanManager']}")
        print(f"  Label Selector: {debug_info['labelSelector']}")
        print(f"  Label Buttons: {debug_info['labelButtons']}")
        print(f"  Has Span Annotations: {debug_info['hasSpanAnnotations']}")
        print(f"  Span Labels from Scheme: {debug_info['getSpanLabelsFromScheme']}")

        # Check if setupSpanLabelSelector was called
        setup_called = self.driver.execute_script("""
            // Check if setupSpanLabelSelector exists and was called
            if (typeof setupSpanLabelSelector === 'function') {
                console.log('[DEBUG] setupSpanLabelSelector function exists');
                return true;
            } else {
                console.log('[DEBUG] setupSpanLabelSelector function not found');
                return false;
            }
        """)
        print(f"  SetupSpanLabelSelector function exists: {setup_called}")

        # This test should fail to show us the debug output
        self.fail("Debug test - check output above to understand why span label selector is not visible")

    def test_comprehensive_span_debug(self):
        """
        Comprehensive debug test to capture all JavaScript console logs, network requests,
        and DOM state to understand why the span label selector is not appearing.
        """
        print("\n" + "="*80)
        print("🔍 COMPREHENSIVE SPAN DEBUG TEST")
        print("="*80)

        # User is already authenticated by BaseSeleniumTest.setUp()
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(5)  # Wait for all JavaScript to load and execute

        # Get JavaScript console logs
        console_logs = self.driver.get_log('browser')
        print(f"\n📋 Console logs ({len(console_logs)} entries):")
        for log in console_logs:
            print(f"  {log['level']}: {log['message']}")

        # Execute JavaScript to get detailed debug info
        debug_info = self.driver.execute_script("""
            const debug = {};

            // Check current instance
            debug.currentInstance = window.currentInstance;
            debug.currentInstanceKeys = window.currentInstance ? Object.keys(window.currentInstance) : [];

            // Check span manager
            debug.spanManager = window.spanManager;
            debug.spanManagerCurrentInstanceId = window.spanManager ? window.spanManager.currentInstanceId : null;

            // Check annotation scheme
            debug.annotationScheme = window.currentInstance ? window.currentInstance.annotation_scheme : null;
            debug.annotationSchemeType = typeof debug.annotationScheme;
            debug.annotationSchemeLength = Array.isArray(debug.annotationScheme) ? debug.annotationScheme.length : 'N/A';

            // Check span labels
            debug.spanLabels = [];
            if (window.currentInstance && window.currentInstance.annotation_scheme) {
                const schemes = window.currentInstance.annotation_scheme;
                if (Array.isArray(schemes)) {
                    const spanScheme = schemes.find(s => s.annotation_type === 'span');
                    debug.spanLabels = spanScheme ? spanScheme.labels : [];
                }
            }

            // Check DOM elements
            const labelSelector = document.getElementById('span-label-selector');
            const labelButtons = document.getElementById('label-buttons');

            debug.labelSelector = {
                exists: !!labelSelector,
                display: labelSelector ? labelSelector.style.display : 'N/A',
                visible: labelSelector ? labelSelector.offsetParent !== null : false,
                innerHTML: labelSelector ? labelSelector.innerHTML.substring(0, 200) : 'N/A'
            };

            debug.labelButtons = {
                exists: !!labelButtons,
                display: labelButtons ? labelButtons.style.display : 'N/A',
                visible: labelButtons ? labelButtons.offsetParent !== null : false,
                children: labelButtons ? labelButtons.children.length : 0,
                innerHTML: labelButtons ? labelButtons.innerHTML.substring(0, 200) : 'N/A'
            };

            // Check if setupSpanLabelSelector was called
            debug.setupSpanLabelSelectorCalled = typeof window.setupSpanLabelSelectorCalled !== 'undefined';

            // Check network requests
            debug.networkRequests = [];
            if (window.performance && window.performance.getEntriesByType) {
                const entries = window.performance.getEntriesByType('resource');
                debug.networkRequests = entries.map(entry => ({
                    name: entry.name,
                    duration: entry.duration,
                    transferSize: entry.transferSize
                }));
            }

            return debug;
        """)

        print(f"\n🔍 DEBUG INFO:")
        print(f"  Current Instance: {debug_info.get('currentInstance')}")
        print(f"  Current Instance Keys: {debug_info.get('currentInstanceKeys')}")
        print(f"  Span Manager: {debug_info.get('spanManager')}")
        print(f"  Span Manager Current Instance ID: {debug_info.get('spanManagerCurrentInstanceId')}")
        print(f"  Annotation Scheme: {debug_info.get('annotationScheme')}")
        print(f"  Annotation Scheme Type: {debug_info.get('annotationSchemeType')}")
        print(f"  Annotation Scheme Length: {debug_info.get('annotationSchemeLength')}")
        print(f"  Span Labels: {debug_info.get('spanLabels')}")
        print(f"  Label Selector: {debug_info.get('labelSelector')}")
        print(f"  Label Buttons: {debug_info.get('labelButtons')}")
        print(f"  Setup Span Label Selector Called: {debug_info.get('setupSpanLabelSelectorCalled')}")

        # Check network requests
        network_requests = debug_info.get('networkRequests', [])
        print(f"\n🌐 Network Requests ({len(network_requests)}):")
        for req in network_requests[:10]:  # Show first 10
            print(f"  {req['name']} ({req['duration']}ms, {req['transferSize']} bytes)")

        # Force call setupSpanLabelSelector and check result
        force_result = self.driver.execute_script("""
            if (typeof setupSpanLabelSelector === 'function') {
                console.log('[FORCE] Calling setupSpanLabelSelector...');
                setupSpanLabelSelector();

                const labelSelector = document.getElementById('span-label-selector');
                const labelButtons = document.getElementById('label-buttons');

                return {
                    labelSelectorDisplay: labelSelector ? labelSelector.style.display : 'N/A',
                    labelButtonsChildren: labelButtons ? labelButtons.children.length : 0,
                    labelButtonsHTML: labelButtons ? labelButtons.innerHTML.substring(0, 200) : 'N/A'
                };
            } else {
                return { error: 'setupSpanLabelSelector function not found' };
            }
        """)

        print(f"\n🔧 Force Call Result: {force_result}")

        # Final check - are elements visible now?
        try:
            label_selector = self.driver.find_element(By.ID, "span-label-selector")
            label_buttons = self.driver.find_element(By.ID, "label-buttons")

            label_selector_visible = label_selector.is_displayed()
            label_buttons_visible = label_buttons.is_displayed()
            label_buttons_count = len(label_buttons.find_elements(By.TAG_NAME, "button"))

            print(f"\n✅ FINAL VISIBILITY CHECK:")
            print(f"  Label Selector Visible: {label_selector_visible}")
            print(f"  Label Buttons Visible: {label_buttons_visible}")
            print(f"  Label Buttons Count: {label_buttons_count}")

            # Assert the elements should be visible
            self.assertTrue(label_selector_visible, "Label selector should be visible")
            self.assertTrue(label_buttons_visible, "Label buttons should be visible")
            self.assertGreater(label_buttons_count, 0, "Should have at least one label button")

        except Exception as e:
            print(f"\n❌ FINAL CHECK FAILED: {e}")
            raise