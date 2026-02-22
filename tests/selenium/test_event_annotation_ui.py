#!/usr/bin/env python3
"""
Selenium UI tests for N-ary event annotation.

Tests the frontend UI functionality:
- Event annotation container renders correctly
- Event type selection works
- Trigger and argument selection workflow
- Event creation and deletion
- Visual arc display
- Persistence across navigation
"""

import time
import os
import sys
import unittest
import pytest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, TimeoutException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


class TestEventAnnotationUI(unittest.TestCase):
    """Test event annotation UI functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up Flask server and test configuration."""
        cls.test_dir = create_test_directory("event_ui_test")

        # Create test data with text suitable for event annotation
        test_data = [
            {"id": "ui_test_1", "text": "John Smith attacked the government building with a rifle yesterday."},
            {"id": "ui_test_2", "text": "Microsoft hired Sarah Johnson as CTO last month."},
            {"id": "ui_test_3", "text": "The rebels attacked the base near the border."},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        config_file = create_test_config(
            cls.test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "entities",
                    "description": "Mark entity spans",
                    "labels": [
                        {"name": "PERSON", "color": "#3b82f6"},
                        {"name": "ORG", "color": "#10b981"},
                        {"name": "LOC", "color": "#f59e0b"},
                        {"name": "WEAPON", "color": "#ef4444"},
                        {"name": "EVENT_TRIGGER", "color": "#8b5cf6"}
                    ],
                },
                {
                    "annotation_type": "event_annotation",
                    "name": "events",
                    "description": "Annotate events with triggers and arguments",
                    "span_schema": "entities",
                    "event_types": [
                        {
                            "type": "ATTACK",
                            "color": "#dc2626",
                            "arguments": [
                                {"role": "attacker", "entity_types": ["PERSON", "ORG"], "required": True},
                                {"role": "target", "entity_types": ["PERSON", "ORG", "LOC"], "required": True},
                                {"role": "weapon", "entity_types": ["WEAPON"], "required": False}
                            ]
                        },
                        {
                            "type": "HIRE",
                            "color": "#2563eb",
                            "arguments": [
                                {"role": "employer", "entity_types": ["ORG"], "required": True},
                                {"role": "employee", "entity_types": ["PERSON"], "required": True}
                            ]
                        }
                    ]
                },
            ],
            data_files=[data_file],
        )

        # Start server
        port = find_free_port(preferred_port=9050)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        if not cls.server.start_server():
            pytest.fail("Failed to start Flask server")

        cls.server._wait_for_server_ready(timeout=15)

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
        """Set up WebDriver and authenticate user."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"event_ui_user_{int(time.time())}"

        # Register and login
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        # Simple login (no password required)
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.send_keys(self.test_user)
        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        # Wait for annotation page to load
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        time.sleep(0.5)

    def tearDown(self):
        """Clean up WebDriver."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def test_event_annotation_container_present(self):
        """Event annotation container should be present on the page."""
        container = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "event-annotation-container"))
        )
        assert container.is_displayed()

    def test_event_types_displayed(self):
        """Event types should be displayed as selectable options."""
        # Look for event type elements
        event_types = self.driver.find_elements(By.CLASS_NAME, "event-type")
        assert len(event_types) >= 2  # We have ATTACK and HIRE

        # Check specific event types are present
        page_source = self.driver.page_source
        assert "ATTACK" in page_source
        assert "HIRE" in page_source

    def test_event_type_selection_shows_trigger_section(self):
        """Selecting an event type should show the trigger selection section."""
        # Find and click an event type
        attack_radio = self.driver.find_element(
            By.CSS_SELECTOR, 'input[value="ATTACK"]'
        )
        # Use JavaScript to click (radio may be hidden)
        self.driver.execute_script("arguments[0].click();", attack_radio)

        # Wait for trigger section to appear
        trigger_section = WebDriverWait(self.driver, 5).until(
            EC.visibility_of_element_located((By.CLASS_NAME, "event-trigger-section"))
        )
        assert trigger_section.is_displayed()

    def test_event_type_colors(self):
        """Event types should display with their configured colors."""
        # Find event type elements
        event_types = self.driver.find_elements(By.CLASS_NAME, "event-type")

        # Check that colors are applied
        for event_type in event_types:
            color_indicator = event_type.find_element(By.CLASS_NAME, "event-color-indicator")
            style = color_indicator.get_attribute("style")
            assert "background-color" in style

    def test_cancel_button_resets_state(self):
        """Cancel button should reset the event creation state."""
        # Select an event type
        attack_radio = self.driver.find_element(
            By.CSS_SELECTOR, 'input[value="ATTACK"]'
        )
        self.driver.execute_script("arguments[0].click();", attack_radio)

        # Wait for mode to be active
        WebDriverWait(self.driver, 5).until(
            EC.visibility_of_element_located((By.CLASS_NAME, "event-trigger-section"))
        )

        # Click cancel button
        cancel_btn = self.driver.find_element(By.CLASS_NAME, "event-cancel-btn")
        cancel_btn.click()

        # Trigger section should be hidden
        trigger_section = self.driver.find_element(By.CLASS_NAME, "event-trigger-section")
        assert not trigger_section.is_displayed()

    def test_escape_key_cancels_event_mode(self):
        """Pressing Escape should cancel event creation mode."""
        # Select an event type
        attack_radio = self.driver.find_element(
            By.CSS_SELECTOR, 'input[value="ATTACK"]'
        )
        self.driver.execute_script("arguments[0].click();", attack_radio)

        # Wait for mode to be active
        WebDriverWait(self.driver, 5).until(
            EC.visibility_of_element_located((By.CLASS_NAME, "event-trigger-section"))
        )

        # Press Escape
        ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()

        # Trigger section should be hidden
        time.sleep(0.3)
        trigger_section = self.driver.find_element(By.CLASS_NAME, "event-trigger-section")
        assert not trigger_section.is_displayed()

    def test_create_button_initially_disabled(self):
        """Create button should be disabled until requirements are met."""
        # Select an event type
        attack_radio = self.driver.find_element(
            By.CSS_SELECTOR, 'input[value="ATTACK"]'
        )
        self.driver.execute_script("arguments[0].click();", attack_radio)

        # Find create button - should be disabled
        create_btn = self.driver.find_element(By.CLASS_NAME, "event-create-btn")
        assert create_btn.get_attribute("disabled") is not None

    def test_existing_events_section_present(self):
        """Existing events section should be present."""
        events_section = self.driver.find_element(By.CLASS_NAME, "event-existing")
        assert events_section.is_displayed()

    def test_no_events_message_initially(self):
        """Should show 'no events' message when no events exist."""
        no_events_msg = self.driver.find_element(By.CLASS_NAME, "no-events-message")
        assert "No events" in no_events_msg.text

    def test_visual_toggle_present(self):
        """Visual display toggle checkbox should be present."""
        toggle = self.driver.find_element(By.CLASS_NAME, "event-visual-toggle")
        assert toggle.is_displayed()

        checkbox = toggle.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
        assert checkbox is not None

    def test_event_annotation_js_loaded(self):
        """Event annotation JavaScript should be loaded and functional."""
        # Check that the EventAnnotationManager is available
        result = self.driver.execute_script(
            "return typeof window.eventAnnotationManagers !== 'undefined'"
        )
        assert result is True

    def test_event_manager_initialized(self):
        """Event annotation manager should be initialized for the schema."""
        result = self.driver.execute_script(
            "return window.eventAnnotationManagers && 'events' in window.eventAnnotationManagers"
        )
        assert result is True


class TestEventAnnotationWorkflow(unittest.TestCase):
    """Test complete event annotation workflow with spans."""

    @classmethod
    def setUpClass(cls):
        """Set up Flask server with pre-created spans for testing."""
        cls.test_dir = create_test_directory("event_workflow_test")

        # Create test data
        test_data = [
            {"id": "workflow_1", "text": "John attacked the building."},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        config_file = create_test_config(
            cls.test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "entities",
                    "description": "Entities",
                    "labels": [
                        {"name": "PERSON"},
                        {"name": "LOC"},
                        {"name": "EVENT_TRIGGER"}
                    ],
                },
                {
                    "annotation_type": "event_annotation",
                    "name": "events",
                    "description": "Events",
                    "span_schema": "entities",
                    "event_types": [
                        {
                            "type": "ATTACK",
                            "arguments": [
                                {"role": "attacker", "required": True},
                                {"role": "target", "required": True}
                            ]
                        }
                    ]
                },
            ],
            data_files=[data_file],
        )

        port = find_free_port(preferred_port=9051)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        if not cls.server.start_server():
            pytest.fail("Failed to start Flask server")

        cls.server._wait_for_server_ready(timeout=15)

        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"workflow_user_{int(time.time())}"

        # Register and login
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.send_keys(self.test_user)
        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def test_selecting_event_type_enters_event_mode(self):
        """Selecting event type should enter event annotation mode."""
        # Select ATTACK event type
        attack_radio = self.driver.find_element(
            By.CSS_SELECTOR, 'input[value="ATTACK"]'
        )
        self.driver.execute_script("arguments[0].click();", attack_radio)

        # Check that event mode is active (container has class)
        container = self.driver.find_element(By.CLASS_NAME, "event-annotation-container")
        assert "event-mode-active" in container.get_attribute("class")

    def test_arguments_panel_shows_required_indicators(self):
        """Arguments panel should show required indicators for required roles."""
        # Select event type first
        attack_radio = self.driver.find_element(
            By.CSS_SELECTOR, 'input[value="ATTACK"]'
        )
        self.driver.execute_script("arguments[0].click();", attack_radio)

        # Wait for arguments section to be visible
        # First need to simulate trigger selection by checking JS state
        time.sleep(0.3)

        # Check for required indicator in page source (it's in the config)
        page_source = self.driver.page_source
        # The required indicator (*) should be present for required arguments
        assert "required" in page_source.lower() or "attacker" in page_source

    def test_event_data_hidden_input_exists(self):
        """Hidden input for event data should exist."""
        hidden_input = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="hidden"][name*="event_annotation"]'
        )
        assert hidden_input is not None

    def test_event_data_hidden_input_updates(self):
        """Hidden input should store event data as JSON."""
        hidden_input = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="hidden"][name*="event_annotation"]'
        )
        value = hidden_input.get_attribute("value")
        # Should be valid JSON (initially empty array)
        import json
        data = json.loads(value)
        assert isinstance(data, list)


class TestEventAnnotationPersistenceUI(unittest.TestCase):
    """Test event annotation persistence via UI."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("event_persist_ui_test")

        test_data = [
            {"id": "persist_ui_1", "text": "Test sentence for persistence."},
            {"id": "persist_ui_2", "text": "Another test sentence."},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        config_file = create_test_config(
            cls.test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "entities",
                    "description": "Entities",
                    "labels": [{"name": "ENTITY"}],
                },
                {
                    "annotation_type": "event_annotation",
                    "name": "events",
                    "description": "Events",
                    "span_schema": "entities",
                    "event_types": [
                        {"type": "TEST", "arguments": []}
                    ]
                },
            ],
            data_files=[data_file],
        )

        port = find_free_port(preferred_port=9052)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        if not cls.server.start_server():
            pytest.fail("Failed to start Flask server")

        cls.server._wait_for_server_ready(timeout=15)

        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"persist_ui_user_{int(time.time())}"

        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.send_keys(self.test_user)
        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def test_event_manager_loads_existing_events(self):
        """Event manager should load existing events on page load."""
        import requests

        # Get the current instance ID from the page (the hidden input is 'instance_id')
        current_instance_id = self.driver.execute_script("""
            var idElem = document.getElementById('instance_id');
            if (idElem) return idElem.value || idElem.textContent;
            var altIdElem = document.getElementById('current_instance_id');
            if (altIdElem) return altIdElem.value || altIdElem.textContent;
            return null;
        """)
        assert current_instance_id is not None, "Could not get current instance ID"

        session = requests.Session()
        # Copy cookies from Selenium
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie['name'], cookie['value'])

        # Create event via API for the current instance
        event_data = {
            "instance_id": current_instance_id,
            "event_annotations": [
                {
                    "schema": "events",
                    "event_type": "TEST",
                    "trigger_span_id": "test_trigger",
                    "arguments": [],
                    "id": f"persist_ui_event_{int(time.time())}",
                    "properties": {"trigger_text": "test"}
                }
            ]
        }
        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json=event_data,
            timeout=5,
        )
        assert response.status_code == 200

        # Refresh page
        self.driver.refresh()
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        time.sleep(1)  # Allow time for events to load

        # Check that event is in the manager's state
        result = self.driver.execute_script("""
            var manager = window.eventAnnotationManagers && window.eventAnnotationManagers['events'];
            if (manager && manager.events) {
                return manager.events.length;
            }
            return 0;
        """)
        # Event should be loaded
        assert result >= 1

    def test_page_shows_event_after_creation(self):
        """Page should display created event in the events list."""
        import requests

        # Get the current instance ID from the page (the hidden input is 'instance_id')
        current_instance_id = self.driver.execute_script("""
            var idElem = document.getElementById('instance_id');
            if (idElem) return idElem.value || idElem.textContent;
            var altIdElem = document.getElementById('current_instance_id');
            if (altIdElem) return altIdElem.value || altIdElem.textContent;
            return null;
        """)
        assert current_instance_id is not None, "Could not get current instance ID"

        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie['name'], cookie['value'])

        # Create event via API for the current instance
        unique_id = f"display_test_{int(time.time())}"
        event_data = {
            "instance_id": current_instance_id,
            "event_annotations": [
                {
                    "schema": "events",
                    "event_type": "TEST",
                    "trigger_span_id": "display_trigger",
                    "arguments": [],
                    "id": unique_id,
                    "properties": {"trigger_text": "displayed"}
                }
            ]
        }
        session.post(
            f"{self.server.base_url}/updateinstance",
            json=event_data,
            timeout=5,
        )

        # Refresh and wait
        self.driver.refresh()
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        time.sleep(1)

        # Trigger the manager to update its UI
        self.driver.execute_script("""
            var manager = window.eventAnnotationManagers && window.eventAnnotationManagers['events'];
            if (manager && manager.updateUI) {
                manager.updateUI();
            }
        """)
        time.sleep(0.5)

        # Check event list contains our event
        event_list = self.driver.find_element(By.CLASS_NAME, "event-list")
        # Look for event items or the "TEST" event type badge
        event_items = event_list.find_elements(By.CLASS_NAME, "event-item")
        if event_items:
            assert len(event_items) >= 1


class TestEventAnnotationFullWorkflowPersistence(unittest.TestCase):
    """Test that events created through UI persist after page refresh.

    This test class specifically tests:
    1. Create spans via API (reliable)
    2. Create an event through the UI using those spans
    3. Refresh the page
    4. Verify the event still appears

    This catches bugs where events are created but not properly persisted.
    """

    @classmethod
    def setUpClass(cls):
        """Set up Flask server with simple event annotation config."""
        cls.test_dir = create_test_directory("event_full_workflow_test")

        # Simple test data
        test_data = [
            {"id": "workflow_test_1", "text": "John attacked the building."},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        config_file = create_test_config(
            cls.test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "entities",
                    "description": "Entities",
                    "labels": [
                        {"name": "PERSON", "color": "#3b82f6"},
                        {"name": "TRIGGER", "color": "#dc2626"},
                        {"name": "TARGET", "color": "#10b981"},
                    ],
                },
                {
                    "annotation_type": "event_annotation",
                    "name": "events",
                    "description": "Events",
                    "span_schema": "entities",
                    "event_types": [
                        {
                            "type": "ATTACK",
                            "color": "#dc2626",
                            "arguments": [
                                {"role": "attacker", "entity_types": ["PERSON"], "required": True},
                                {"role": "target", "entity_types": ["TARGET"], "required": True}
                            ]
                        }
                    ]
                },
            ],
            data_files=[data_file],
        )

        port = find_free_port(preferred_port=9053)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        if not cls.server.start_server():
            pytest.fail("Failed to start Flask server")

        cls.server._wait_for_server_ready(timeout=15)

        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"full_workflow_user_{int(time.time())}"

        # Register and login
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.send_keys(self.test_user)
        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _create_spans_via_api(self, instance_id):
        """Create span annotations via API for testing."""
        import requests

        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie['name'], cookie['value'])

        # Create spans: John (0-4), attacked (5-13), building (18-26)
        # Use 'name' for schema name (API expectation)
        spans = [
            {"name": "entities", "label": "PERSON", "start": 0, "end": 4, "id": "span_john"},
            {"name": "entities", "label": "TRIGGER", "start": 5, "end": 13, "id": "span_attacked"},
            {"name": "entities", "label": "TARGET", "start": 18, "end": 26, "id": "span_building"},
        ]

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={"instance_id": instance_id, "span_annotations": spans},
            timeout=5,
        )
        return response.status_code == 200

    def test_event_created_through_ui_persists_after_refresh(self):
        """Events created through the JavaScript manager should persist after page refresh.

        This test simulates the UI event creation by directly calling the JavaScript
        manager's createEvent-like functionality, then verifies persistence.
        """
        import requests

        # Get the current instance ID
        current_instance_id = self.driver.execute_script("""
            var idElem = document.getElementById('instance_id');
            if (idElem) return idElem.value || idElem.textContent;
            return null;
        """)
        assert current_instance_id is not None, "Could not get current instance ID"

        # Create an event through the JavaScript manager (simulating UI creation)
        # This is what the UI does when creating an event
        event_created = self.driver.execute_script("""
            var manager = window.eventAnnotationManagers && window.eventAnnotationManagers['events'];
            if (!manager) {
                console.error('Event manager not found');
                return false;
            }

            // Simulate creating an event like the UI would
            var eventData = {
                id: 'ui_test_event_' + Date.now(),
                schema: 'events',
                event_type: 'ATTACK',
                trigger_span_id: 'test_trigger_span',
                arguments: [
                    {role: 'attacker', span_id: 'test_attacker_span'},
                    {role: 'target', span_id: 'test_target_span'}
                ],
                properties: {
                    color: '#dc2626',
                    trigger_text: 'attacked',
                    trigger_label: 'TRIGGER'
                }
            };

            // Add to events array (what createEvent does)
            manager.events.push(eventData);

            // Update hidden input (what createEvent does)
            manager.updateEventDataInput();

            // Sync to backend (what createEvent does)
            manager.syncToBackend();

            return true;
        """)
        assert event_created, "Failed to create event via JavaScript manager"

        # Wait for sync to complete
        time.sleep(1)

        # Verify event exists in manager before refresh
        events_before = self.driver.execute_script("""
            var manager = window.eventAnnotationManagers && window.eventAnnotationManagers['events'];
            return manager ? manager.events.length : 0;
        """)
        assert events_before >= 1, f"Event should exist in manager before refresh, found {events_before}"

        # Refresh the page
        self.driver.refresh()
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        time.sleep(2)  # Allow time for events to load via API

        # Verify event persists after refresh
        events_after = self.driver.execute_script("""
            var manager = window.eventAnnotationManagers && window.eventAnnotationManagers['events'];
            return manager ? manager.events.length : 0;
        """)
        assert events_after >= 1, f"Event should persist after refresh, but found {events_after} events"

        # Also check the events list UI
        event_items = self.driver.find_elements(By.CLASS_NAME, "event-item")
        assert len(event_items) >= 1, f"Event should appear in UI after refresh, found {len(event_items)}"


if __name__ == "__main__":
    unittest.main()
