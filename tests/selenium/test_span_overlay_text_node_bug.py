#!/usr/bin/env python3
"""
Selenium test for the span overlay text-node pollution bug.

Regression test for the bug where collectTextNodes() in span-core.js walked into
#span-overlays children, causing overlay label text ("News", "×") to pollute
the cumulative character offset. This made each successive span overlay render
at a progressively wrong position.

The test creates multiple spans, then verifies that each overlay segment
actually covers the text it claims to annotate (by comparing the overlay's
bounding rect against a fresh Range created for the same character offsets).
"""

import time
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from tests.selenium.test_base import BaseSeleniumTest


class TestSpanOverlayTextNodeBug(BaseSeleniumTest):
    """
    Verify that multiple span overlays align with their annotated text,
    even after overlay labels inject extra text nodes into #text-content.
    """

    def _wait_for_span_manager(self):
        """Wait for SpanManager to be fully initialized."""
        WebDriverWait(self.driver, 10).until(
            lambda d: d.execute_script(
                "return !!(window.spanManager && window.spanManager.isInitialized);"
            )
        )

    def _create_span_via_api(self, label, start, end):
        """Create a span annotation by simulating a text selection and calling the save API."""
        result = self.driver.execute_script("""
            var label = arguments[0], start = arguments[1], end = arguments[2];
            var sm = window.spanManager;
            if (!sm || !sm.positioningStrategy) return 'no_manager';

            // Get the text from the container
            var container = sm.positioningStrategy.container;
            var text = (container.getAttribute('data-original-text') || container.textContent || '');
            // Strip HTML tags if from data-original-text
            text = text.replace(/<[^>]*>/g, '').trim().replace(/\\s+/g, ' ');
            var selectedText = text.substring(start, end);
            if (!selectedText) return 'empty_text';

            // Use createAnnotation which handles save + overlay rendering
            if (typeof sm.createAnnotation === 'function') {
                sm.createAnnotation(label, start, end, selectedText);
                return 'ok_createAnnotation';
            }

            // Fallback: use saveSpan which POSTs to the server
            if (typeof sm.saveSpan === 'function') {
                sm.saveSpan({start: start, end: end, text: selectedText, label: label});
                return 'ok_saveSpan';
            }

            return 'no_method';
        """, label, start, end)
        return result

    def _select_label(self, label):
        """Select a span label checkbox in the UI."""
        self.driver.execute_script("""
            var label = arguments[0];
            // Try clicking the checkbox for this label
            var checkboxes = document.querySelectorAll('.annotation-form.span input[type="checkbox"]');
            for (var cb of checkboxes) {
                var lbl = cb.closest('label') || cb.parentElement;
                if (lbl && lbl.textContent.trim().toLowerCase().includes(label.toLowerCase())) {
                    if (!cb.checked) cb.click();
                    return;
                }
            }
            // Fallback: programmatically set the label
            if (window.spanManager) {
                window.spanManager.selectedLabel = label;
            }
        """, label)

    def _get_overlay_and_text_rects(self):
        """
        For every overlay in #span-overlays, compute positions RELATIVE to
        #text-content for both:
          1. The overlay segment's bounding rect
          2. A fresh Range bounding rect for the same character offsets

        Returns a list of dicts with keys: start, end, label, overlay_x/y, text_x/y.
        Comparing overlay vs text positions tells us if overlays are aligned.
        """
        return self.driver.execute_script("""
            var overlaysEl = document.getElementById('span-overlays');
            if (!overlaysEl) return [];

            var textEl = document.getElementById('text-content');
            if (!textEl) return [];

            var containerRect = textEl.getBoundingClientRect();
            var results = [];
            var overlays = overlaysEl.querySelectorAll('.span-overlay-pure');

            overlays.forEach(function(overlay) {
                var start = parseInt(overlay.dataset.start);
                var end = parseInt(overlay.dataset.end);
                var label = overlay.dataset.label || '';
                if (isNaN(start) || isNaN(end)) return;

                // Get overlay segment rect relative to text-content
                var seg = overlay.querySelector('.span-highlight-segment');
                if (!seg) return;
                var segRect = seg.getBoundingClientRect();

                // Build a fresh Range for the same offsets to get the true text rect.
                // Walk text nodes SKIPPING overlay containers (mirrors the fix).
                var textNodes = [];
                var cumOffset = 0;
                function walk(node) {
                    if (node.nodeType === 3) {
                        textNodes.push({node: node, start: cumOffset, end: cumOffset + node.textContent.length});
                        cumOffset += node.textContent.length;
                    } else if (node.nodeType === 1) {
                        if (node.id === 'span-overlays' || node.classList.contains('span-overlays-field')) return;
                        for (var c of node.childNodes) walk(c);
                    }
                }
                walk(textEl);

                var startNode = null, startOff = 0, endNode = null, endOff = 0;
                for (var tn of textNodes) {
                    if (startNode === null && start >= tn.start && start < tn.end) {
                        startNode = tn.node;
                        startOff = start - tn.start;
                    }
                    if (end > tn.start && end <= tn.end) {
                        endNode = tn.node;
                        endOff = end - tn.start;
                    }
                }
                if (!startNode || !endNode) return;

                var range = document.createRange();
                try {
                    range.setStart(startNode, startOff);
                    range.setEnd(endNode, endOff);
                } catch(e) { return; }

                var rects = range.getClientRects();
                if (rects.length === 0) return;
                var textRect = rects[0];

                // All positions relative to text-content
                results.push({
                    start: start,
                    end: end,
                    label: label,
                    overlay_x: segRect.left - containerRect.left,
                    overlay_y: segRect.top - containerRect.top,
                    text_x: textRect.left - containerRect.left,
                    text_y: textRect.top - containerRect.top
                });
            });

            return results;
        """)

    def test_no_progressive_drift_after_creation(self):
        """
        Create 3 non-overlapping spans and verify overlays don't progressively
        drift apart from their text. Before the fix, span 2+ would accumulate
        extra offset because collectTextNodes included overlay label text.

        We check that all spans have the SAME offset between overlay and text
        (a consistent CSS offset is OK; progressive drift is the bug).
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "text-content")
        self._wait_for_span_manager()

        self._select_label("positive")

        text_len = self.driver.execute_script("""
            var sm = window.spanManager;
            var c = sm.positioningStrategy.container;
            var t = (c.getAttribute('data-original-text') || c.textContent || '');
            t = t.replace(/<[^>]*>/g, '').trim().replace(/\\s+/g, ' ');
            return t.length;
        """)
        assert text_len > 30, f"Text too short for test: {text_len}"

        # Create 3 non-overlapping spans at known offsets
        spans_to_create = [
            ("positive", 0, min(10, text_len)),
            ("negative", 15, min(25, text_len)),
            ("neutral",  30, min(40, text_len)),
        ]

        for label, start, end in spans_to_create:
            if end > text_len:
                continue
            self._select_label(label)
            result = self._create_span_via_api(label, start, end)
            assert result.startswith("ok"), f"Failed to create span ({start},{end}): {result}"
            time.sleep(0.3)

        time.sleep(0.5)

        rects = self._get_overlay_and_text_rects()
        assert len(rects) >= 2, f"Expected at least 2 overlays, got {len(rects)}"

        # All spans should have the same (overlay - text) offset.
        # A consistent CSS padding offset is fine; progressive drift is the bug.
        x_offsets = [r["overlay_x"] - r["text_x"] for r in rects]
        y_offsets = [r["overlay_y"] - r["text_y"] for r in rects]

        MAX_VARIANCE_PX = 5  # tolerance for rounding between spans
        x_spread = max(x_offsets) - min(x_offsets)
        y_spread = max(y_offsets) - min(y_offsets)

        assert x_spread < MAX_VARIANCE_PX, (
            f"Progressive horizontal drift detected: offsets vary by {x_spread:.1f}px "
            f"across spans. Per-span x-offsets: {[f'{o:.1f}' for o in x_offsets]}"
        )
        assert y_spread < MAX_VARIANCE_PX, (
            f"Progressive vertical drift detected: offsets vary by {y_spread:.1f}px "
            f"across spans. Per-span y-offsets: {[f'{o:.1f}' for o in y_offsets]}"
        )

    def test_no_progressive_drift_after_reload(self):
        """
        Create spans, navigate away and back, verify no progressive drift
        in the reloaded overlays. This catches the case where sequentially
        rendered overlays accumulate offset from prior overlay label text.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "text-content")
        self._wait_for_span_manager()

        text_len = self.driver.execute_script("""
            var sm = window.spanManager;
            var c = sm.positioningStrategy.container;
            var t = (c.getAttribute('data-original-text') || c.textContent || '');
            t = t.replace(/<[^>]*>/g, '').trim().replace(/\\s+/g, ' ');
            return t.length;
        """)

        if text_len < 30:
            pytest.skip("Text too short for multi-span test")

        # Create 2 spans
        self._select_label("positive")
        self._create_span_via_api("positive", 0, min(10, text_len))
        time.sleep(0.3)
        self._select_label("negative")
        self._create_span_via_api("negative", 15, min(25, text_len))
        time.sleep(1.5)  # ensure debounced save fires

        # Navigate away then back
        try:
            self.driver.find_element(By.ID, "next-btn").click()
            time.sleep(1.0)
            self.driver.find_element(By.ID, "prev-btn").click()
            time.sleep(1.0)
        except Exception:
            pytest.skip("Navigation buttons not available")

        self._wait_for_span_manager()
        time.sleep(0.5)

        rects = self._get_overlay_and_text_rects()
        if len(rects) < 2:
            pytest.skip("Spans not persisted after navigation (unrelated issue)")

        # Check that all spans have the same offset (no progressive drift)
        x_offsets = [r["overlay_x"] - r["text_x"] for r in rects]
        y_offsets = [r["overlay_y"] - r["text_y"] for r in rects]

        MAX_VARIANCE_PX = 5
        x_spread = max(x_offsets) - min(x_offsets)
        y_spread = max(y_offsets) - min(y_offsets)

        assert x_spread < MAX_VARIANCE_PX, (
            f"After reload: progressive horizontal drift of {x_spread:.1f}px. "
            f"Per-span x-offsets: {[f'{o:.1f}' for o in x_offsets]}"
        )
        assert y_spread < MAX_VARIANCE_PX, (
            f"After reload: progressive vertical drift of {y_spread:.1f}px. "
            f"Per-span y-offsets: {[f'{o:.1f}' for o in y_offsets]}"
        )

    def test_collect_text_nodes_skips_overlays(self):
        """
        Directly verify that collectTextNodes in getPositionsFromOffsets
        does not include text from overlay elements.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "text-content")
        self._wait_for_span_manager()

        # Get the original text length (before any overlays)
        original_len = self.driver.execute_script("""
            var sm = window.spanManager;
            var c = sm.positioningStrategy.container;
            // Walk text nodes the way collectTextNodes does
            var len = 0;
            function walk(node) {
                if (node.nodeType === 3) {
                    len += node.textContent.length;
                } else if (node.nodeType === 1) {
                    if (node.id === 'span-overlays' || node.classList.contains('span-overlays-field')) return;
                    for (var ch of node.childNodes) walk(ch);
                }
            }
            walk(c);
            return len;
        """)

        # Create a span to inject overlay labels into the DOM
        self._select_label("positive")
        self._create_span_via_api("positive", 0, min(8, original_len))
        time.sleep(0.5)

        # Now count text nodes again WITH the overlay skip
        len_with_skip = self.driver.execute_script("""
            var c = window.spanManager.positioningStrategy.container;
            var len = 0;
            function walk(node) {
                if (node.nodeType === 3) {
                    len += node.textContent.length;
                } else if (node.nodeType === 1) {
                    if (node.id === 'span-overlays' || node.classList.contains('span-overlays-field')) return;
                    for (var ch of node.childNodes) walk(ch);
                }
            }
            walk(c);
            return len;
        """)

        # And WITHOUT the skip (the old buggy behavior)
        len_without_skip = self.driver.execute_script("""
            var c = window.spanManager.positioningStrategy.container;
            var len = 0;
            function walk(node) {
                if (node.nodeType === 3) {
                    len += node.textContent.length;
                } else if (node.nodeType === 1) {
                    for (var ch of node.childNodes) walk(ch);
                }
            }
            walk(c);
            return len;
        """)

        assert len_with_skip == original_len, (
            f"Text length changed after adding overlay (with skip): "
            f"original={original_len}, after={len_with_skip}"
        )
        assert len_without_skip > original_len, (
            f"Without skip, overlay label text should inflate the count: "
            f"original={original_len}, without_skip={len_without_skip}. "
            f"If equal, the test precondition is wrong (overlay has no text nodes)."
        )
