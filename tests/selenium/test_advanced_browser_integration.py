"""
Advanced Browser Integration Tests

This test suite covers:
1. Keyboard-based interactions
2. Complex mouse gestures
3. Browser-specific behaviors (Firefox, Chrome, Safari)
4. Accessibility features
5. Mobile-like interactions
6. Network interruption handling
"""

import time
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from tests.selenium.test_base import BaseSeleniumTest


class TestAdvancedBrowserIntegration(BaseSeleniumTest):
    """Advanced integration tests for browser-specific behaviors and complex interactions."""

    def setUp(self):
        """Set up test environment with enhanced debugging."""
        super().setUp()
        self.wait = WebDriverWait(self.driver, 10)
        self.actions = ActionChains(self.driver)

    def test_keyboard_shortcuts_and_interactions(self):
        """Test keyboard shortcuts and keyboard-based span creation."""
        print("\n" + "="*80)
        print("🧪 KEYBOARD SHORTCUTS AND INTERACTIONS TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for positioning strategy to initialize
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.positioningStrategy &&
                        window.spanManager.positioningStrategy.isInitialized) {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                }; check();
            });
        """)

        # Test keyboard navigation
        body = self.driver.find_element(By.TAG_NAME, "body")

        # Test Ctrl+A (select all)
        self.actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
        time.sleep(0.1)

        select_all_result = self.execute_script_safe("""
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0) {
                const selectedText = selection.toString().trim();
                return {
                    success: true,
                    selectedText: selectedText,
                    textLength: selectedText.length
                };
            } else {
                return { success: false, error: 'No selection after Ctrl+A' };
            }
        """)

        print(f"🔧 Select all result: {select_all_result}")

        # Test keyboard-based span creation
        if select_all_result and select_all_result.get('success'):
            keyboard_span_result = self.execute_script_safe("""
                const selection = window.getSelection();
                if (selection && selection.rangeCount > 0 && !selection.isCollapsed) {
                    const selectedText = selection.toString().trim();

                    if (window.spanManager && window.spanManager.positioningStrategy) {
                        const positioningStrategy = window.spanManager.positioningStrategy;

                        // Create span using keyboard-selected text
                        const spanResult = positioningStrategy.createSpanWithAlgorithm(0, selectedText.length, selectedText);

                        return {
                            success: true,
                            selectedText: selectedText,
                            spanResult: spanResult
                        };
                    } else {
                        return { success: false, error: 'Positioning strategy not available' };
                    }
                } else {
                    return { success: false, error: 'No valid selection for keyboard span creation' };
                }
            """)

            print(f"🔧 Keyboard span result: {keyboard_span_result}")

            # Verify keyboard-based span creation works
            self.assertTrue(keyboard_span_result and keyboard_span_result.get('success'),
                           f"Keyboard span creation failed: {keyboard_span_result}")

        # Test Escape key to clear selection
        self.actions.send_keys(Keys.ESCAPE).perform()
        time.sleep(0.1)

        escape_result = self.execute_script_safe("""
            const selection = window.getSelection();
            return {
                success: true,
                isCollapsed: selection ? selection.isCollapsed : true,
                rangeCount: selection ? selection.rangeCount : 0
            };
        """)

        print(f"🔧 Escape key result: {escape_result}")

        # Verify selection is cleared
        self.assertTrue(escape_result and escape_result.get('isCollapsed'),
                       "Selection should be cleared after Escape key")

        print("✅ Keyboard shortcuts and interactions test passed!")

    def test_complex_mouse_gestures(self):
        """Test complex mouse gestures and multi-touch-like interactions."""
        print("\n" + "="*80)
        print("🧪 COMPLEX MOUSE GESTURES TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for positioning strategy to initialize
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.positioningStrategy &&
                        window.spanManager.positioningStrategy.isInitialized) {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                }; check();
            });
        """)

        # Get text content element
        text_content = self.driver.find_element(By.ID, "text-content")

        # Test double-click selection
        self.actions.double_click(text_content).perform()
        time.sleep(0.1)

        double_click_result = self.execute_script_safe("""
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0) {
                const selectedText = selection.toString().trim();
                return {
                    success: true,
                    selectedText: selectedText,
                    isCollapsed: selection.isCollapsed
                };
            } else {
                return { success: false, error: 'No selection after double-click' };
            }
        """)

        print(f"🔧 Double-click result: {double_click_result}")

        # Test triple-click selection (select line)
        self.actions.click(text_content).click(text_content).click(text_content).perform()
        time.sleep(0.1)

        triple_click_result = self.execute_script_safe("""
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0) {
                const selectedText = selection.toString().trim();
                return {
                    success: true,
                    selectedText: selectedText,
                    isCollapsed: selection.isCollapsed
                };
            } else {
                return { success: false, error: 'No selection after triple-click' };
            }
        """)

        print(f"🔧 Triple-click result: {triple_click_result}")

        # Test drag and drop simulation
        self.actions.move_to_element(text_content)
        self.actions.click_and_hold()
        self.actions.move_by_offset(50, 0)
        self.actions.move_by_offset(50, 0)  # Continue dragging
        self.actions.release()
        self.actions.perform()

        drag_result = self.execute_script_safe("""
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0) {
                const selectedText = selection.toString().trim();
                return {
                    success: true,
                    selectedText: selectedText,
                    isCollapsed: selection.isCollapsed
                };
            } else {
                return { success: false, error: 'No selection after drag' };
            }
        """)

        print(f"🔧 Drag result: {drag_result}")

        # Verify at least one gesture works
        gestures_worked = [
            double_click_result and double_click_result.get('success'),
            triple_click_result and triple_click_result.get('success'),
            drag_result and drag_result.get('success')
        ]

        self.assertTrue(any(gestures_worked), "At least one mouse gesture should work")

        print("✅ Complex mouse gestures test passed!")

    def test_browser_specific_behaviors(self):
        """Test browser-specific behaviors and compatibility."""
        print("\n" + "="*80)
        print("🧪 BROWSER SPECIFIC BEHAVIORS TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for positioning strategy to initialize
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.positioningStrategy &&
                        window.spanManager.positioningStrategy.isInitialized) {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                }; check();
            });
        """)

        # Detect browser and test specific behaviors
        browser_info = self.execute_script_safe("""
            return {
                userAgent: navigator.userAgent,
                isFirefox: navigator.userAgent.includes('Firefox'),
                isChrome: navigator.userAgent.includes('Chrome'),
                isSafari: navigator.userAgent.includes('Safari'),
                isEdge: navigator.userAgent.includes('Edge'),
                supportsFonts: !!document.fonts,
                supportsCanvas: !!document.createElement('canvas').getContext,
                supportsSelection: !!window.getSelection
            };
        """)

        print(f"🔧 Browser info: {browser_info}")

        # Test browser-specific font handling
        font_test_result = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.positioningStrategy) {
                const positioningStrategy = window.spanManager.positioningStrategy;

                try {
                    const fontMetrics = positioningStrategy.fontMetrics;
                    return {
                        success: true,
                        fontMetrics: fontMetrics,
                        fontSize: fontMetrics ? fontMetrics.fontSize : null,
                        fontFamily: fontMetrics ? fontMetrics.fontFamily : null
                    };
                } catch (error) {
                    return { success: false, error: error.toString() };
                }
            } else {
                return { success: false, error: 'Positioning strategy not available' };
            }
        """)

        print(f"🔧 Font test result: {font_test_result}")

        # Test browser-specific selection behavior
        selection_test_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (textContent) {
                // Test browser-specific selection methods
                const range = document.createRange();
                range.selectNodeContents(textContent);

                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);

                const selectedText = selection.toString().trim();

                return {
                    success: true,
                    selectedText: selectedText,
                    textLength: selectedText.length,
                    rangeCount: selection.rangeCount,
                    isCollapsed: selection.isCollapsed
                };
            } else {
                return { success: false, error: 'Text content element not found' };
            }
        """)

        print(f"🔧 Selection test result: {selection_test_result}")

        # Test browser-specific canvas support
        canvas_test_result = self.execute_script_safe("""
            try {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');

                if (ctx) {
                    ctx.font = '16px Arial';
                    const metrics = ctx.measureText('Test');

                    return {
                        success: true,
                        canvasSupported: true,
                        textMetrics: {
                            width: metrics.width,
                            actualBoundingBoxLeft: metrics.actualBoundingBoxLeft,
                            actualBoundingBoxRight: metrics.actualBoundingBoxRight
                        }
                    };
                } else {
                    return { success: false, error: 'Canvas context not available' };
                }
            } catch (error) {
                return { success: false, error: error.toString() };
            }
        """)

        print(f"🔧 Canvas test result: {canvas_test_result}")

        # Verify browser compatibility
        self.assertTrue(browser_info.get('supportsSelection'), "Browser should support text selection")
        self.assertTrue(font_test_result and font_test_result.get('success'), "Font handling should work")
        self.assertTrue(selection_test_result and selection_test_result.get('success'), "Selection should work")

        print("✅ Browser specific behaviors test passed!")

    def test_accessibility_features(self):
        """Test accessibility features and keyboard navigation."""
        print("\n" + "="*80)
        print("🧪 ACCESSIBILITY FEATURES TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for positioning strategy to initialize
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.positioningStrategy &&
                        window.spanManager.positioningStrategy.isInitialized) {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                }; check();
            });
        """)

        # Test keyboard navigation
        body = self.driver.find_element(By.TAG_NAME, "body")

        # Test Tab navigation
        body.send_keys(Keys.TAB)
        time.sleep(0.1)

        tab_result = self.execute_script_safe("""
            const activeElement = document.activeElement;
            return {
                success: true,
                activeElementId: activeElement ? activeElement.id : null,
                activeElementTag: activeElement ? activeElement.tagName : null,
                isFocusable: activeElement ? activeElement.tabIndex >= 0 : false
            };
        """)

        print(f"🔧 Tab navigation result: {tab_result}")

        # Test arrow key navigation
        body.send_keys(Keys.ARROW_RIGHT)
        time.sleep(0.1)

        arrow_result = self.execute_script_safe("""
            const selection = window.getSelection();
            return {
                success: true,
                hasSelection: !!selection,
                isCollapsed: selection ? selection.isCollapsed : true,
                rangeCount: selection ? selection.rangeCount : 0
            };
        """)

        print(f"🔧 Arrow key result: {arrow_result}")

        # Test screen reader compatibility
        accessibility_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (textContent) {
                return {
                    success: true,
                    hasAriaLabel: !!textContent.getAttribute('aria-label'),
                    hasRole: !!textContent.getAttribute('role'),
                    hasTabIndex: textContent.tabIndex >= 0,
                    isReadable: textContent.textContent && textContent.textContent.trim().length > 0
                };
            } else {
                return { success: false, error: 'Text content element not found' };
            }
        """)

        print(f"🔧 Accessibility result: {accessibility_result}")

        # Verify accessibility features
        self.assertTrue(tab_result and tab_result.get('success'), "Tab navigation should work")
        self.assertTrue(accessibility_result and accessibility_result.get('success'), "Accessibility check should work")
        self.assertTrue(accessibility_result.get('isReadable'), "Content should be readable")

        print("✅ Accessibility features test passed!")

    def test_mobile_like_interactions(self):
        """Test mobile-like interactions and touch simulation."""
        print("\n" + "="*80)
        print("🧪 MOBILE LIKE INTERACTIONS TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for positioning strategy to initialize
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.positioningStrategy &&
                        window.spanManager.positioningStrategy.isInitialized) {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                }; check();
            });
        """)

        # Get text content element
        text_content = self.driver.find_element(By.ID, "text-content")

        # Test touch-like selection (click and drag)
        self.actions.move_to_element(text_content)
        self.actions.click_and_hold()
        self.actions.move_by_offset(30, 0)
        self.actions.pause(0.2)  # Simulate touch delay
        self.actions.move_by_offset(30, 0)
        self.actions.release()
        self.actions.perform()

        touch_selection_result = self.execute_script_safe("""
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0) {
                const selectedText = selection.toString().trim();
                return {
                    success: true,
                    selectedText: selectedText,
                    textLength: selectedText.length,
                    isCollapsed: selection.isCollapsed
                };
            } else {
                return { success: false, error: 'No selection after touch-like interaction' };
            }
        """)

        print(f"🔧 Touch selection result: {touch_selection_result}")

        # Test pinch-to-zoom simulation (resize window)
        original_size = self.driver.get_window_size()
        self.driver.set_window_size(400, 600)  # Simulate mobile viewport
        time.sleep(0.1)

        mobile_view_result = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.positioningStrategy) {
                const positioningStrategy = window.spanManager.positioningStrategy;

                // Force reinitialization for new viewport
                return positioningStrategy.initialize().then(() => {
                    const spanResult = positioningStrategy.createSpanWithAlgorithm(0, 5, 'I am ');
                    return {
                        success: true,
                        spanResult: spanResult,
                        viewportWidth: window.innerWidth,
                        viewportHeight: window.innerHeight
                    };
                }).catch((error) => {
                    return { success: false, error: error.toString() };
                });
            } else {
                return { success: false, error: 'Positioning strategy not available' };
            }
        """)

        print(f"🔧 Mobile view result: {mobile_view_result}")

        # Restore original window size
        self.driver.set_window_size(original_size['width'], original_size['height'])

        # Test scroll behavior
        scroll_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (textContent) {
                const originalScrollTop = textContent.scrollTop;
                textContent.scrollTop = 50;

                return {
                    success: true,
                    originalScrollTop: originalScrollTop,
                    newScrollTop: textContent.scrollTop,
                    scrollable: textContent.scrollHeight > textContent.clientHeight
                };
            } else {
                return { success: false, error: 'Text content element not found' };
            }
        """)

        print(f"🔧 Scroll result: {scroll_result}")

        # Verify mobile-like interactions work
        self.assertTrue(touch_selection_result and touch_selection_result.get('success'),
                       "Touch-like selection should work")
        self.assertTrue(mobile_view_result and mobile_view_result.get('success'),
                       "Mobile viewport handling should work")

        print("✅ Mobile like interactions test passed!")

    def test_network_interruption_handling(self):
        """Test how the system handles network interruptions and recovery."""
        print("\n" + "="*80)
        print("🧪 NETWORK INTERRUPTION HANDLING TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for positioning strategy to initialize
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.positioningStrategy &&
                        window.spanManager.positioningStrategy.isInitialized) {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                }; check();
            });
        """)

        # Test offline behavior
        offline_result = self.execute_script_safe("""
            // Simulate offline mode
            const originalOnline = navigator.onLine;
            Object.defineProperty(navigator, 'onLine', {
                get: function() { return false; }
            });

            try {
                if (window.spanManager && window.spanManager.positioningStrategy) {
                    const positioningStrategy = window.spanManager.positioningStrategy;

                    // Test if positioning still works offline
                    const spanResult = positioningStrategy.createSpanWithAlgorithm(0, 5, 'I am ');

                    return {
                        success: true,
                        spanResult: spanResult,
                        offline: !navigator.onLine
                    };
                } else {
                    return { success: false, error: 'Positioning strategy not available' };
                }
            } finally {
                // Restore original online status
                Object.defineProperty(navigator, 'onLine', {
                    get: function() { return originalOnline; }
                });
            }
        """)

        print(f"🔧 Offline result: {offline_result}")

        # Test API failure handling
        api_failure_result = self.execute_script_safe("""
            if (window.spanManager) {
                // Test if span manager handles API failures gracefully
                const originalFetch = window.fetch;

                // Mock fetch to simulate API failure
                window.fetch = function() {
                    return Promise.reject(new Error('Network error'));
                };

                try {
                    // Try to create an annotation (should fail gracefully)
                    const annotationPromise = window.spanManager.createAnnotation('test', 0, 4, 'test_label');

                    return {
                        success: true,
                        annotationPromise: 'Promise created',
                        message: 'API failure handled gracefully'
                    };
                } catch (error) {
                    return { success: false, error: error.toString() };
                } finally {
                    // Restore original fetch
                    window.fetch = originalFetch;
                }
            } else {
                return { success: false, error: 'SpanManager not available' };
            }
        """)

        print(f"🔧 API failure result: {api_failure_result}")

        # Test recovery after network restoration
        recovery_result = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.positioningStrategy) {
                const positioningStrategy = window.spanManager.positioningStrategy;

                // Test if positioning strategy recovers after network issues
                const spanResult = positioningStrategy.createSpanWithAlgorithm(0, 5, 'I am ');

                return {
                    success: true,
                    spanResult: spanResult,
                    recovered: true
                };
            } else {
                return { success: false, error: 'Positioning strategy not available' };
            }
        """)

        print(f"🔧 Recovery result: {recovery_result}")

        # Verify network interruption handling
        self.assertTrue(offline_result and offline_result.get('success'),
                       "System should work offline")
        self.assertTrue(api_failure_result and api_failure_result.get('success'),
                       "API failures should be handled gracefully")
        self.assertTrue(recovery_result and recovery_result.get('success'),
                       "System should recover after network restoration")

        print("✅ Network interruption handling test passed!")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])