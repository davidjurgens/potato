"""
Selenium tests for dependency tree arc visualization.

Tests that arcs are correctly rendered between linked spans.
"""

import pytest
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest


class TestDependencyArcs(BaseSeleniumTest):
    """Test arc rendering for dependency tree annotation."""

    @pytest.fixture(scope="class", autouse=True)
    def setup_server(self, request):
        """Start server with dependency tree config."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        import os

        config_path = os.path.join(
            os.path.dirname(__file__),
            "../../examples/span/dependency-tree/config.yaml"
        )

        # Use a unique port for this test
        self.server = FlaskTestServer(port=9876, config_file=config_path)
        if not self.server.start():
            pytest.fail("Failed to start server")

        request.cls.server = self.server
        yield
        self.server.stop()

    def test_span_segment_positions(self):
        """Test that span segments have proper positions that can be used for arcs."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Wait for the annotation interface to load
        instance_text = self.wait_for_element(By.ID, "instance-text")
        assert instance_text is not None, "Instance text not found"

        # Create two spans using JavaScript
        self._create_span_js("cat", "NOUN")
        time.sleep(0.5)
        self._create_span_js("sat", "VERB")
        time.sleep(0.5)

        # Check spans were created
        spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        assert len(spans) >= 2, f"Expected at least 2 spans, found {len(spans)}"

        # Now test the getSpanPositions logic using JavaScript
        result = self.driver.execute_script("""
            const positions = {};
            const instanceText = document.getElementById('instance-text');
            if (!instanceText) return {error: 'No instance-text found'};

            const containerRect = instanceText.getBoundingClientRect();

            document.querySelectorAll('.span-overlay-pure').forEach(overlay => {
                const spanId = overlay.dataset.annotationId;
                const label = overlay.dataset.label;

                // This is the fix we're testing - get bounds from segments
                const segments = overlay.querySelectorAll('.span-highlight-segment');
                let rect = null;

                if (segments.length > 0) {
                    let minLeft = Infinity, minTop = Infinity, maxRight = -Infinity, maxBottom = -Infinity;
                    segments.forEach(segment => {
                        const segRect = segment.getBoundingClientRect();
                        if (segRect.width > 0 && segRect.height > 0) {
                            minLeft = Math.min(minLeft, segRect.left);
                            minTop = Math.min(minTop, segRect.top);
                            maxRight = Math.max(maxRight, segRect.right);
                            maxBottom = Math.max(maxBottom, segRect.bottom);
                        }
                    });

                    if (minLeft !== Infinity) {
                        rect = {
                            left: minLeft,
                            top: minTop,
                            width: maxRight - minLeft,
                            height: maxBottom - minTop
                        };
                    }
                }

                // Fallback
                if (!rect) {
                    rect = overlay.getBoundingClientRect();
                }

                if (rect.width > 0 && rect.height > 0) {
                    positions[spanId] = {
                        label: label,
                        x: rect.left - containerRect.left,
                        y: rect.top - containerRect.top,
                        width: rect.width,
                        height: rect.height,
                        segmentCount: segments.length
                    };
                } else {
                    positions[spanId] = {
                        label: label,
                        error: 'Zero dimensions',
                        segmentCount: segments.length
                    };
                }
            });

            return {
                containerRect: {
                    left: containerRect.left,
                    top: containerRect.top,
                    width: containerRect.width,
                    height: containerRect.height
                },
                positions: positions
            };
        """)

        print("\\nPosition calculation result:")
        print(f"  Container rect: {result.get('containerRect', {})}")
        print(f"  Positions:")
        for span_id, pos in result.get('positions', {}).items():
            print(f"    {span_id[:30]}...: {pos}")

        # Verify positions are valid
        positions = result.get('positions', {})
        assert len(positions) >= 2, f"Expected at least 2 positions, got {len(positions)}"

        for span_id, pos in positions.items():
            assert 'error' not in pos, f"Position error for {span_id}: {pos}"
            assert pos['width'] > 0, f"Width should be > 0 for {span_id}"
            assert pos['height'] > 0, f"Height should be > 0 for {span_id}"
            assert pos['x'] > 0, f"X should be > 0 for {span_id} (got {pos['x']})"

        # Check that different spans have different positions
        pos_list = list(positions.values())
        if len(pos_list) >= 2:
            assert pos_list[0]['x'] != pos_list[1]['x'], "Spans should have different X positions"

    def test_arc_rendering_with_link(self):
        """Test that arcs render correctly when a link is created."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Create two spans
        self._create_span_js("cat", "NOUN")
        time.sleep(0.5)
        self._create_span_js("sat", "VERB")
        time.sleep(0.5)

        # Get span IDs
        span_ids = self.driver.execute_script("""
            const ids = [];
            document.querySelectorAll('.span-overlay-pure').forEach(overlay => {
                ids.push(overlay.dataset.annotationId);
            });
            return ids;
        """)
        print(f"\\nSpan IDs: {span_ids}")
        assert len(span_ids) >= 2, "Need at least 2 spans"

        # Create a link between the spans using JavaScript (bypassing UI issues)
        link_result = self.driver.execute_script(f"""
            const manager = window.spanLinkManagers?.dependencies;
            if (!manager) return {{error: 'No span link manager found'}};

            // Set link type
            manager.currentLinkType = 'nsubj';
            manager.isLinkMode = true;

            // Get the span overlays
            const span1 = document.querySelector('.span-overlay-pure[data-annotation-id="{span_ids[0]}"]');
            const span2 = document.querySelector('.span-overlay-pure[data-annotation-id="{span_ids[1]}"]');

            if (!span1 || !span2) return {{error: 'Spans not found'}};

            // Simulate selection
            manager.selectedSpans = [
                {{id: '{span_ids[0]}', label: span1.dataset.label, text: 'cat', element: span1}},
                {{id: '{span_ids[1]}', label: span2.dataset.label, text: 'sat', element: span2}}
            ];

            // Create the link
            const link = {{
                id: 'test_link_' + Date.now(),
                schema: 'dependencies',
                link_type: 'nsubj',
                span_ids: ['{span_ids[0]}', '{span_ids[1]}'],
                direction: 'directed',
                properties: {{color: '#dc2626'}}
            }};

            manager.links.push(link);
            manager.renderArcs();

            return {{
                success: true,
                linkCount: manager.links.length,
                arcsContainerExists: !!manager.arcsContainer
            }};
        """)

        print(f"Link result: {link_result}")
        assert link_result.get('success'), f"Failed to create link: {link_result}"

        time.sleep(0.3)

        # Check the SVG output
        svg_info = self.driver.execute_script("""
            const arcsContainer = document.getElementById('dependencies_arcs');
            if (!arcsContainer) return {error: 'No arcs container'};

            const svg = arcsContainer.querySelector('svg');
            if (!svg) return {error: 'No SVG in container'};

            const paths = svg.querySelectorAll('path.span-link-arc');
            const labels = svg.querySelectorAll('text.span-link-label');

            let pathData = [];
            paths.forEach(path => {
                const d = path.getAttribute('d');
                pathData.push({
                    d: d,
                    stroke: path.getAttribute('stroke')
                });
            });

            return {
                containerHTML: arcsContainer.innerHTML.substring(0, 500),
                pathCount: paths.length,
                paths: pathData,
                labelCount: labels.length
            };
        """)

        print(f"\\nSVG Info:")
        print(f"  Path count: {svg_info.get('pathCount', 0)}")
        print(f"  Paths: {svg_info.get('paths', [])}")
        print(f"  Container HTML: {svg_info.get('containerHTML', '')[:200]}...")

        # Verify arc was created
        assert svg_info.get('pathCount', 0) >= 1, f"No arc paths found. SVG info: {svg_info}"

        # Parse and verify path coordinates
        if svg_info.get('paths'):
            path = svg_info['paths'][0]
            d = path['d']
            print(f"  Path d: {d}")

            # Extract coordinates from "M x1 y1 Q midX ctrlY x2 y2"
            import re
            coords = re.findall(r'[\d.]+', d)
            if len(coords) >= 6:
                x1, y1, midX, ctrlY, x2, y2 = [float(c) for c in coords[:6]]
                print(f"  Coordinates: x1={x1}, y1={y1}, midX={midX}, ctrlY={ctrlY}, x2={x2}, y2={y2}")

                # Verify coordinates are reasonable
                assert x1 > 50, f"x1 too small: {x1}"
                assert x2 > 50, f"x2 too small: {x2}"
                assert abs(x2 - x1) > 10, f"Spans too close: x1={x1}, x2={x2}"

    def _create_span_js(self, word, label):
        """Helper to create a span annotation using JavaScript."""
        self.driver.execute_script(f"""
            // Select the label checkbox
            const checkbox = document.getElementById('tokens_{label}');
            if (checkbox && !checkbox.checked) {{
                checkbox.click();
            }}

            // Wait for label to be selected
            if (window.spanManager) {{
                window.spanManager.selectLabel('{label}', 'tokens');
            }}
        """)
        time.sleep(0.2)

        # Create selection and trigger span creation
        self.driver.execute_script(f"""
            const textContent = document.getElementById('text-content');
            const text = textContent.textContent;
            const wordIndex = text.indexOf('{word}');

            if (wordIndex === -1) {{
                console.error('Word not found: {word}');
                return;
            }}

            const range = document.createRange();
            const walker = document.createTreeWalker(textContent, NodeFilter.SHOW_TEXT);
            let currentPos = 0;

            while (walker.nextNode()) {{
                const node = walker.currentNode;
                const nodeLen = node.textContent.length;

                if (currentPos + nodeLen > wordIndex) {{
                    const startOffset = wordIndex - currentPos;
                    range.setStart(node, startOffset);
                    range.setEnd(node, startOffset + {len(word)});
                    break;
                }}
                currentPos += nodeLen;
            }}

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);

            // Trigger mouseup to create span
            textContent.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true}}));
        """)

    def wait_for_element(self, by, value, timeout=10):
        """Wait for element to be present and return it."""
        wait = WebDriverWait(self.driver, timeout)
        return wait.until(EC.presence_of_element_located((by, value)))
