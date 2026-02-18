"""
Selenium test for arc (span link) persistence bug.

This test verifies that span links (arcs) persist after page reload.
The bug was that links weren't being saved to the backend because the
saveLink() function didn't include the required 'annotations' key.
"""

import pytest
import time
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


class TestArcPersistenceBug:
    """Test that span link arcs persist after page reload."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server with the dependency tree config."""
        config_path = "project-hub/simple_examples/simple-dependency-tree/config.yaml"
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_file = os.path.join(repo_root, config_path)

        # Clear any existing annotations
        output_dir = os.path.join(repo_root, "project-hub/simple_examples/simple-dependency-tree/annotation_output")
        if os.path.exists(output_dir):
            import shutil
            shutil.rmtree(output_dir)

        port = find_free_port(preferred_port=9877)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
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
    def teardown_class(cls):
        """Clean up the Flask server."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()

    def setup_method(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        timestamp = int(time.time())
        self.test_user = f"test_arc_persist_{timestamp}"

        # Login
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(0.5)

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

    def test_arc_persists_after_reload(self):
        """Test that arcs persist after page reload - the main bug test."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)
        self.wait_for_element(By.ID, "instance-text")

        # Get instance ID
        instance_id = self.driver.execute_script(
            "return document.getElementById('instance_id')?.value"
        )
        print(f"\nInstance ID: {instance_id}")

        # Step 1: Create two span annotations via API
        print("\n=== Creating spans via API ===")

        # Create span on "The" (0-3)
        span1_result = self.driver.execute_script("""
            return fetch('/updateinstance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    instance_id: arguments[0],
                    type: 'span',
                    schema: 'tokens',
                    state: [{
                        name: 'DET',
                        start: 0,
                        end: 3,
                        title: 'DET',
                        value: 1,
                        span_id: 'tokens_DET_0_3'
                    }]
                })
            }).then(r => r.json());
        """, instance_id)
        print(f"Span 1 result: {span1_result}")
        time.sleep(0.3)

        # Create span on "cat" (4-7)
        span2_result = self.driver.execute_script("""
            return fetch('/updateinstance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    instance_id: arguments[0],
                    type: 'span',
                    schema: 'tokens',
                    state: [{
                        name: 'NOUN',
                        start: 4,
                        end: 7,
                        title: 'NOUN',
                        value: 1,
                        span_id: 'tokens_NOUN_4_7'
                    }]
                })
            }).then(r => r.json());
        """, instance_id)
        print(f"Span 2 result: {span2_result}")
        time.sleep(0.5)

        # Step 2: Create a link between spans via API (the bug was here)
        print("\n=== Creating link via API ===")

        link_result = self.driver.execute_script("""
            const link = {
                id: 'link_test_' + Date.now(),
                schema: 'dependencies',
                link_type: 'det',
                span_ids: ['tokens_DET_0_3', 'tokens_NOUN_4_7'],
                direction: 'directed',
                properties: {
                    color: '#6b7280',
                    span_labels: ['DET', 'NOUN'],
                    span_positions: [{start: 0, end: 3}, {start: 4, end: 7}]
                }
            };

            return fetch('/updateinstance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    instance_id: arguments[0],
                    annotations: {},  // This was the bug - missing annotations key!
                    link_annotations: [link]
                })
            }).then(r => r.json());
        """, instance_id)
        print(f"Link creation result: {link_result}")
        time.sleep(0.5)

        # Step 3: Verify link was saved by fetching from API
        print("\n=== Verifying link saved to backend ===")

        api_links = self.driver.execute_script("""
            return fetch('/api/links/' + arguments[0])
                .then(r => r.json());
        """, instance_id)
        print(f"API links before reload: {api_links}")

        links_before = api_links.get('links', [])
        assert len(links_before) > 0, f"Link was NOT saved to backend! API response: {api_links}"
        print(f"SUCCESS: Found {len(links_before)} link(s) saved to backend")

        # Step 4: Reload the page
        print("\n=== Reloading page ===")
        self.driver.refresh()
        time.sleep(2)
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(1)

        # Step 5: Verify link still exists after reload
        print("\n=== Verifying link persists after reload ===")

        api_links_after = self.driver.execute_script("""
            return fetch('/api/links/' + arguments[0])
                .then(r => r.json());
        """, instance_id)
        print(f"API links after reload: {api_links_after}")

        links_after = api_links_after.get('links', [])
        assert len(links_after) > 0, f"Link did NOT persist after reload! API response: {api_links_after}"
        print(f"SUCCESS: Link persisted! Found {len(links_after)} link(s)")

        # Step 6: Verify the SpanLinkManager loaded the links
        manager_state = self.driver.execute_script("""
            const manager = window.spanLinkManagers && Object.values(window.spanLinkManagers)[0];
            if (!manager) return {error: 'No manager'};
            return {
                linksCount: manager.links.length,
                links: manager.links
            };
        """)
        print(f"SpanLinkManager state: {manager_state}")

        manager_links = manager_state.get('linksCount', 0)
        assert manager_links > 0, f"SpanLinkManager did not load links! State: {manager_state}"
        print(f"SUCCESS: SpanLinkManager has {manager_links} link(s)")

    def test_link_save_includes_annotations_key(self):
        """Test that saveLink includes the required annotations key."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)
        self.wait_for_element(By.ID, "instance-text")

        # Check that saveLink function includes annotations key
        has_annotations_key = self.driver.execute_script("""
            const manager = window.spanLinkManagers && Object.values(window.spanLinkManagers)[0];
            if (!manager || !manager.saveLink) return {error: 'No manager or saveLink'};

            // Check the saveLink function source code
            const source = manager.saveLink.toString();
            return {
                hasAnnotationsKey: source.includes('annotations'),
                sourcePreview: source.substring(0, 500)
            };
        """)
        print(f"\nsaveLink check: {has_annotations_key}")

        assert has_annotations_key.get('hasAnnotationsKey', False), \
            f"saveLink does not include annotations key! Source: {has_annotations_key.get('sourcePreview', '')}"
