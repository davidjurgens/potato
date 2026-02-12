"""
Comprehensive tests for pure CSS positioning algorithm edge cases.
Tests various scenarios that could cause positioning issues.

NOTE: These tests are SKIPPED because they test internal JS functions
(getOriginalTextForPositioning, calculateCharacterPositions) that have
been removed during the span positioning refactoring. The functionality
is now handled differently in span-core.js.
"""

import time
import unittest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest


@unittest.skip("Tests internal JS functions that have been removed during refactoring")
class TestPureCSSEdgeCases(BaseSeleniumTest):
    """Test edge cases for the pure CSS positioning algorithm."""

    def test_empty_span_range(self):
        """Test handling of empty span ranges (start == end)."""
        print("\n" + "="*80)
        print("🧪 TESTING EMPTY SPAN RANGE")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Test with empty range (start == end)
        result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            const fontMetrics = getFontMetrics(textContent);
            const originalText = getOriginalTextForPositioning(textContent);

            // Test empty range
            const positions = calculateCharacterPositions(originalText, 10, 10, fontMetrics, textContent);

            return {
                success: true,
                positions: positions,
                positionsLength: positions.length,
                originalText: originalText,
                testRange: { start: 10, end: 10 }
            };
        """)

        print(f"🔧 Empty range test result: {result}")

        # Empty ranges should return empty array
        self.assertEqual(result['positionsLength'], 0, "Empty range should return no positions")
        print("✅ Empty range handled correctly")

    def test_invalid_span_range(self):
        """Test handling of invalid span ranges (out of bounds)."""
        print("\n" + "="*80)
        print("🧪 TESTING INVALID SPAN RANGE")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Test various invalid ranges
        test_cases = [
            {"start": -1, "end": 5, "description": "Negative start"},
            {"start": 0, "end": -1, "description": "Negative end"},
            {"start": 1000, "end": 1005, "description": "Start beyond text length"},
            {"start": 5, "end": 1000, "description": "End beyond text length"},
            {"start": 10, "end": 5, "description": "Start > end"}
        ]

        for test_case in test_cases:
            result = self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const fontMetrics = getFontMetrics(textContent);
                const originalText = getOriginalTextForPositioning(textContent);

                const positions = calculateCharacterPositions(
                    originalText,
                    {test_case['start']},
                    {test_case['end']},
                    fontMetrics,
                    textContent
                );

                return {{
                    success: true,
                    positions: positions,
                    positionsLength: positions.length,
                    testCase: {test_case}
                }};
            """)

            print(f"🔧 {test_case['description']}: {result}")

            # Invalid ranges should return empty array
            self.assertEqual(result['positionsLength'], 0,
                           f"Invalid range ({test_case['description']}) should return no positions")

        print("✅ All invalid ranges handled correctly")

    def test_single_character_span(self):
        """Test positioning of single character spans."""
        print("\n" + "="*80)
        print("🧪 TESTING SINGLE CHARACTER SPAN")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Test single character at different positions
        test_positions = [0, 5, 10, 20, 40]  # Different positions in the text

        for pos in test_positions:
            result = self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const fontMetrics = getFontMetrics(textContent);
                const originalText = getOriginalTextForPositioning(textContent);
                const pos = {pos};

                if (pos >= originalText.length) {{
                    return {{ success: false, error: 'Position out of bounds' }};
                }}

                const positions = calculateCharacterPositions(
                    originalText,
                    pos,
                    pos + 1,
                    fontMetrics,
                    textContent
                );

                const targetChar = originalText[pos];

                return {{
                    success: true,
                    positions: positions,
                    positionsLength: positions.length,
                    targetChar: targetChar,
                    position: pos
                }};
            """)

            print(f"🔧 Single character at position {pos}: {result}")

            if result.get('success'):
                # Should return exactly one position
                self.assertEqual(result['positionsLength'], 1,
                               f"Single character at position {pos} should return exactly one position")

                # Position should have valid dimensions
                position = result['positions'][0]
                self.assertGreater(position['width'], 0,
                                 f"Single character width should be positive at position {pos}")
                self.assertGreater(position['height'], 0,
                                 f"Single character height should be positive at position {pos}")

                print(f"✅ Single character '{result['targetChar']}' at position {pos} positioned correctly")

        print("✅ All single character spans handled correctly")

    def test_word_wrapping_edge_cases(self):
        """Test positioning when text wraps to new lines."""
        print("\n" + "="*80)
        print("🧪 TESTING WORD WRAPPING EDGE CASES")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Test spans that cross line boundaries using the existing text
        test_cases = [
            {"start": 0, "end": 50, "description": "Span starting at beginning"},
            {"start": 20, "end": 70, "description": "Span crossing line boundary"},
            {"start": 40, "end": 88, "description": "Span in middle of text"},
            {"start": 60, "end": 88, "description": "Span near end of text"}
        ]

        for test_case in test_cases:
            result = self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const fontMetrics = getFontMetrics(textContent);
                const originalText = getOriginalTextForPositioning(textContent);

                const positions = calculateCharacterPositions(
                    originalText,
                    {test_case['start']},
                    {test_case['end']},
                    fontMetrics,
                    textContent
                );

                const targetText = originalText.substring({test_case['start']}, {test_case['end']});

                return {{
                    success: true,
                    positions: positions,
                    positionsLength: positions.length,
                    targetText: targetText,
                    testCase: {test_case}
                }};
            """)

            print(f"🔧 {test_case['description']}: {result}")

            # Should return at least one position
            self.assertGreater(result['positionsLength'], 0,
                             f"Word wrapping test should return at least one position")

            # Check that positions are valid
            for i, position in enumerate(result['positions']):
                self.assertGreater(position['width'], 0,
                                 f"Position {i} width should be positive")
                self.assertGreater(position['height'], 0,
                                 f"Position {i} height should be positive")
                self.assertGreaterEqual(position['x'], 0,
                                      f"Position {i} x should be non-negative")
                self.assertGreaterEqual(position['y'], 0,
                                      f"Position {i} y should be non-negative")

            print(f"✅ {test_case['description']} handled correctly with {result['positionsLength']} segments")

        print("✅ All word wrapping edge cases handled correctly")

    def test_special_characters(self):
        """Test positioning with special characters (spaces, tabs, newlines)."""
        print("\n" + "="*80)
        print("🧪 TESTING SPECIAL CHARACTERS")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Test special characters
        special_chars = [
            {"char": " ", "name": "space"},
            {"char": "!", "name": "exclamation"},
            {"char": "?", "name": "question"},
            {"char": ".", "name": "period"},
            {"char": ",", "name": "comma"}
        ]

        for char_info in special_chars:
            result = self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const fontMetrics = getFontMetrics(textContent);
                const originalText = getOriginalTextForPositioning(textContent);

                // Find the special character in the text
                const charIndex = originalText.indexOf('{char_info['char']}');

                if (charIndex === -1) {{
                    return {{ success: false, error: 'Character not found in text' }};
                }}

                const positions = calculateCharacterPositions(
                    originalText,
                    charIndex,
                    charIndex + 1,
                    fontMetrics,
                    textContent
                );

                return {{
                    success: true,
                    positions: positions,
                    positionsLength: positions.length,
                    char: '{char_info['char']}',
                    charName: '{char_info['name']}',
                    charIndex: charIndex
                }};
            """)

            print(f"🔧 Special character '{char_info['name']}': {result}")

            if result.get('success'):
                # Should return exactly one position
                self.assertEqual(result['positionsLength'], 1,
                               f"Special character '{char_info['name']}' should return exactly one position")

                # Position should have valid dimensions
                position = result['positions'][0]
                self.assertGreaterEqual(position['width'], 0,
                                      f"Special character '{char_info['name']}' width should be non-negative")
                self.assertGreater(position['height'], 0,
                                 f"Special character '{char_info['name']}' height should be positive")

                print(f"✅ Special character '{char_info['name']}' positioned correctly")

        print("✅ All special characters handled correctly")

    def test_multi_line_span_creation(self):
        """Test creating spans that span multiple lines."""
        print("\n" + "="*80)
        print("🧪 TESTING MULTI-LINE SPAN CREATION")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Temporarily disable span manager cleanup to prevent overlay removal
        self.execute_script_safe("""
            if (window.spanManager) {
                // Store original methods
                window.spanManager._originalClearAllStateAndOverlays = window.spanManager.clearAllStateAndOverlays;
                window.spanManager._originalClearAllSpanOverlays = window.spanManager.clearAllSpanOverlays;

                // Disable cleanup methods
                window.spanManager.clearAllStateAndOverlays = function() {
                    console.log('🔍 [TEST] Disabled clearAllStateAndOverlays for test');
                };
                window.spanManager.clearAllSpanOverlays = function() {
                    console.log('🔍 [TEST] Disabled clearAllSpanOverlays for test');
                };
            }
        """)

        # Create a multi-line span
        span_data = {
            "id": "test_multi_line",
            "text": "technology that will revolutionize",
            "start": 40,
            "end": 70,
            "label": "test_label"
        }

        # Test the pure CSS overlay creation
        result = self.execute_script_safe(f"""
            const span = {span_data};
            const textContent = document.getElementById('text-content');
            const fontMetrics = getFontMetrics(textContent);
            const originalText = getOriginalTextForPositioning(textContent);

            const positions = calculateCharacterPositions(
                originalText,
                span.start,
                span.end,
                fontMetrics,
                textContent
            );

            const overlay = createPureCSSOverlay(span, positions, textContent, fontMetrics);

            return {{
                success: true,
                positions: positions,
                positionsLength: positions.length,
                overlay: overlay ? 'created' : 'failed',
                span: span
            }};
        """)

        print(f"🔧 Multi-line span creation result: {result}")

        # Should return multiple positions for multi-line span
        self.assertGreater(result['positionsLength'], 0,
                          "Multi-line span should return at least one position")

        # Overlay should be created successfully
        self.assertEqual(result['overlay'], 'created',
                        "Multi-line overlay should be created successfully")

        print("✅ Multi-line span creation handled correctly")

    def test_container_edge_positioning(self):
        """Test positioning at the edges of the container."""
        print("\n" + "="*80)
        print("🧪 TESTING CONTAINER EDGE POSITIONING")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Test positioning at container edges
        edge_tests = [
            {"start": 0, "end": 1, "description": "First character"},
            {"start": 0, "end": 5, "description": "Start of text"},
            {"start": 80, "end": 85, "description": "End of text"},
            {"start": 79, "end": 80, "description": "Last character"}
        ]

        for test_case in edge_tests:
            result = self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const fontMetrics = getFontMetrics(textContent);
                const originalText = getOriginalTextForPositioning(textContent);
                const containerRect = textContent.getBoundingClientRect();

                // Calculate content area dimensions (excluding padding)
                const contentWidth = containerRect.width - fontMetrics.containerPadding.left - fontMetrics.containerPadding.right;
                const contentHeight = containerRect.height - fontMetrics.containerPadding.top - fontMetrics.containerPadding.bottom;

                const positions = calculateCharacterPositions(
                    originalText,
                    {test_case['start']},
                    {test_case['end']},
                    fontMetrics,
                    textContent
                );

                return {{
                    success: true,
                    positions: positions,
                    positionsLength: positions.length,
                    containerWidth: containerRect.width,
                    containerHeight: containerRect.height,
                    contentWidth: contentWidth,
                    contentHeight: contentHeight,
                    testCase: {test_case}
                }};
            """)

            print(f"🔧 {test_case['description']}: {result}")

            # Should return at least one position
            self.assertGreater(result['positionsLength'], 0,
                             f"Edge positioning test should return at least one position")

            # Check that positions are within reasonable bounds
            for i, position in enumerate(result['positions']):
                self.assertGreaterEqual(position['x'], 0,
                                      f"Position {i} x should be non-negative")
                self.assertGreaterEqual(position['y'], 0,
                                      f"Position {i} y should be non-negative")
                # Allow a small tolerance for positioning (1px)
                self.assertLessEqual(position['x'] + position['width'], result['contentWidth'] + 1,
                                   f"Position {i} should not extend significantly beyond content width")
                self.assertLessEqual(position['y'] + position['height'], result['contentHeight'] + 1,
                                   f"Position {i} should not extend significantly beyond content height")

            print(f"✅ {test_case['description']} positioned correctly within container bounds")

        print("✅ All container edge positioning tests passed")

    def test_font_metrics_accuracy(self):
        """Test that font metrics are calculated accurately."""
        print("\n" + "="*80)
        print("🧪 TESTING FONT METRICS ACCURACY")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Test font metrics calculation
        result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            const fontMetrics = getFontMetrics(textContent);

            // Test measuring specific text
            const testText = "Hello World";
            const measuredWidth = measureText(testText, fontMetrics);

            // Calculate expected width using character widths
            let expectedWidth = 0;
            for (let char of testText) {
                expectedWidth += fontMetrics.charWidths[char] || fontMetrics.averageCharWidth;
            }

            return {
                success: true,
                fontMetrics: fontMetrics,
                testText: testText,
                measuredWidth: measuredWidth,
                expectedWidth: expectedWidth,
                difference: Math.abs(measuredWidth - expectedWidth)
            };
        """)

        print(f"🔧 Font metrics test result: {result}")

        # Font metrics should be valid
        self.assertGreater(result['fontMetrics']['fontSize'], 0,
                          "Font size should be positive")
        self.assertGreater(result['fontMetrics']['lineHeight'], 0,
                          "Line height should be positive")
        self.assertGreater(result['fontMetrics']['averageCharWidth'], 0,
                          "Average character width should be positive")

        # Measured width should be close to expected width
        self.assertLess(result['difference'], 5,
                       "Measured width should be close to expected width (within 5px)")

        print("✅ Font metrics calculated accurately")

    def test_pure_css_overlay_rendering(self):
        """Test that pure CSS overlays are rendered correctly in the DOM."""
        print("\n" + "="*80)
        print("🧪 TESTING PURE CSS OVERLAY RENDERING")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Create a test span and render it
        span_data = {
            "id": "test_render",
            "text": "technology",
            "start": 40,
            "end": 50,
            "label": "test_label"
        }

        # Test the positioning algorithm and overlay creation
        result = self.execute_script_safe(f"""
            const span = {span_data};
            const textContent = document.getElementById('text-content');
            const spanOverlays = document.getElementById('span-overlays');

            if (!spanOverlays) {{
                return {{ success: false, error: 'Span overlays container not found' }};
            }}

            const fontMetrics = getFontMetrics(textContent);
            const originalText = getOriginalTextForPositioning(textContent);

            const positions = calculateCharacterPositions(
                originalText,
                span.start,
                span.end,
                fontMetrics,
                textContent
            );

            const overlay = createPureCSSOverlay(span, positions, textContent, fontMetrics);

            // Test that the overlay was created correctly
            const overlayCreated = overlay !== null;
            const hasCorrectClass = overlay && overlay.classList.contains('span-overlay-pure');
            const hasCorrectAttributes = overlay &&
                overlay.dataset.annotationId === span.id &&
                overlay.dataset.start === span.start.toString() &&
                overlay.dataset.end === span.end.toString() &&
                overlay.dataset.label === span.label;

            // Test positioning
            const hasPositioning = overlay &&
                overlay.style.position === 'absolute' &&
                overlay.style.left &&
                overlay.style.top &&
                overlay.style.width &&
                overlay.style.height;

            // Test styling
            const hasStyling = overlay &&
                overlay.style.backgroundColor &&
                overlay.style.zIndex &&
                overlay.style.pointerEvents;

            return {{
                success: true,
                overlayCreated: overlayCreated,
                hasCorrectClass: hasCorrectClass,
                hasCorrectAttributes: hasCorrectAttributes,
                hasPositioning: hasPositioning,
                hasStyling: hasStyling,
                positions: positions,
                positionsLength: positions.length,
                overlayElement: overlay ? {{
                    className: overlay.className,
                    dataset: overlay.dataset,
                    style: {{
                        position: overlay.style.position,
                        left: overlay.style.left,
                        top: overlay.style.top,
                        width: overlay.style.width,
                        height: overlay.style.height,
                        backgroundColor: overlay.style.backgroundColor,
                        zIndex: overlay.style.zIndex
                    }}
                }} : null
            }};
        """)

        print(f"🔧 Pure CSS overlay rendering result: {result}")

        # Test that the overlay was created correctly
        self.assertTrue(result['overlayCreated'],
                        "Pure CSS overlay should be created successfully")
        self.assertTrue(result['hasCorrectClass'],
                        "Overlay should have the correct CSS class")
        self.assertTrue(result['hasCorrectAttributes'],
                        "Overlay should have the correct data attributes")
        self.assertTrue(result['hasPositioning'],
                        "Overlay should have proper positioning styles")
        self.assertTrue(result['hasStyling'],
                        "Overlay should have proper styling")

        # Test that positions were calculated correctly
        self.assertGreater(result['positionsLength'], 0,
                        "At least one position should be calculated")
        self.assertIsNotNone(result['positions'],
                        "Positions should not be null")

        print("✅ Pure CSS overlay creation and positioning working correctly")

    def test_mixed_content_positioning(self):
        """Test positioning with mixed content (text, numbers, symbols)."""
        print("\n" + "="*80)
        print("🧪 TESTING MIXED CONTENT POSITIONING")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Test mixed content positioning
        test_cases = [
            {"start": 0, "end": 10, "description": "Mixed text and numbers"},
            {"start": 20, "end": 30, "description": "Text with punctuation"},
            {"start": 40, "end": 50, "description": "Numbers and symbols"},
            {"start": 60, "end": 70, "description": "Mixed case text"}
        ]

        for test_case in test_cases:
            result = self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const fontMetrics = getFontMetrics(textContent);
                const originalText = getOriginalTextForPositioning(textContent);

                const positions = calculateCharacterPositions(
                    originalText,
                    {test_case['start']},
                    {test_case['end']},
                    fontMetrics,
                    textContent
                );

                return {{
                    success: true,
                    positions: positions,
                    positionsLength: positions.length,
                    testCase: {test_case}
                }};
            """)

            print(f"🔧 {test_case['description']}: {result}")

            # Verify positions are calculated correctly
            self.assertGreater(result['positionsLength'], 0,
                            f"At least one position should be calculated for {test_case['description']}")
            self.assertIsNotNone(result['positions'],
                            f"Positions should not be null for {test_case['description']}")

        print("✅ Mixed content positioning working correctly")

    def test_dynamic_font_changes(self):
        """Test positioning when font properties change dynamically."""
        print("\n" + "="*80)
        print("🧪 TESTING DYNAMIC FONT CHANGES")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Test positioning with different font sizes
        font_sizes = ["12px", "16px", "20px", "24px"]

        for font_size in font_sizes:
            result = self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');

                // Change font size
                textContent.style.fontSize = '{font_size}';

                // Wait for font change to take effect
                return new Promise((resolve) => {{
                    setTimeout(() => {{
                        const fontMetrics = getFontMetrics(textContent);
                        const originalText = getOriginalTextForPositioning(textContent);

                        const positions = calculateCharacterPositions(
                            originalText,
                            0,
                            10,
                            fontMetrics,
                            textContent
                        );

                        resolve({{
                            success: true,
                            positions: positions,
                            positionsLength: positions.length,
                            fontSize: '{font_size}',
                            fontMetrics: fontMetrics
                        }});
                    }}, 100);
                }});
            """)

            print(f"🔧 Font size {font_size}: {result}")

            # Verify positions are calculated correctly
            self.assertGreater(result['positionsLength'], 0,
                            f"At least one position should be calculated for font size {font_size}")
            self.assertIsNotNone(result['positions'],
                            f"Positions should not be null for font size {font_size}")

        print("✅ Dynamic font changes working correctly")

    def test_container_resize_handling(self):
        """Test positioning when container is resized."""
        print("\n" + "="*80)
        print("🧪 TESTING CONTAINER RESIZE HANDLING")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Test positioning with different container widths
        container_widths = ["800px", "1200px", "1600px", "2000px"]

        for width in container_widths:
            result = self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const container = textContent.parentElement;

                // Change container width
                container.style.width = '{width}';

                // Wait for resize to take effect
                return new Promise((resolve) => {{
                    setTimeout(() => {{
                        const fontMetrics = getFontMetrics(textContent);
                        const originalText = getOriginalTextForPositioning(textContent);

                        const positions = calculateCharacterPositions(
                            originalText,
                            0,
                            10,
                            fontMetrics,
                            textContent
                        );

                        resolve({{
                            success: true,
                            positions: positions,
                            positionsLength: positions.length,
                            containerWidth: '{width}',
                            actualWidth: container.offsetWidth
                        }});
                    }}, 100);
                }});
            """)

            print(f"🔧 Container width {width}: {result}")

            # Verify positions are calculated correctly
            self.assertGreater(result['positionsLength'], 0,
                            f"At least one position should be calculated for container width {width}")
            self.assertIsNotNone(result['positions'],
                            f"Positions should not be null for container width {width}")

        print("✅ Container resize handling working correctly")

    def test_unicode_and_special_characters(self):
        """Test positioning with Unicode and special characters."""
        print("\n" + "="*80)
        print("🧪 TESTING UNICODE AND SPECIAL CHARACTERS")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Test positioning with Unicode and special characters
        test_cases = [
            {"start": 0, "end": 5, "description": "Basic Unicode characters"},
            {"start": 10, "end": 15, "description": "Emoji and symbols"},
            {"start": 20, "end": 25, "description": "Accented characters"},
            {"start": 30, "end": 35, "description": "Special punctuation"}
        ]

        for test_case in test_cases:
            result = self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const fontMetrics = getFontMetrics(textContent);
                const originalText = getOriginalTextForPositioning(textContent);

                const positions = calculateCharacterPositions(
                    originalText,
                    {test_case['start']},
                    {test_case['end']},
                    fontMetrics,
                    textContent
                );

                return {{
                    success: true,
                    positions: positions,
                    positionsLength: positions.length,
                    testCase: {test_case},
                    textLength: originalText.length
                }};
            """)

            print(f"🔧 {test_case['description']}: {result}")

            # Verify positions are calculated correctly
            self.assertGreater(result['positionsLength'], 0,
                            f"At least one position should be calculated for {test_case['description']}")
            self.assertIsNotNone(result['positions'],
                            f"Positions should not be null for {test_case['description']}")

        print("✅ Unicode and special characters positioning working correctly")

    def test_text_content_debug(self):
        """Debug test to understand text content issues."""
        print("\n" + "="*80)
        print("🧪 DEBUGGING TEXT CONTENT")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Debug text content
        debug_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            const originalText = getOriginalTextForPositioning(textContent);

            return {
                textContentText: textContent.textContent,
                textContentInnerHTML: textContent.innerHTML,
                originalText: originalText,
                textContentLength: textContent.textContent.length,
                originalTextLength: originalText ? originalText.length : 0,
                firstChar: textContent.textContent.charAt(0),
                firstCharCode: textContent.textContent.charCodeAt(0),
                firstCharOriginal: originalText ? originalText.charAt(0) : null,
                firstCharCodeOriginal: originalText ? originalText.charCodeAt(0) : null
            };
        """)

        print(f"🔍 [DEBUG] Text Content Debug Results: {debug_result}")

        # Basic assertions
        self.assertIsNotNone(debug_result['textContentText'], "Text content should not be null")
        self.assertGreater(debug_result['textContentLength'], 0, "Text content should have length > 0")
        self.assertEqual(debug_result['textContentText'], debug_result['originalText'], "Text content should match original text")

        # Check that first character is not a newline
        self.assertNotEqual(debug_result['firstChar'], '\n', "First character should not be a newline")
        self.assertNotEqual(debug_result['firstCharCode'], 10, "First character code should not be newline (10)")

    def test_padding_debug(self):
        """Debug test to understand padding calculations."""
        print("\n" + "="*80)
        print("🧪 DEBUGGING PADDING CALCULATIONS")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Debug padding calculations
        debug_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            const fontMetrics = getFontMetrics(textContent);
            const containerRect = textContent.getBoundingClientRect();
            const computedStyle = window.getComputedStyle(textContent);

            return {
                containerRect: {
                    width: containerRect.width,
                    height: containerRect.height
                },
                computedStyle: {
                    paddingTop: computedStyle.paddingTop,
                    paddingLeft: computedStyle.paddingLeft,
                    paddingRight: computedStyle.paddingRight,
                    paddingBottom: computedStyle.paddingBottom
                },
                fontMetrics: {
                    containerPadding: fontMetrics.containerPadding
                },
                calculatedContent: {
                    width: containerRect.width - fontMetrics.containerPadding.left - fontMetrics.containerPadding.right,
                    height: containerRect.height - fontMetrics.containerPadding.top - fontMetrics.containerPadding.bottom
                }
            };
        """)

        print(f"🔍 [DEBUG] Padding Debug Results: {debug_result}")

        # Basic assertions
        self.assertIsNotNone(debug_result['containerRect'], "Container rect should not be null")
        self.assertIsNotNone(debug_result['fontMetrics'], "Font metrics should not be null")

        # Check that padding values are reasonable
        self.assertGreaterEqual(debug_result['fontMetrics']['containerPadding']['top'], 0, "Top padding should be non-negative")
        self.assertGreaterEqual(debug_result['fontMetrics']['containerPadding']['left'], 0, "Left padding should be non-negative")
        self.assertGreaterEqual(debug_result['fontMetrics']['containerPadding']['right'], 0, "Right padding should be non-negative")
        self.assertGreaterEqual(debug_result['fontMetrics']['containerPadding']['bottom'], 0, "Bottom padding should be non-negative")

    def test_word_wrapping_debug(self):
        """Debug test to understand word wrapping issues."""
        print("\n" + "="*80)
        print("🧪 DEBUGGING WORD WRAPPING ISSUES")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Debug the problematic text range
        debug_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            const fontMetrics = getFontMetrics(textContent);
            const originalText = getOriginalTextForPositioning(textContent);

            // Test the problematic range (40-90)
            const start = 40;
            const end = 90;
            const targetText = originalText.substring(start, end);

            console.log('🔍 [DEBUG] Original text length:', originalText.length);
            console.log('🔍 [DEBUG] Target text:', targetText);
            console.log('🔍 [DEBUG] Target text length:', targetText.length);

            const positions = calculateCharacterPositions(
                originalText,
                start,
                end,
                fontMetrics,
                textContent
            );

            return {
                originalTextLength: originalText.length,
                targetText: targetText,
                targetTextLength: targetText.length,
                start: start,
                end: end,
                positions: positions,
                positionsLength: positions.length,
                fontMetrics: {
                    fontSize: fontMetrics.fontSize,
                    lineHeight: fontMetrics.lineHeight,
                    averageCharWidth: fontMetrics.averageCharWidth
                }
            };
        """)

        print(f"🔍 [DEBUG] Word Wrapping Debug Results: {debug_result}")

        # Basic assertions
        self.assertIsNotNone(debug_result['originalTextLength'], "Original text length should not be null")
        self.assertIsNotNone(debug_result['targetText'], "Target text should not be null")
        self.assertGreater(debug_result['originalTextLength'], 0, "Original text should have length > 0")
        self.assertGreater(debug_result['targetTextLength'], 0, "Target text should have length > 0")

    def test_positioning_algorithm_debug(self):
        """Detailed debug test to understand the positioning algorithm issue."""
        print("\n" + "="*80)
        print("🧪 DEBUGGING POSITIONING ALGORITHM")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Debug the positioning algorithm step by step
        debug_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            const fontMetrics = getFontMetrics(textContent);
            const originalText = getOriginalTextForPositioning(textContent);

            // Test the problematic range (40-90)
            const start = 40;
            const end = 90;
            const targetText = originalText.substring(start, end);

            // Get container dimensions
            const containerRect = textContent.getBoundingClientRect();
            const containerWidth = containerRect.width - fontMetrics.containerPadding.left - fontMetrics.containerPadding.right;

            console.log('🔍 [DEBUG] Container width:', containerWidth);
            console.log('🔍 [DEBUG] Font metrics:', fontMetrics);

            // Simulate the positioning algorithm step by step
            let currentLine = 0;
            let currentX = fontMetrics.containerPadding.left;
            let currentY = fontMetrics.containerPadding.top + (currentLine * fontMetrics.lineHeight);

            console.log('🔍 [DEBUG] Initial position:', { currentX, currentY, currentLine });

            // Calculate positions for all characters up to the start position
            for (let i = 0; i < start; i++) {
                const char = originalText[i];
                const charWidth = fontMetrics.charWidths[char] || fontMetrics.averageCharWidth;

                if (char === '\\n') {
                    currentLine++;
                    currentX = fontMetrics.containerPadding.left;
                    currentY = fontMetrics.containerPadding.top + (currentLine * fontMetrics.lineHeight);
                } else {
                    currentX += charWidth;
                    if (currentX >= containerWidth) {
                        currentLine++;
                        currentX = fontMetrics.containerPadding.left + charWidth;
                        currentY = fontMetrics.containerPadding.top + (currentLine * fontMetrics.lineHeight);
                    }
                }

                if (i % 10 === 0) {
                    console.log('🔍 [DEBUG] After character', i, ':', { char, charWidth, currentX, currentY, currentLine });
                }
            }

            console.log('🔍 [DEBUG] Position at start:', { currentX, currentY, currentLine });

            // Now calculate positions for the target text
            let segmentStart = { x: currentX, y: currentY, line: currentLine };
            let lastCharX = currentX;
            let lastCharY = currentY;
            const positions = [];

            for (let i = start; i < end; i++) {
                const char = originalText[i];
                const charWidth = fontMetrics.charWidths[char] || fontMetrics.averageCharWidth;

                console.log('🔍 [DEBUG] Processing character', i, ':', { char, charWidth, currentX, currentY });

                if (char === '\\n') {
                    // End current segment and start new line
                    if (segmentStart.x !== lastCharX || segmentStart.y !== lastCharY) {
                        positions.push({
                            x: segmentStart.x,
                            y: segmentStart.y,
                            width: lastCharX - segmentStart.x,
                            height: fontMetrics.lineHeight,
                            line: segmentStart.line
                        });
                    }

                    currentLine++;
                    currentX = fontMetrics.containerPadding.left;
                    currentY = fontMetrics.containerPadding.top + (currentLine * fontMetrics.lineHeight);
                    segmentStart = { x: currentX, y: currentY, line: currentLine };
                    lastCharX = currentX;
                    lastCharY = currentY;
                } else if (char === ' ') {
                    // Handle spaces - they have width but don't create segments
                    currentX += charWidth;
                    lastCharX = currentX;
                    lastCharY = currentY;
                } else {
                    currentX += charWidth;
                    if (currentX >= containerWidth) {
                        // End current segment and wrap to next line
                        if (segmentStart.x !== lastCharX || segmentStart.y !== lastCharY) {
                            positions.push({
                                x: segmentStart.x,
                                y: segmentStart.y,
                                width: lastCharX - segmentStart.x,
                                height: fontMetrics.lineHeight,
                                line: segmentStart.line
                            });
                        }

                        currentLine++;
                        currentX = fontMetrics.containerPadding.left + charWidth;
                        currentY = fontMetrics.containerPadding.top + (currentLine * fontMetrics.lineHeight);
                        segmentStart = { x: fontMetrics.containerPadding.left, y: currentY, line: currentLine };
                    }

                    lastCharX = currentX;
                    lastCharY = currentY;
                }
            }

            // Add final segment if it has content
            if (segmentStart.x !== lastCharX || segmentStart.y !== lastCharY || start === end - 1) {
                const width = Math.max(lastCharX - segmentStart.x, fontMetrics.averageCharWidth);
                positions.push({
                    x: segmentStart.x,
                    y: segmentStart.y,
                    width: width,
                    height: fontMetrics.lineHeight,
                    line: segmentStart.line
                });
            }

            return {
                originalTextLength: originalText.length,
                targetText: targetText,
                targetTextLength: targetText.length,
                start: start,
                end: end,
                containerWidth: containerWidth,
                positions: positions,
                positionsLength: positions.length,
                finalPosition: { currentX, currentY, currentLine },
                segmentStart: segmentStart,
                lastChar: { x: lastCharX, y: lastCharY }
            };
        """)

        print(f"🔍 [DEBUG] Positioning Algorithm Debug Results: {debug_result}")

        # Basic assertions
        self.assertIsNotNone(debug_result['originalTextLength'], "Original text length should not be null")
        self.assertIsNotNone(debug_result['targetText'], "Target text should not be null")
        self.assertGreater(debug_result['originalTextLength'], 0, "Original text should have length > 0")
        self.assertGreater(debug_result['targetTextLength'], 0, "Target text should have length > 0")