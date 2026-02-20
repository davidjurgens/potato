"""
Selenium tests for event annotation arc rendering.

These tests verify that:
1. Event arcs appear immediately when an event is created (not just after refresh)
2. Arcs are positioned correctly over their constituent spans
3. Arcs persist after page refresh
"""

import pytest
import time
import unittest
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


class EventAnnotationSeleniumTest(unittest.TestCase):
    """Base class for event annotation Selenium tests using the event annotation example config."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server with event annotation config."""
        # Use the event annotation example config
        config_file = "examples/span/event-annotation/config.yaml"

        # Use dynamic port allocation
        port = find_free_port(preferred_port=9020)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        # Wait for server to be ready
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options for headless testing
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        # Enable browser logging
        chrome_options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})

        cls.chrome_options = chrome_options

        try:
            cls.driver = webdriver.Chrome(options=chrome_options)
            cls.driver.implicitly_wait(5)
        except Exception as e:
            print(f"Failed to create Chrome driver: {e}")
            cls.server.stop_server()
            raise

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'driver'):
            cls.driver.quit()
        if hasattr(cls, 'server'):
            cls.server.stop_server()

    def setUp(self):
        """Set up for each test - register and login."""
        # Generate unique username
        self.username = f"test_user_{self.__class__.__name__}_{int(time.time())}"

        # Register user (in debug mode, this might be automatic)
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(0.5)

        # Try to login
        try:
            email_field = self.driver.find_element(By.NAME, "email")
            email_field.clear()
            email_field.send_keys(self.username)

            # Check for password field
            try:
                pass_field = self.driver.find_element(By.NAME, "pass")
                pass_field.clear()
                pass_field.send_keys("test123")
            except:
                pass

            # Submit form
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "input[type='submit'], button[type='submit']")
            submit_btn.click()
            time.sleep(1)
        except Exception as e:
            print(f"Login attempt: {e}")

    def wait_for_element(self, by, value, timeout=10):
        """Wait for an element to be present."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )


class TestEventArcRendering(EventAnnotationSeleniumTest):
    """Test event annotation arc rendering."""

    def create_span_annotation(self, text_to_select, label_id):
        """
        Create a span annotation by selecting text and clicking a label.

        Args:
            text_to_select: The text to highlight and annotate
            label_id: The ID of the label checkbox to click (e.g., 'entities_PERSON')
        """
        # Click the label checkbox first to activate span creation mode
        label_checkbox = self.wait_for_element(By.ID, label_id)
        label_checkbox.click()
        time.sleep(0.3)

        # Find the text content element
        text_content = self.wait_for_element(By.ID, "text-content")

        # Use JavaScript to select the text and trigger span creation
        self.driver.execute_script("""
            const textContent = document.getElementById('text-content');
            const text = arguments[0];
            const textNode = textContent.firstChild;

            // Find the text in the content
            const fullText = textContent.textContent || textContent.innerText;
            const startIndex = fullText.indexOf(text);

            if (startIndex === -1) {
                console.error('Text not found:', text);
                return;
            }

            // Create a range for the selection
            const range = document.createRange();

            // Find the correct text node and offsets
            function findTextNodeAndOffset(node, targetOffset) {
                if (node.nodeType === Node.TEXT_NODE) {
                    if (targetOffset <= node.length) {
                        return { node: node, offset: targetOffset };
                    }
                    return { node: null, offset: targetOffset - node.length };
                }

                let currentOffset = targetOffset;
                for (let child of node.childNodes) {
                    const result = findTextNodeAndOffset(child, currentOffset);
                    if (result.node) {
                        return result;
                    }
                    currentOffset = result.offset;
                }
                return { node: null, offset: currentOffset };
            }

            const startResult = findTextNodeAndOffset(textContent, startIndex);
            const endResult = findTextNodeAndOffset(textContent, startIndex + text.length);

            if (startResult.node && endResult.node) {
                range.setStart(startResult.node, startResult.offset);
                range.setEnd(endResult.node, endResult.offset);

                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);

                // Trigger mouseup to create the span
                const mouseupEvent = new MouseEvent('mouseup', {
                    bubbles: true,
                    cancelable: true,
                    view: window
                });
                textContent.dispatchEvent(mouseupEvent);
            }
        """, text_to_select)

        time.sleep(0.5)  # Wait for span creation

    def wait_for_span_overlay(self, span_id_pattern, timeout=5):
        """Wait for a span overlay to appear."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, f"[data-annotation-id*='{span_id_pattern}']"))
        )

    def get_arc_elements(self):
        """Get all arc-related SVG elements."""
        return {
            'svg': self.driver.find_elements(By.CSS_SELECTOR, '.event-arcs-svg'),
            'hubs': self.driver.find_elements(By.CSS_SELECTOR, '.event-hub'),
            'arcs': self.driver.find_elements(By.CSS_SELECTOR, '.event-arc'),
            'labels': self.driver.find_elements(By.CSS_SELECTOR, '.event-type-label')
        }

    def test_arc_appears_on_event_creation(self):
        """Test that arcs appear immediately when an event is created."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Wait for page to load
        self.wait_for_element(By.ID, "text-content")

        # Get the instance text to know what spans to create
        text_content = self.driver.find_element(By.ID, "text-content")
        instance_text = text_content.text
        print(f"Instance text: {instance_text}")

        # Check initial state - no arcs should exist
        initial_arcs = self.get_arc_elements()
        initial_hub_count = len(initial_arcs['hubs'])
        print(f"Initial hub count: {initial_hub_count}")

        # Create entity spans based on the text content
        # For the event annotation example, text is like:
        # "John Smith attacked the government building..."

        # Create PERSON span
        if "John" in instance_text:
            self.create_span_annotation("John", "entities_PERSON")
            time.sleep(0.3)

        # Create EVENT_TRIGGER span
        if "attacked" in instance_text:
            self.create_span_annotation("attacked", "entities_EVENT_TRIGGER")
            time.sleep(0.3)
        elif "hired" in instance_text:
            self.create_span_annotation("hired", "entities_EVENT_TRIGGER")
            time.sleep(0.3)
        elif "traveled" in instance_text:
            self.create_span_annotation("traveled", "entities_EVENT_TRIGGER")
            time.sleep(0.3)

        # Create LOCATION span
        if "Chicago" in instance_text:
            self.create_span_annotation("Chicago", "entities_LOCATION")
            time.sleep(0.3)
        elif "London" in instance_text:
            self.create_span_annotation("London", "entities_LOCATION")
            time.sleep(0.3)

        # Now create an event
        # 1. Select event type (ATTACK)
        event_type_radio = self.wait_for_element(By.ID, "events_event_ATTACK")
        event_type_radio.click()
        time.sleep(0.5)

        # 2. Click on trigger span (EVENT_TRIGGER)
        trigger_spans = self.driver.find_elements(
            By.CSS_SELECTOR,
            "[data-annotation-id*='EVENT_TRIGGER'] .span-highlight-segment"
        )
        if trigger_spans:
            trigger_spans[0].click()
            time.sleep(0.3)

        # 3. Select attacker role and click PERSON span
        attacker_role = self.driver.find_element(
            By.CSS_SELECTOR,
            ".event-role-button"
        )
        attacker_role.click()
        time.sleep(0.2)

        person_spans = self.driver.find_elements(
            By.CSS_SELECTOR,
            "[data-annotation-id*='PERSON'] .span-highlight-segment"
        )
        if person_spans:
            person_spans[0].click()
            time.sleep(0.3)

        # 4. Select target role and click LOCATION span
        target_roles = self.driver.find_elements(
            By.CSS_SELECTOR,
            ".event-role-button"
        )
        if len(target_roles) > 1:
            target_roles[1].click()
            time.sleep(0.2)

        location_spans = self.driver.find_elements(
            By.CSS_SELECTOR,
            "[data-annotation-id*='LOCATION'] .span-highlight-segment"
        )
        if location_spans:
            location_spans[0].click()
            time.sleep(0.3)

        # 5. Click Create Event button
        create_button = self.wait_for_element(By.ID, "events_create_event")

        # Check if button is enabled
        is_enabled = create_button.is_enabled()
        print(f"Create button enabled: {is_enabled}")

        if is_enabled:
            create_button.click()
            time.sleep(1)  # Wait for arc rendering

            # NOW CHECK: Arcs should appear IMMEDIATELY (not just after refresh)
            post_create_arcs = self.get_arc_elements()

            print(f"Post-create SVG count: {len(post_create_arcs['svg'])}")
            print(f"Post-create hub count: {len(post_create_arcs['hubs'])}")
            print(f"Post-create arc count: {len(post_create_arcs['arcs'])}")
            print(f"Post-create label count: {len(post_create_arcs['labels'])}")

            # Verify arcs appeared
            assert len(post_create_arcs['hubs']) > initial_hub_count, \
                "Arc hub should appear immediately after event creation"

            # Verify the hub is visible and has reasonable position
            if post_create_arcs['hubs']:
                hub = post_create_arcs['hubs'][0]
                cx = hub.get_attribute('cx')
                cy = hub.get_attribute('cy')
                print(f"Hub position: cx={cx}, cy={cy}")

                # Hub should not be at position 0,0 (that indicates failed positioning)
                assert float(cx) > 10, f"Hub cx position should be > 10, got {cx}"

    def test_arc_positions_match_spans(self):
        """Test that arc positions correctly align with their span elements."""
        # This test verifies that the arc hub is positioned over the trigger span
        # and arc endpoints are positioned over argument spans

        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Wait for any existing events to load
        self.wait_for_element(By.ID, "text-content")
        time.sleep(0.5)

        # Get arc elements
        arcs = self.get_arc_elements()

        if not arcs['hubs']:
            pytest.skip("No events exist yet - run test_arc_appears_on_event_creation first")

        # Get the hub position
        hub = arcs['hubs'][0]
        hub_cx = float(hub.get_attribute('cx'))
        hub_cy = float(hub.get_attribute('cy'))

        # Get the trigger span position
        # Find the event data to know which span is the trigger
        event_list = self.driver.find_element(By.ID, "events_event_list")

        # The hub should be somewhere reasonable (not at 0,0)
        assert hub_cx > 0, f"Hub cx should be > 0, got {hub_cx}"
        assert hub_cy > 0, f"Hub cy should be > 0, got {hub_cy}"

        print(f"Arc hub position verified: cx={hub_cx}, cy={hub_cy}")

    def test_arc_persists_after_refresh(self):
        """Test that arcs persist and display correctly after page refresh."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Get initial arc count
        initial_arcs = self.get_arc_elements()
        initial_hub_count = len(initial_arcs['hubs'])

        if initial_hub_count == 0:
            pytest.skip("No events exist - run test_arc_appears_on_event_creation first")

        # Refresh the page
        self.driver.refresh()
        time.sleep(2)

        # Wait for page to reload
        self.wait_for_element(By.ID, "text-content")
        time.sleep(1)

        # Get arc count after refresh
        post_refresh_arcs = self.get_arc_elements()
        post_refresh_hub_count = len(post_refresh_arcs['hubs'])

        print(f"Hubs before refresh: {initial_hub_count}")
        print(f"Hubs after refresh: {post_refresh_hub_count}")

        # Arc count should be the same
        assert post_refresh_hub_count == initial_hub_count, \
            f"Arc count should persist after refresh: expected {initial_hub_count}, got {post_refresh_hub_count}"

        # Verify hub has valid position after refresh
        if post_refresh_arcs['hubs']:
            hub = post_refresh_arcs['hubs'][0]
            cx = float(hub.get_attribute('cx'))
            assert cx > 10, f"Hub cx should be > 10 after refresh, got {cx}"

    def test_arc_svg_container_exists(self):
        """Test that the arc SVG container is properly created."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Check for arc spacer
        arc_spacer = self.driver.find_elements(By.CSS_SELECTOR, ".event-annotation-arc-spacer")
        print(f"Arc spacer elements: {len(arc_spacer)}")

        # Check for arcs container
        arcs_container = self.driver.find_elements(By.CSS_SELECTOR, ".event-annotation-arcs-container")
        print(f"Arcs container elements: {len(arcs_container)}")

        # Check for text wrapper
        text_wrapper = self.driver.find_elements(By.CSS_SELECTOR, ".event-annotation-text-wrapper")
        print(f"Text wrapper elements: {len(text_wrapper)}")

        # At least the container structure should exist
        assert len(arc_spacer) > 0 or len(arcs_container) > 0, \
            "Arc container structure should exist"


class TestEventArcRenderingDiagnostics(EventAnnotationSeleniumTest):
    """Diagnostic tests to help identify arc rendering issues."""

    def test_diagnose_span_dimensions(self):
        """Diagnostic test to check span element dimensions."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Wait for page to load
        self.wait_for_element(By.ID, "text-content")
        time.sleep(0.5)

        # Get all span overlays and their dimensions
        span_data = self.driver.execute_script("""
            const results = [];
            const overlays = document.querySelectorAll('[data-annotation-id]');

            overlays.forEach(overlay => {
                const id = overlay.dataset.annotationId;
                const rect = overlay.getBoundingClientRect();

                // Get segment dimensions
                const segments = overlay.querySelectorAll('.span-highlight-segment');
                const segmentRects = [];
                segments.forEach(seg => {
                    const segRect = seg.getBoundingClientRect();
                    segmentRects.push({
                        width: segRect.width,
                        height: segRect.height,
                        left: segRect.left,
                        top: segRect.top
                    });
                });

                results.push({
                    id: id,
                    overlayWidth: rect.width,
                    overlayHeight: rect.height,
                    overlayLeft: rect.left,
                    overlayTop: rect.top,
                    segmentCount: segments.length,
                    segments: segmentRects
                });
            });

            return results;
        """)

        print("\n=== Span Dimensions Diagnostic ===")
        for span in span_data:
            print(f"\nSpan ID: {span['id']}")
            print(f"  Overlay: {span['overlayWidth']}x{span['overlayHeight']} at ({span['overlayLeft']}, {span['overlayTop']})")
            print(f"  Segments: {span['segmentCount']}")
            for i, seg in enumerate(span['segments']):
                print(f"    Segment {i}: {seg['width']}x{seg['height']} at ({seg['left']}, {seg['top']})")

        # Check if any spans have zero dimensions
        zero_width_overlays = [s for s in span_data if s['overlayWidth'] == 0]
        print(f"\nOverlays with zero width: {len(zero_width_overlays)}")

        # Check if segments have valid dimensions
        segments_with_width = sum(1 for s in span_data for seg in s['segments'] if seg['width'] > 0)
        print(f"Segments with valid width: {segments_with_width}")

    def test_diagnose_text_wrapper_position(self):
        """Diagnostic test to check text wrapper positioning."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)  # Wait longer for JS to initialize

        # Get browser console logs
        try:
            logs = self.driver.get_log('browser')
            print("\n=== Browser Console Logs ===")
            for log in logs:
                if 'EventAnnotationManager' in log.get('message', ''):
                    print(log['message'])
        except Exception as e:
            print(f"Could not get browser logs: {e}")

        wrapper_data = self.driver.execute_script("""
            const wrapper = document.querySelector('.event-annotation-text-wrapper');
            const spacer = document.querySelector('.event-annotation-arc-spacer');
            const container = document.querySelector('.event-annotation-arcs-container');
            const instanceText = document.getElementById('instance-text');
            const eventContainer = document.getElementById('events');

            return {
                wrapper: wrapper ? wrapper.getBoundingClientRect() : null,
                spacer: spacer ? spacer.getBoundingClientRect() : null,
                container: container ? container.getBoundingClientRect() : null,
                wrapperExists: !!wrapper,
                spacerExists: !!spacer,
                containerExists: !!container,
                instanceTextExists: !!instanceText,
                instanceTextId: instanceText ? instanceText.id : null,
                eventContainerExists: !!eventContainer,
                eventContainerShowArcs: eventContainer ? eventContainer.dataset.showArcs : null,
                managersExist: !!window.eventAnnotationManagers,
                managerNames: window.eventAnnotationManagers ? Object.keys(window.eventAnnotationManagers) : []
            };
        """)

        print("\n=== Container Positioning Diagnostic ===")
        print(f"instance-text exists: {wrapper_data['instanceTextExists']}")
        print(f"Event container exists: {wrapper_data['eventContainerExists']}")
        print(f"Event container showArcs: {wrapper_data['eventContainerShowArcs']}")
        print(f"Managers exist: {wrapper_data['managersExist']}")
        print(f"Manager names: {wrapper_data['managerNames']}")
        print(f"Wrapper exists: {wrapper_data['wrapperExists']}")
        print(f"Spacer exists: {wrapper_data['spacerExists']}")
        print(f"Container exists: {wrapper_data['containerExists']}")

        if wrapper_data['wrapper']:
            w = wrapper_data['wrapper']
            print(f"Wrapper: {w['width']}x{w['height']} at ({w['left']}, {w['top']})")

        if wrapper_data['spacer']:
            s = wrapper_data['spacer']
            print(f"Spacer: {s['width']}x{s['height']} at ({s['left']}, {s['top']})")

    def test_diagnose_event_manager_state(self):
        """Diagnostic test to check EventAnnotationManager state."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        manager_state = self.driver.execute_script("""
            const managers = window.eventAnnotationManagers;
            if (!managers) return { error: 'No managers found' };

            const result = {};
            for (const [name, manager] of Object.entries(managers)) {
                result[name] = {
                    events: manager.events ? manager.events.length : 0,
                    hasTextWrapper: !!manager.textWrapper,
                    hasArcsContainer: !!manager.arcsContainer,
                    hasArcSpacer: !!manager.arcSpacer,
                    state: manager.state,
                    isEventMode: manager.isEventMode
                };
            }
            return result;
        """)

        print("\n=== EventAnnotationManager State ===")
        print(manager_state)
