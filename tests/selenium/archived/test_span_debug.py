#!/usr/bin/env python3
"""
Comprehensive span annotation debugging test.

This test isolates span annotation issues by:
1. Starting a fresh server instance
2. Creating a test user
3. Step-by-step span creation with detailed logging
4. Verifying backend storage and retrieval
5. Checking frontend rendering
"""

import time
import json
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import pytest
import subprocess
import signal
import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from tests.helpers.flask_test_setup import FlaskTestServer


class TestSpanDebug:
    """Comprehensive span annotation debugging test."""

    def setup_method(self):
        """Set up test environment."""
        self.server = None
        self.driver = None
        self.server_url = "http://localhost:9008"
        self.test_user = "debug_user"

        # Start the server
        self._start_server()

        # Set up the browser
        self._setup_browser()

        # Register test user
        self._register_user()

    def teardown_method(self):
        """Clean up test environment."""
        if self.driver:
            self.driver.quit()
        if self.server:
            self.server.terminate()
            self.server.wait()

    def _start_server(self):
        """Start the Flask server with span annotation config."""
        print("🔧 Starting Flask server...")

        # Use a simple span annotation config
        config_content = """
name: "Span Debug Test"
data_file: "data/test_data.json"
phases:
  - name: "annotation"
    template: "base_template_v2.html"
    schemas:
      - name: "emotion"
        type: "span"
        labels:
          - name: "happy"
            title: "Happy"
          - name: "sad"
            title: "Sad"
          - name: "angry"
            title: "Angry"
        colors:
          happy: "(255, 255, 0)"
          sad: "(0, 0, 255)"
          angry: "(255, 0, 0)"
"""

        # Write config to temporary file
        config_path = "configs/span-debug-test.yaml"
        os.makedirs("configs", exist_ok=True)
        with open(config_path, "w") as f:
            f.write(config_content)

        # Start server
        cmd = ["python", "-m", "potato.flask_server", "start", config_path]
        self.server = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Wait for server to start
        time.sleep(3)

        # Check if server is running
        try:
            response = requests.get(f"{self.server_url}/admin/health", timeout=5)
            if response.status_code == 200:
                print("✅ Server started successfully")
            else:
                raise Exception(f"Server health check failed: {response.status_code}")
        except Exception as e:
            print(f"❌ Server failed to start: {e}")
            if self.server:
                self.server.terminate()
            raise

    def _setup_browser(self):
        """Set up Chrome browser in headless mode."""
        print("🔧 Setting up browser...")

        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(10)
        print("✅ Browser setup complete")

    def _register_user(self):
        """Register a test user."""
        print(f"🔧 Registering user: {self.test_user}")

        response = requests.post(f"{self.server_url}/register",
                               data={"username": self.test_user, "password": "testpass"})

        if response.status_code == 302:  # Redirect after successful registration
            print(f"✅ User {self.test_user} registered successfully")
        else:
            print(f"❌ User registration failed: {response.status_code}")
            raise Exception("User registration failed")

    def _get_user_state(self):
        """Get current user state for debugging."""
        try:
            response = self.server.get(f"/admin/user_state/{self.test_user}")
        except AttributeError:
            import requests
            response = requests.get(f"{self.server_url}/admin/user_state/{self.test_user}", headers={"X-API-Key": "admin_api_key"})

        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Failed to get user state: {response.status_code}")
            return None

    def _create_span_via_api(self, instance_id, text, start, end, label="happy"):
        """Create a span annotation via direct API call."""
        print(f"🔧 Creating span via API: '{text[start:end]}' ({start}-{end})")

        span_data = {
            "type": "span",
            "schema": "emotion",
            "state": [
                {
                    "name": label,
                    "start": start,
                    "end": end,
                    "title": label.capitalize(),
                    "value": text[start:end]
                }
            ],
            "instance_id": instance_id
        }

        print(f"🔧 Span data: {json.dumps(span_data, indent=2)}")

        response = requests.post(f"{self.server_url}/updateinstance", json=span_data)

        if response.status_code == 200:
            result = response.json()
            print(f"✅ Span creation API response: {result}")
            return result
        else:
            print(f"❌ Span creation failed: {response.status_code} - {response.text}")
            return None

    def _verify_span_storage(self, instance_id):
        """Verify that spans are properly stored in the backend."""
        print(f"🔧 Verifying span storage for instance: {instance_id}")

        user_state = self._get_user_state()
        if not user_state:
            return False

        print(f"🔧 User state: {json.dumps(user_state, indent=2)}")

        # Check if instance has annotations
        annotations = user_state.get("annotations", {}).get("by_instance", {})
        if str(instance_id) not in annotations:
            print(f"❌ No annotations found for instance {instance_id}")
            return False

        instance_annotations = annotations[str(instance_id)]
        print(f"🔧 Instance annotations: {json.dumps(instance_annotations, indent=2)}")

        # Check for span annotations
        span_annotations = []
        for key, value in instance_annotations.items():
            if isinstance(value, dict) and "start" in value and "end" in value:
                span_annotations.append(value)

        print(f"🔧 Found {len(span_annotations)} span annotations")
        return len(span_annotations) > 0

    def _check_frontend_rendering(self, expected_text):
        """Check if spans are properly rendered in the frontend."""
        print("🔧 Checking frontend rendering...")

        # Wait for the page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Get the text container
        text_container = self.driver.find_element(By.ID, "instance-text")
        html_content = text_container.get_attribute("innerHTML")

        print(f"🔧 Text container HTML: {html_content}")

        # Check for span elements
        span_elements = text_container.find_elements(By.TAG_NAME, "span")
        print(f"🔧 Found {len(span_elements)} span elements")

        for i, span in enumerate(span_elements):
            print(f"🔧 Span {i}: {span.get_attribute('outerHTML')}")

        # Check if the expected text is highlighted
        if expected_text in html_content:
            print(f"✅ Expected text '{expected_text}' found in HTML")
            return True
        else:
            print(f"❌ Expected text '{expected_text}' not found in HTML")
            return False

    def test_span_annotation_debug_workflow(self):
        """Comprehensive span annotation debugging workflow."""
        print("\n" + "="*80)
        print("🧪 STARTING SPAN ANNOTATION DEBUG WORKFLOW")
        print("="*80)

        # Step 1: Navigate to annotation page
        print("\n📋 Step 1: Navigating to annotation page")
        self.driver.get(f"{self.server_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Get the current instance
        instance_id_element = self.driver.find_element(By.ID, "instance_id")
        instance_id = instance_id_element.get_attribute("value")
        print(f"🔧 Current instance ID: {instance_id}")

        # Get the text content
        text_container = self.driver.find_element(By.ID, "instance-text")
        full_text = text_container.text
        print(f"🔧 Full text: '{full_text}'")

        # Step 2: Create a span annotation via API
        print("\n📋 Step 2: Creating span annotation via API")

        # Find a good text to annotate (look for "artificial intelligence")
        target_text = "artificial intelligence"
        start_pos = full_text.find(target_text)

        if start_pos == -1:
            # Fallback to first few words
            target_text = full_text.split()[0]
            start_pos = 0

        end_pos = start_pos + len(target_text)

        print(f"🔧 Target text: '{target_text}' (positions {start_pos}-{end_pos})")

        # Create span via API
        api_result = self._create_span_via_api(instance_id, full_text, start_pos, end_pos)
        if not api_result:
            pytest.fail("Span creation via API failed")

        # Step 3: Verify backend storage
        print("\n📋 Step 3: Verifying backend storage")
        if not self._verify_span_storage(instance_id):
            pytest.fail("Span storage verification failed")

        # Step 4: Reload page and check frontend rendering
        print("\n📋 Step 4: Checking frontend rendering")
        self.driver.refresh()

        # Wait for page to reload
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        if not self._check_frontend_rendering(target_text):
            pytest.fail("Frontend rendering verification failed")

        # Step 5: Try creating span via frontend selection
        print("\n📋 Step 5: Testing frontend span creation")

        # Find another piece of text to select
        text_container = self.driver.find_element(By.ID, "instance-text")
        full_text = text_container.text

        # Look for "natural language processing"
        target_text2 = "natural language processing"
        start_pos2 = full_text.find(target_text2)

        if start_pos2 == -1:
            # Fallback to different text
            words = full_text.split()
            if len(words) >= 3:
                target_text2 = " ".join(words[1:3])
                start_pos2 = full_text.find(target_text2)

        if start_pos2 != -1:
            print(f"🔧 Testing frontend selection: '{target_text2}'")

            # Use JavaScript to select text
            script = f"""
            var textElement = arguments[0];
            var text = textElement.textContent;
            var startIndex = text.indexOf('{target_text2}');
            if (startIndex >= 0) {{
                var range = document.createRange();
                var startNode = textElement.firstChild;
                range.setStart(startNode, startIndex);
                range.setEnd(startNode, startIndex + {len(target_text2)});

                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);

                console.log('Text selected:', selection.toString());
                return true;
            }}
            return false;
            """

            selection_made = self.driver.execute_script(script, text_container)
            if selection_made:
                print("✅ Text selection successful")

                # Try to trigger span creation (this would normally be done by clicking a button)
                # For now, we'll just verify the selection worked
                selected_text = self.driver.execute_script("return window.getSelection().toString();")
                print(f"🔧 Selected text: '{selected_text}'")
            else:
                print("❌ Text selection failed")

        print("\n" + "="*80)
        print("✅ SPAN ANNOTATION DEBUG WORKFLOW COMPLETED")
        print("="*80)

    def test_span_annotation_edge_cases(self):
        """Test edge cases for span annotation."""
        print("\n" + "="*80)
        print("🧪 TESTING SPAN ANNOTATION EDGE CASES")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server_url}/annotate")

        # Get instance info
        instance_id = self.driver.find_element(By.ID, "instance_id").get_attribute("value")
        text_container = self.driver.find_element(By.ID, "instance-text")
        full_text = text_container.text

        print(f"🔧 Testing edge cases with text: '{full_text[:100]}...'")

        # Test 1: Single character span
        print("\n📋 Test 1: Single character span")
        api_result = self._create_span_via_api(instance_id, full_text, 0, 1, "happy")
        if api_result:
            print("✅ Single character span created")
            self._verify_span_storage(instance_id)
        else:
            print("❌ Single character span failed")

        # Test 2: Span at end of text
        print("\n📋 Test 2: Span at end of text")
        end_text = full_text[-10:]  # Last 10 characters
        start_pos = len(full_text) - 10
        api_result = self._create_span_via_api(instance_id, full_text, start_pos, len(full_text), "sad")
        if api_result:
            print("✅ End span created")
            self._verify_span_storage(instance_id)
        else:
            print("❌ End span failed")

        # Test 3: Overlapping spans
        print("\n📋 Test 3: Overlapping spans")
        if len(full_text) >= 20:
            # Create two overlapping spans
            api_result1 = self._create_span_via_api(instance_id, full_text, 5, 15, "happy")
            api_result2 = self._create_span_via_api(instance_id, full_text, 10, 20, "sad")

            if api_result1 and api_result2:
                print("✅ Overlapping spans created")
                self._verify_span_storage(instance_id)
            else:
                print("❌ Overlapping spans failed")

        print("\n" + "="*80)
        print("✅ EDGE CASE TESTING COMPLETED")
        print("="*80)


if __name__ == "__main__":
    # Run the test directly
    test = TestSpanDebug()
    test.setup_method()
    try:
        test.test_span_annotation_debug_workflow()
        test.test_span_annotation_edge_cases()
    finally:
        test.teardown_method()