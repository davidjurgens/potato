"""
Selenium test for span link (arc) persistence on page reload.

This test reproduces a bug where arc annotations disappear after page reload
even though the links were saved to the backend.
"""

import pytest
import time
import os
import json
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


class TestSpanLinkPersistence:
    """Test that span links persist across page reloads."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server with the dependency tree config."""
        # Use the dependency tree example config
        config_path = "examples/span/dependency-tree/config.yaml"

        # Get absolute path
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_file = os.path.join(repo_root, config_path)

        # Start server with dynamic port
        port = find_free_port(preferred_port=9494)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options for headless testing
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    @classmethod
    def teardown_class(cls):
        """Clean up the Flask server."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()

    def setup_method(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)

        # Generate unique test user
        timestamp = int(time.time())
        self.test_user = f"test_user_span_link_{timestamp}"

        # Login
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(0.5)

        # Simple login (no password required)
        username_field = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_field.send_keys(self.test_user)
        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()
        time.sleep(1)

    def teardown_method(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def wait_for_element(self, by, value, timeout=10):
        """Wait for an element to be present and return it."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def test_link_persistence_on_reload(self):
        """Test that links persist after page reload."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Wait for the page to load
        self.wait_for_element(By.ID, "instance-text")

        # Log initial state
        print("\n=== STEP 1: Initial page load ===")
        self.log_page_state()

        # Get the instance ID
        instance_id = self.driver.execute_script(
            "return document.getElementById('instance_id')?.value"
        )
        print(f"Instance ID: {instance_id}")

        # STEP 2: Create span annotations via API
        print("\n=== STEP 2: Creating span annotations via API ===")

        # Create first span: "The" at 0-3
        # Format: annotations dict required, span_annotations array with schema, name, start, end, value
        span1_result = self.driver.execute_script("""
            const data = {
                instance_id: arguments[0],
                annotations: {},  // Required for frontend format detection
                span_annotations: [{
                    schema: "tokens",
                    name: "DET",
                    start: 0,
                    end: 3,
                    value: true
                }]
            };
            return fetch('/updateinstance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            }).then(r => r.json());
        """, instance_id)
        print(f"Span 1 result: {span1_result}")
        time.sleep(0.3)

        # Create second span: "cat" at 20-23
        span2_result = self.driver.execute_script("""
            const data = {
                instance_id: arguments[0],
                annotations: {},
                span_annotations: [{
                    schema: "tokens",
                    name: "NOUN",
                    start: 20,
                    end: 23,
                    value: true
                }]
            };
            return fetch('/updateinstance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            }).then(r => r.json());
        """, instance_id)
        print(f"Span 2 result: {span2_result}")
        time.sleep(0.5)

        # Reload to see spans rendered
        self.driver.refresh()
        time.sleep(1.5)
        self.wait_for_element(By.ID, "instance-text")

        # Check spans exist
        span_overlays = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        print(f"Span overlays after reload: {len(span_overlays)}")

        # Get span IDs
        span_ids = []
        for overlay in span_overlays:
            span_id = overlay.get_attribute("data-annotation-id")
            span_label = overlay.get_attribute("data-label")
            print(f"  Found span: id={span_id}, label={span_label}")
            if span_id:
                span_ids.append(span_id)

        if len(span_ids) < 2:
            # Debug: fetch spans from API
            api_spans = self.driver.execute_script("""
                return fetch('/api/spans/' + arguments[0])
                    .then(r => r.json());
            """, instance_id)
            print(f"API spans: {api_spans}")
            pytest.skip(f"Need at least 2 spans, only found {len(span_ids)}")

        # STEP 3: Create a link between the spans
        print("\n=== STEP 3: Creating link between spans ===")

        link_data = {
            "instance_id": instance_id,
            "annotations": {},  # Required for frontend format detection
            "link_annotations": [{
                "id": f"link_test_{int(time.time())}",
                "schema": "dependencies",
                "link_type": "det",
                "span_ids": span_ids[:2],
                "direction": "directed",
                "properties": {
                    "color": "#6b7280"
                }
            }]
        }

        link_result = self.driver.execute_script("""
            return fetch('/updateinstance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(arguments[0])
            }).then(r => r.json());
        """, link_data)
        print(f"Link creation result: {link_result}")
        time.sleep(0.5)

        # STEP 4: Verify arc is visible before reload
        print("\n=== STEP 4: Checking arc visibility BEFORE reload ===")

        # Trigger arc rendering
        self.driver.execute_script("""
            const manager = window.spanLinkManagers && Object.values(window.spanLinkManagers)[0];
            if (manager) {
                manager.loadExistingLinks();
            }
        """)
        time.sleep(1)

        self.log_arc_state()

        links_before = self.driver.execute_script("""
            const manager = window.spanLinkManagers && Object.values(window.spanLinkManagers)[0];
            return manager ? manager.links : [];
        """)
        print(f"Links in manager before reload: {len(links_before)} links")

        # Check API for persisted links
        api_links_before = self.driver.execute_script("""
            return fetch('/api/links/' + arguments[0])
                .then(r => r.json());
        """, instance_id)
        print(f"API links before reload: {api_links_before}")

        # STEP 5: Reload the page
        print("\n=== STEP 5: Reloading page ===")
        self.driver.refresh()
        time.sleep(2)

        # Wait for page to fully load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(1)

        # STEP 6: Check state after reload
        print("\n=== STEP 6: Checking state AFTER reload ===")
        self.log_page_state()
        self.log_arc_state()

        # Check spans still exist
        span_overlays_after = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        print(f"Span overlays after reload: {len(span_overlays_after)}")

        # Check links in manager
        links_after = self.driver.execute_script("""
            const manager = window.spanLinkManagers && Object.values(window.spanLinkManagers)[0];
            if (!manager) return {error: 'No manager found'};
            return {
                linksCount: manager.links.length,
                links: manager.links,
                arcsContainerExists: !!manager.arcsContainer,
                arcSpacerExists: !!manager.arcSpacer,
                arcSpacerHeight: manager.arcSpacer?.style?.height
            };
        """)
        print(f"Manager state after reload: {links_after}")

        # Check API for persisted links
        api_links_after = self.driver.execute_script("""
            return fetch('/api/links/' + arguments[0])
                .then(r => r.json());
        """, instance_id)
        print(f"API links after reload: {api_links_after}")

        # Check for SVG arcs
        arc_paths = self.driver.find_elements(By.CSS_SELECTOR, "svg path")
        arc_containers = self.driver.find_elements(By.CSS_SELECTOR, ".span-link-arcs-container svg")
        print(f"SVG paths found: {len(arc_paths)}")
        print(f"Arc containers found: {len(arc_containers)}")

        if arc_containers:
            svg_content = self.driver.execute_script(
                "return arguments[0].innerHTML", arc_containers[0]
            )
            print(f"SVG content: {svg_content[:300] if svg_content else 'empty'}...")

        # DETAILED VISIBILITY DIAGNOSTICS
        print("\n=== STEP 7: Detailed visibility diagnostics ===")
        visibility_info = self.driver.execute_script("""
            const manager = window.spanLinkManagers && Object.values(window.spanLinkManagers)[0];
            if (!manager) return {error: 'No manager'};

            const result = {
                // Arc spacer visibility
                arcSpacerExists: !!manager.arcSpacer,
                arcSpacerInDOM: manager.arcSpacer ? document.body.contains(manager.arcSpacer) : false,
                arcSpacerDisplay: manager.arcSpacer?.style?.display,
                arcSpacerVisibility: manager.arcSpacer?.style?.visibility,
                arcSpacerComputedDisplay: manager.arcSpacer ? getComputedStyle(manager.arcSpacer).display : null,
                arcSpacerBoundingRect: manager.arcSpacer?.getBoundingClientRect(),

                // Arcs container visibility
                arcsContainerExists: !!manager.arcsContainer,
                arcsContainerInDOM: manager.arcsContainer ? document.body.contains(manager.arcsContainer) : false,
                arcsContainerDisplay: manager.arcsContainer?.style?.display,
                arcsContainerBoundingRect: manager.arcsContainer?.getBoundingClientRect(),

                // SVG visibility
                svgElement: manager.arcsContainer?.querySelector('svg'),
                svgExists: !!manager.arcsContainer?.querySelector('svg'),
                svgBoundingRect: manager.arcsContainer?.querySelector('svg')?.getBoundingClientRect(),

                // Arc path visibility
                arcPaths: [...(manager.arcsContainer?.querySelectorAll('path.span-link-arc') || [])].map(p => ({
                    d: p.getAttribute('d'),
                    stroke: p.getAttribute('stroke'),
                    strokeWidth: p.getAttribute('stroke-width'),
                    boundingRect: p.getBoundingClientRect()
                })),

                // Span positions (critical for arc rendering)
                spanPositions: manager.getSpanPositions(),

                // Text wrapper state
                textWrapperExists: !!manager.textWrapper,
                textWrapperInDOM: manager.textWrapper ? document.body.contains(manager.textWrapper) : false,
                textWrapperBoundingRect: manager.textWrapper?.getBoundingClientRect(),

                // Instance text state (parent container)
                instanceTextBoundingRect: document.getElementById('instance-text')?.getBoundingClientRect()
            };

            return result;
        """)

        print(f"Arc spacer in DOM: {visibility_info.get('arcSpacerInDOM')}")
        print(f"Arc spacer display: {visibility_info.get('arcSpacerComputedDisplay')}")
        print(f"Arc spacer bounds: {visibility_info.get('arcSpacerBoundingRect')}")
        print(f"Arcs container in DOM: {visibility_info.get('arcsContainerInDOM')}")
        print(f"Arcs container bounds: {visibility_info.get('arcsContainerBoundingRect')}")
        print(f"SVG exists: {visibility_info.get('svgExists')}")
        print(f"SVG bounds: {visibility_info.get('svgBoundingRect')}")
        print(f"Arc paths: {visibility_info.get('arcPaths')}")
        print(f"Span positions: {visibility_info.get('spanPositions')}")
        print(f"Text wrapper in DOM: {visibility_info.get('textWrapperInDOM')}")
        print(f"Text wrapper bounds: {visibility_info.get('textWrapperBoundingRect')}")

        # ASSERTIONS
        # 1. Links should be loaded from API
        api_link_count = len(api_links_after.get('links', []))
        assert api_link_count > 0, f"Links not persisted to API. API response: {api_links_after}"

        # 2. Links should be in the manager
        manager_link_count = links_after.get('linksCount', 0)
        assert manager_link_count > 0, f"Links not loaded into manager. Manager state: {links_after}"

        # 3. Arc spacer should be visible with non-zero dimensions
        arc_spacer_rect = visibility_info.get('arcSpacerBoundingRect', {})
        spacer_height = arc_spacer_rect.get('height', 0) if arc_spacer_rect else 0
        assert spacer_height > 0, f"Arc spacer has zero height! Bounds: {arc_spacer_rect}"

        # 4. Arc paths should exist with class span-link-arc
        arc_path_count = len(visibility_info.get('arcPaths', []))
        assert arc_path_count > 0, f"No arc paths with class span-link-arc found"

        # 5. Arc paths should have valid bounding rects (non-zero dimensions)
        for i, path_info in enumerate(visibility_info.get('arcPaths', [])):
            path_rect = path_info.get('boundingRect', {})
            path_width = path_rect.get('width', 0) if path_rect else 0
            path_height = path_rect.get('height', 0) if path_rect else 0
            assert path_width > 0 and path_height > 0, f"Arc path {i} has zero dimensions: {path_rect}"
            print(f"Arc path {i} dimensions: {path_width}x{path_height}")

        # 6. Span positions should be non-empty for arc rendering
        span_positions = visibility_info.get('spanPositions', {})
        assert len(span_positions) >= 2, f"Need at least 2 span positions for arcs, got: {span_positions}"

        # 7. Take a screenshot for visual verification
        screenshot_path = os.path.join(os.path.dirname(__file__), "arc_persistence_screenshot.png")
        self.driver.save_screenshot(screenshot_path)
        print(f"\nScreenshot saved to: {screenshot_path}")

    def log_page_state(self):
        """Log the current page state for debugging."""
        state = self.driver.execute_script("""
            return {
                instanceId: document.getElementById('instance_id')?.value,
                hasSpanManager: !!window.spanManager,
                hasSpanLinkManagers: !!window.spanLinkManagers,
                spanLinkManagerCount: window.spanLinkManagers ? Object.keys(window.spanLinkManagers).length : 0,
                spanOverlays: document.querySelectorAll('.span-overlay-pure').length,
                textContent: document.getElementById('text-content')?.textContent?.substring(0, 50)
            };
        """)
        print(f"Page state: {state}")

    def log_arc_state(self):
        """Log the arc rendering state for debugging."""
        state = self.driver.execute_script("""
            const manager = window.spanLinkManagers && Object.values(window.spanLinkManagers)[0];
            if (!manager) return {error: 'No span link manager'};

            let spanPositions = {};
            try {
                spanPositions = manager.getSpanPositions ? manager.getSpanPositions() : 'method not found';
            } catch(e) {
                spanPositions = {error: e.toString()};
            }

            return {
                schemaName: manager.schemaName,
                linksCount: manager.links.length,
                links: manager.links,
                hasArcsContainer: !!manager.arcsContainer,
                arcsContainerHTML: manager.arcsContainer?.innerHTML?.substring(0, 300),
                hasArcSpacer: !!manager.arcSpacer,
                arcSpacerHeight: manager.arcSpacer?.style?.height,
                hasTextWrapper: !!manager.textWrapper,
                spanPositions: spanPositions
            };
        """)
        print(f"Arc state: {state}")
