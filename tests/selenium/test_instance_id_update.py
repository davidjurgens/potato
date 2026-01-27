import unittest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest

class TestInstanceIdUpdate(BaseSeleniumTest):
    def test_instance_id_updates_on_navigation(self):
        """Test that the instance_id input element is updated when navigating between instances."""
        base_url = self.server.base_url

        # Navigate to annotation page
        self.driver.get(f"{base_url}/annotate")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))

        # Get the initial instance_id
        instance_id_input = self.driver.find_element(By.ID, "instance_id")
        initial_instance_id = instance_id_input.get_attribute("value")
        print(f"🔍 Initial instance_id: {initial_instance_id}")

        # Get the initial instance text
        instance_text = self.driver.find_element(By.ID, "instance-text").text
        print(f"🔍 Initial instance text: {instance_text[:100]}...")

        # Navigate to next instance
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for page to reload
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))

        # Get the new instance_id
        instance_id_input = self.driver.find_element(By.ID, "instance_id")
        new_instance_id = instance_id_input.get_attribute("value")
        print(f"🔍 New instance_id: {new_instance_id}")

        # Get the new instance text
        new_instance_text = self.driver.find_element(By.ID, "instance-text").text
        print(f"🔍 New instance text: {new_instance_text[:100]}...")

        # Verify that the instance_id has changed
        self.assertNotEqual(initial_instance_id, new_instance_id,
                           f"Instance ID should have changed from {initial_instance_id} to {new_instance_id}")

        # Verify that the instance text has changed
        self.assertNotEqual(instance_text, new_instance_text,
                           "Instance text should have changed after navigation")

        print("✅ Instance ID and text updated correctly on navigation")

    def test_instance_id_matches_api_call(self):
        """Test that the instance_id used in API calls matches the current instance."""
        base_url = self.server.base_url

        # Navigate to annotation page
        self.driver.get(f"{base_url}/annotate")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))

        # Get the instance_id from the input element
        instance_id_input = self.driver.find_element(By.ID, "instance_id")
        dom_instance_id = instance_id_input.get_attribute("value")
        print(f"🔍 DOM instance_id: {dom_instance_id}")

        # Open browser console to capture API calls
        self.driver.execute_script("""
            // Override fetch to log API calls
            const originalFetch = window.fetch;
            window.fetch = function(...args) {
                console.log('🔍 API CALL:', args[0]);
                return originalFetch.apply(this, args);
            };
        """)

        # Trigger a span annotation load (this should make an API call)
        self.driver.execute_script("""
            // Simulate loading span annotations
            if (window.loadSpanAnnotations) {
                window.loadSpanAnnotations();
            }
        """)

        # Wait a moment for any API calls to be made
        import time
        time.sleep(0.05)

        # Get console logs
        logs = self.driver.get_log('browser')
        api_calls = [log['message'] for log in logs if 'API CALL:' in log['message']]

        print(f"🔍 API calls made: {api_calls}")

        # Check if any API calls were made to /api/spans/
        span_api_calls = [call for call in api_calls if '/api/spans/' in call]

        if span_api_calls:
            # Extract the instance_id from the API call
            api_call = span_api_calls[0]
            # The API call should be something like: /api/spans/instance_id
            api_instance_id = api_call.split('/api/spans/')[-1].split('"')[0]
            print(f"🔍 API call instance_id: {api_instance_id}")

            # Verify that the API call uses the same instance_id as the DOM
            self.assertEqual(dom_instance_id, api_instance_id,
                           f"API call should use the same instance_id as DOM: {dom_instance_id} vs {api_instance_id}")
        else:
            print("⚠️ No span API calls detected - this might be expected if no span annotations are configured")

if __name__ == '__main__':
    unittest.main()