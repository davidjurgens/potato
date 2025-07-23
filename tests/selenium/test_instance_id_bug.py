import unittest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest

class TestInstanceIdBug(BaseSeleniumTest):
    def test_instance_id_not_updating_bug(self):
        """Test to reproduce the bug where instance_id doesn't update on navigation."""
        base_url = self.server.base_url

        # Navigate to annotation page
        self.driver.get(f"{base_url}/annotate")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))

        # Get the initial instance_id and text
        instance_id_input = self.driver.find_element(By.ID, "instance_id")
        initial_instance_id = instance_id_input.get_attribute("value")
        initial_text = self.driver.find_element(By.ID, "instance-text").text
        print(f"🔍 Initial instance_id: {initial_instance_id}")
        print(f"🔍 Initial text: {initial_text[:100]}...")

        # Run the debug function to see what's happening
        self.driver.execute_script("""
            if (window.debugInstanceId) {
                window.debugInstanceId();
            } else {
                console.log('debugInstanceId function not available');
            }
        """)

        # Navigate to next instance
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for page to reload
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))

        # Get the new instance_id and text
        instance_id_input = self.driver.find_element(By.ID, "instance_id")
        new_instance_id = instance_id_input.get_attribute("value")
        new_text = self.driver.find_element(By.ID, "instance-text").text
        print(f"🔍 New instance_id: {new_instance_id}")
        print(f"🔍 New text: {new_text[:100]}...")

        # Run the debug function again
        self.driver.execute_script("""
            if (window.debugInstanceId) {
                window.debugInstanceId();
            } else {
                console.log('debugInstanceId function not available');
            }
        """)

        # Check if the instance_id changed
        if initial_instance_id == new_instance_id:
            print("❌ BUG REPRODUCED: instance_id did not change!")
            print(f"   Initial: {initial_instance_id}")
            print(f"   New: {new_instance_id}")

            # Check if the text changed
            if initial_text == new_text:
                print("❌ Text also did not change - navigation may have failed completely")
            else:
                print("⚠️ Text changed but instance_id did not - this is the bug!")
        else:
            print("✅ instance_id changed correctly")
            print(f"   Initial: {initial_instance_id}")
            print(f"   New: {new_instance_id}")

        # Check if the text changed
        if initial_text != new_text:
            print("✅ Text changed correctly")
        else:
            print("❌ Text did not change - navigation may have failed")

if __name__ == '__main__':
    unittest.main()