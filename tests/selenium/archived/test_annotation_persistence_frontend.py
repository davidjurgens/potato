"""
Selenium tests for frontend annotation persistence behavior.

This test suite verifies that annotations don't persist incorrectly in the
frontend when navigating between different instances. It tests the actual
user interface behavior and DOM state.
"""

from tests.selenium.test_base import BaseSeleniumTest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import json


class TestAnnotationPersistenceFrontend(BaseSeleniumTest):
    """
    Test suite for frontend annotation persistence behavior.

    Tests that annotations are properly isolated between instances in the
    user interface and don't leak from one instance to another.

    Authentication: Handled automatically by BaseSeleniumTest
    """

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server with comprehensive annotation config."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        import os

        # Use the comprehensive annotation test config
        config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                  "tests/configs/comprehensive-annotation-test.yaml")
        cls.server = FlaskTestServer(port=9008, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        # Wait for server to be ready
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options for headless testing
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-images")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # Set up Firefox options for headless testing
        from selenium.webdriver.firefox.options import Options as FirefoxOptions
        firefox_options = FirefoxOptions()
        firefox_options.add_argument("--headless")
        firefox_options.add_argument("--width=1920")
        firefox_options.add_argument("--height=1080")
        firefox_options.set_preference("dom.webdriver.enabled", False)
        firefox_options.set_preference("useAutomationExtension", False)
        firefox_options.set_preference("general.useragent.override", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0")

        cls.chrome_options = chrome_options
        cls.firefox_options = firefox_options

    @classmethod
    def tearDownClass(cls):
        """Clean up the Flask server after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()

    def debug_print_instance_info(self):
        """Debug helper to print current instance information."""
        try:
            instance_text = self.driver.find_element(By.ID, "instance-text").text
            print(f"🔍 Current instance text: {instance_text[:100]}...")
        except Exception as e:
            print(f"🔍 Could not get instance text: {e}")

        try:
            # Check for annotation forms
            forms = self.driver.find_elements(By.CSS_SELECTOR, "#annotation-forms form")
            print(f"🔍 Found {len(forms)} annotation forms")

            for form in forms:
                form_id = form.get_attribute("id")
                print(f"🔍 Form ID: {form_id}")

                # Check for inputs in this form
                inputs = form.find_elements(By.CSS_SELECTOR, "input, textarea")
                print(f"🔍 Form {form_id} has {len(inputs)} inputs")

                for input_elem in inputs:
                    input_type = input_elem.get_attribute("type") or "textarea"
                    input_name = input_elem.get_attribute("name")
                    input_id = input_elem.get_attribute("id")
                    input_value = input_elem.get_attribute("value")
                    input_checked = input_elem.get_attribute("checked")
                    print(f"🔍   Input: type={input_type}, name={input_name}, id={input_id}, value={input_value}, checked={input_checked}")
        except Exception as e:
            print(f"🔍 Error checking forms: {e}")

    def test_likert_annotation_persistence_frontend(self):
        """
        Test that likert annotations don't persist across instances in the frontend.

        This test verifies that when a user selects a likert rating on one
        instance, that rating doesn't appear selected on subsequent instances.
        """
        print("\n🔍 Starting likert annotation persistence test")

        try:
            # Navigate to annotation page
            self.driver.get(f"{self.server.base_url}/annotate")
            self.wait_for_element(By.ID, "instance-text")

            print("🔍 Initial page load complete")
            self.debug_print_instance_info()

            # Capture the first instance text for later comparison
            first_instance_text = self.driver.find_element(By.ID, "instance-text").text
            print(f"🔍 First instance text: {first_instance_text[:100]}...")

            # Wait for annotation form to load
            self.wait_for_element(By.NAME, "quality_rating")
            print("🔍 Found quality_rating form")

            # Select a likert rating on the first instance
            likert_buttons = self.driver.find_elements(By.NAME, "quality_rating")
            print(f"🔍 Found {len(likert_buttons)} likert buttons")
            assert len(likert_buttons) > 0, "Likert buttons not found"

            # Click on rating 4 (index 3, since ratings are 1-5)
            print("🔍 Clicking on likert rating 4 (index 3)")
            try:
                # Click on the label instead of the input since the input is hidden
                label = self.driver.find_element(By.CSS_SELECTOR, 'label[for="quality_rating_4_radio"]')
                label.click()
                print("🔍 Click successful")
            except Exception as click_error:
                print(f"🔍 Click failed: {click_error}")
                raise

            time.sleep(1)  # Allow time for selection to register

            # Verify the selection was made
            try:
                selected_button = self.driver.find_element(By.CSS_SELECTOR, 'input[name="quality_rating"]:checked')
                selected_value = selected_button.get_attribute("value")
                print(f"🔍 Selected likert rating: {selected_value}")
                assert selected_button is not None, "No likert rating selected"
            except Exception as selection_error:
                print(f"🔍 Selection verification failed: {selection_error}")
                raise

            # Navigate to next instance
            print("🔍 Navigating to next instance")
            next_button = self.driver.find_element(By.ID, "next-btn")
            next_button.click()

            # Wait for the new instance to load
            self.wait_for_element(By.ID, "instance-text")
            time.sleep(2)  # Allow time for form to populate

            print("🔍 After navigation:")
            self.debug_print_instance_info()

            # Check that no likert rating is selected on the new instance
            try:
                selected_button = self.driver.find_element(By.CSS_SELECTOR, 'input[name="quality_rating"]:checked')
                selected_value = selected_button.get_attribute("value")
                print(f"🔍 ERROR: Likert rating persisted with value: {selected_value}")
                assert False, f"Likert rating persisted: {selected_value}"
            except:
                # No selection found, which is correct
                print("🔍 SUCCESS: No likert rating selected on new instance")

            # Verify we're on a different instance
            instance_text = self.driver.find_element(By.ID, "instance-text").text
            print(f"🔍 Current instance text: {instance_text[:100]}...")
            # Check that we're on a different instance (text should be different)
            assert instance_text != first_instance_text, f"Instance text did not change after navigation: {instance_text}"

        except Exception as e:
            print(f"🔍 TEST FAILED WITH EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            raise

    def test_radio_annotation_persistence_frontend(self):
        """
        Test that radio button annotations don't persist across instances in the frontend.
        """
        print("\n🔍 Starting radio annotation persistence test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        print("🔍 Initial page load complete")
        self.debug_print_instance_info()

        # Wait for annotation form to load
        self.wait_for_element(By.NAME, "sentiment")
        print("🔍 Found sentiment form")

        # Select a radio button option on the first instance
        radio_buttons = self.driver.find_elements(By.NAME, "sentiment")
        print(f"🔍 Found {len(radio_buttons)} radio buttons")
        assert len(radio_buttons) > 0, "Radio buttons not found"

        # Click on "Positive" option (first option, value="1")
        positive_button = None
        for button in radio_buttons:
            if button.get_attribute("value") == "1":  # First option is Positive
                positive_button = button
                break

        assert positive_button is not None, "Positive radio button not found"
        print("🔍 Clicking on Positive radio button")
        try:
            # Click on the label instead of the input since the input is hidden
            button_id = positive_button.get_attribute("id")
            label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
            label.click()
            print("🔍 Click successful")
        except Exception as click_error:
            print(f"🔍 Click failed: {click_error}")
            raise

        time.sleep(1)

        # Verify the selection was made
        selected_button = self.driver.find_element(By.CSS_SELECTOR, 'input[name="sentiment"]:checked')
        selected_value = selected_button.get_attribute("value")
        print(f"🔍 Selected radio button: {selected_value}")
        assert selected_button.get_attribute("value") == "1", "Radio button selection not registered"

        # Navigate to next instance
        print("🔍 Navigating to next instance")
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for the new instance to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        print("🔍 After navigation:")
        self.debug_print_instance_info()

        # Check that no radio button is selected on the new instance
        try:
            selected_button = self.driver.find_element(By.CSS_SELECTOR, 'input[name="sentiment"]:checked')
            selected_value = selected_button.get_attribute("value")
            print(f"🔍 ERROR: Radio button persisted with value: {selected_value}")
            assert False, f"Radio button persisted: {selected_value}"
        except:
            # No selection found, which is correct
            print("🔍 SUCCESS: No radio button selected on new instance")

    def test_slider_annotation_persistence_frontend(self):
        """
        Test that slider annotations don't persist across instances in the frontend.
        """
        print("\n🔍 Starting slider annotation persistence test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        print("🔍 Initial page load complete")
        self.debug_print_instance_info()

        # Wait for annotation form to load
        self.wait_for_element(By.NAME, "complexity:::slider")
        print("🔍 Found complexity slider")

        # Find the slider and set a value
        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        assert slider is not None, "Slider not found"

        # Set slider to value 8
        print("🔍 Setting slider to value 8")
        self.driver.execute_script("arguments[0].value = '8';", slider)
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", slider)
        time.sleep(1)

        # Verify the slider value was set
        slider_value = slider.get_attribute("value")
        print(f"🔍 Slider value set to: {slider_value}")
        assert slider_value == "8", f"Slider value not set correctly: {slider_value}"

        # Navigate to next instance
        print("🔍 Navigating to next instance")
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for the new instance to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        print("🔍 After navigation:")
        self.debug_print_instance_info()

        # Check that slider is reset on the new instance
        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        new_slider_value = slider.get_attribute("value")
        print(f"🔍 New instance slider value: {new_slider_value}")

        # The slider should be reset to its default value (likely 5 based on config)
        if new_slider_value != "8":
            print("🔍 SUCCESS: Slider value reset on new instance")
        else:
            print(f"🔍 ERROR: Slider value persisted: {new_slider_value}")
            assert False, f"Slider value persisted: {new_slider_value}"

    def test_text_annotation_persistence_frontend(self):
        """
        Test that text annotations don't persist across instances in the frontend.
        """
        print("\n🔍 Starting text annotation persistence test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        print("🔍 Initial page load complete")
        self.debug_print_instance_info()

        # Wait for annotation form to load
        self.wait_for_element(By.NAME, "summary:::text_box")
        print("🔍 Found summary textarea")

        # Find the textarea and enter some text
        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        assert textarea is not None, "Summary textarea not found"

        test_text = "This is test annotation text"
        print(f"🔍 Entering text: {test_text}")
        textarea.clear()
        textarea.send_keys(test_text)
        time.sleep(1)

        # Verify the text was entered
        textarea_value = textarea.get_attribute("value")
        print(f"🔍 Textarea value: {textarea_value}")
        assert textarea_value == test_text, f"Text not entered correctly: {textarea_value}"

        # Navigate to next instance
        print("🔍 Navigating to next instance")
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for the new instance to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        print("🔍 After navigation:")
        self.debug_print_instance_info()

        # Check that textarea is cleared on the new instance
        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        new_textarea_value = textarea.get_attribute("value")
        print(f"🔍 New instance textarea value: '{new_textarea_value}'")

        if new_textarea_value == "" or new_textarea_value != test_text:
            print("🔍 SUCCESS: Textarea cleared on new instance")
        else:
            print(f"🔍 ERROR: Textarea value persisted: '{new_textarea_value}'")
            assert False, f"Textarea value persisted: '{new_textarea_value}'"

    def test_mixed_annotation_persistence_frontend(self):
        """
        Test that multiple annotation types don't persist across instances in the frontend.
        """
        print("\n🔍 Starting mixed annotation persistence test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        print("🔍 Initial page load complete")
        self.debug_print_instance_info()

        # Wait for all annotation forms to load
        self.wait_for_element(By.NAME, "quality_rating")
        self.wait_for_element(By.NAME, "sentiment")
        self.wait_for_element(By.NAME, "complexity:::slider")
        self.wait_for_element(By.NAME, "summary:::text_box")
        print("🔍 All annotation forms loaded")

        # Make annotations on all fields
        print("🔍 Making annotations on all fields...")

        # Likert rating
        likert_buttons = self.driver.find_elements(By.NAME, "quality_rating")
        # Click on the label for rating 3 (index 2)
        button_id = likert_buttons[2].get_attribute("id")
        label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
        label.click()
        print("🔍 Set likert rating to 3")

        # Radio button
        radio_buttons = self.driver.find_elements(By.NAME, "sentiment")
        for button in radio_buttons:
            if button.get_attribute("value") == "2":  # Neutral is second option (value="2")
                # Click on the label instead of the input
                button_id = button.get_attribute("id")
                label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
                label.click()
                break
        print("🔍 Set radio button to Neutral")

        # Slider
        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        self.driver.execute_script("arguments[0].value = '7';", slider)
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", slider)
        print("🔍 Set slider to 7")

        # Text
        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        textarea.clear()
        textarea.send_keys("Mixed test annotation")
        print("🔍 Set text to 'Mixed test annotation'")

        time.sleep(1)

        # Navigate to next instance
        print("🔍 Navigating to next instance")
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for the new instance to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        print("🔍 After navigation:")
        self.debug_print_instance_info()

        # Check that all fields are reset
        print("🔍 Checking that all fields are reset...")

        # Check likert
        try:
            selected_likert = self.driver.find_element(By.CSS_SELECTOR, 'input[name="quality_rating"]:checked')
            print(f"🔍 ERROR: Likert rating persisted: {selected_likert.get_attribute('value')}")
            assert False, "Likert rating persisted"
        except:
            print("🔍 SUCCESS: Likert rating reset")

        # Check radio
        try:
            selected_radio = self.driver.find_element(By.CSS_SELECTOR, 'input[name="sentiment"]:checked')
            print(f"🔍 ERROR: Radio button persisted: {selected_radio.get_attribute('value')}")
            assert False, "Radio button persisted"
        except:
            print("🔍 SUCCESS: Radio button reset")

        # Check slider
        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        slider_value = slider.get_attribute("value")
        if slider_value != "7":
            print("🔍 SUCCESS: Slider reset")
        else:
            print(f"🔍 ERROR: Slider persisted: {slider_value}")
            assert False, "Slider persisted"

        # Check text
        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        textarea_value = textarea.get_attribute("value")
        if textarea_value != "Mixed test annotation":
            print("🔍 SUCCESS: Textarea reset")
        else:
            print(f"🔍 ERROR: Textarea persisted: '{textarea_value}'")
            assert False, "Textarea persisted"

    def test_form_clearing_on_navigation(self):
        """
        Test that form inputs are properly cleared when navigating between instances.
        """
        print("\n🔍 Starting form clearing test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        print("🔍 Initial page load complete")
        self.debug_print_instance_info()

        # Wait for annotation forms to load
        self.wait_for_element(By.NAME, "quality_rating")
        self.wait_for_element(By.NAME, "sentiment")
        self.wait_for_element(By.NAME, "complexity:::slider")
        self.wait_for_element(By.NAME, "summary:::text_box")
        print("🔍 All annotation forms loaded")

        # Fill out all forms
        print("🔍 Filling out all forms...")

        # Likert
        likert_buttons = self.driver.find_elements(By.NAME, "quality_rating")
        # Click on the label for rating 5 (index 4)
        button_id = likert_buttons[4].get_attribute("id")
        label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
        label.click()
        print("🔍 Set likert to 5")

        # Radio
        radio_buttons = self.driver.find_elements(By.NAME, "sentiment")
        for button in radio_buttons:
            if button.get_attribute("value") == "3":  # Negative is third option (value="3")
                button_id = button.get_attribute("id")
                label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
                label.click()
                break
        print("🔍 Set radio to Negative")

        # Slider
        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        self.driver.execute_script("arguments[0].value = '9';", slider)
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", slider)
        print("🔍 Set slider to 9")

        # Text
        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        textarea.clear()
        textarea.send_keys("Form clearing test text")
        print("🔍 Set text to 'Form clearing test text'")

        time.sleep(1)

        # Navigate to next instance
        print("🔍 Navigating to next instance")
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for the new instance to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        print("🔍 After navigation:")
        self.debug_print_instance_info()

        # Verify all forms are cleared
        print("🔍 Verifying all forms are cleared...")

        # Check that no radio buttons are selected
        checked_radios = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="radio"]:checked')
        print(f"🔍 Found {len(checked_radios)} checked radio buttons")
        assert len(checked_radios) == 0, f"Radio buttons not cleared: {len(checked_radios)} still checked"

        # Check that textarea is empty
        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        textarea_value = textarea.get_attribute("value")
        print(f"🔍 Textarea value: '{textarea_value}'")
        assert textarea_value == "", f"Textarea not cleared: '{textarea_value}'"

        # Check that slider is reset (should be default value, likely 5)
        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        slider_value = slider.get_attribute("value")
        print(f"🔍 Slider value: {slider_value}")
        assert slider_value != "9", f"Slider not reset: {slider_value}"

        print("🔍 SUCCESS: All forms cleared properly")

    def test_annotation_state_isolation(self):
        """
        Test that annotation state is properly isolated between different instances.
        """
        print("\n🔍 Starting annotation state isolation test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        print("🔍 Initial page load complete")
        self.debug_print_instance_info()

        # Wait for annotation forms to load
        self.wait_for_element(By.NAME, "quality_rating")
        self.wait_for_element(By.NAME, "sentiment")
        self.wait_for_element(By.NAME, "complexity:::slider")
        self.wait_for_element(By.NAME, "summary:::text_box")
        print("🔍 All annotation forms loaded")

        # Make annotations on first instance
        print("🔍 Making annotations on first instance...")

        likert_buttons = self.driver.find_elements(By.NAME, "quality_rating")
        # Click on the label for rating 1 (index 0)
        button_id = likert_buttons[0].get_attribute("id")
        label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
        label.click()

        radio_buttons = self.driver.find_elements(By.NAME, "sentiment")
        for button in radio_buttons:
            if button.get_attribute("value") == "1":  # Positive is first option (value="1")
                button_id = button.get_attribute("id")
                label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
                label.click()
                break

        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        self.driver.execute_script("arguments[0].value = '3';", slider)
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", slider)

        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        textarea.clear()
        textarea.send_keys("First instance annotation")

        time.sleep(1)

        # Navigate to next instance
        print("🔍 Navigating to next instance")
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for the new instance to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        print("🔍 After navigation:")
        self.debug_print_instance_info()

        # Make different annotations on second instance
        print("🔍 Making different annotations on second instance...")

        likert_buttons = self.driver.find_elements(By.NAME, "quality_rating")
        # Click on the label for rating 5 (index 4)
        button_id = likert_buttons[4].get_attribute("id")
        label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
        label.click()

        radio_buttons = self.driver.find_elements(By.NAME, "sentiment")
        for button in radio_buttons:
            if button.get_attribute("value") == "3":  # Negative is third option (value="3")
                button_id = button.get_attribute("id")
                label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
                label.click()
                break

        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        self.driver.execute_script("arguments[0].value = '8';", slider)
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", slider)

        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        textarea.clear()
        textarea.send_keys("Second instance annotation")

        time.sleep(1)

        # Navigate back to first instance
        print("🔍 Navigating back to first instance")
        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()

        # Wait for the first instance to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        print("🔍 Back to first instance:")
        self.debug_print_instance_info()

        # Verify that first instance annotations are isolated (not persisted)
        print("🔍 Verifying first instance annotations are isolated after multiple cycles...")

        # Check likert - should NOT be selected
        try:
            selected_likert = self.driver.find_element(By.CSS_SELECTOR, 'input[name="quality_rating"]:checked')
            print(f"🔍 ERROR: Likert rating persisted after cycles: {selected_likert.get_attribute('value')}")
            assert False, "Likert rating persisted after multiple cycles when it should be isolated"
        except:
            print("🔍 SUCCESS: Likert rating isolated after multiple cycles")

        # Check radio - should NOT be selected
        try:
            selected_radio = self.driver.find_element(By.CSS_SELECTOR, 'input[name="sentiment"]:checked')
            print(f"🔍 ERROR: Radio button persisted after cycles: {selected_radio.get_attribute('value')}")
            assert False, "Radio button persisted after multiple cycles when it should be isolated"
        except:
            print("🔍 SUCCESS: Radio button isolated after multiple cycles")

        # Check slider - should be reset to default
        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        slider_value = slider.get_attribute("value")
        print(f"🔍 Slider value: {slider_value}")
        if slider_value != "6":
            print("🔍 SUCCESS: Slider isolated after multiple cycles")
        else:
            print(f"🔍 ERROR: Slider persisted after cycles: {slider_value}")
            assert False, "Slider persisted after multiple cycles when it should be isolated"

        # Check text - should be empty
        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        textarea_value = textarea.get_attribute("value")
        print(f"🔍 Textarea value: '{textarea_value}'")
        if textarea_value == "":
            print("🔍 SUCCESS: Textarea isolated after multiple cycles")
        else:
            print(f"🔍 ERROR: Textarea persisted after cycles: '{textarea_value}'")
            assert False, "Textarea persisted after multiple cycles when it should be isolated"

        print("🔍 SUCCESS: First instance annotations are properly isolated after multiple navigation cycles")

    def test_multiple_navigation_cycles(self):
        """
        Test that annotations persist correctly across multiple navigation cycles.
        """
        print("\n🔍 Starting multiple navigation cycles test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        print("🔍 Initial page load complete")
        self.debug_print_instance_info()

        # Wait for annotation forms to load
        self.wait_for_element(By.NAME, "quality_rating")
        self.wait_for_element(By.NAME, "sentiment")
        self.wait_for_element(By.NAME, "complexity:::slider")
        self.wait_for_element(By.NAME, "summary:::text_box")
        print("🔍 All annotation forms loaded")

        # Make annotations on first instance
        print("🔍 Making annotations on first instance...")

        likert_buttons = self.driver.find_elements(By.NAME, "quality_rating")
        # Click on the label for rating 3 (index 2)
        button_id = likert_buttons[2].get_attribute("id")
        label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
        label.click()

        radio_buttons = self.driver.find_elements(By.NAME, "sentiment")
        for button in radio_buttons:
            if button.get_attribute("value") == "2":  # Neutral is second option (value="2")
                button_id = button.get_attribute("id")
                label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{button_id}"]')
                label.click()
                break

        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        self.driver.execute_script("arguments[0].value = '6';", slider)
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", slider)

        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        textarea.clear()
        textarea.send_keys("Cycle test annotation")

        time.sleep(1)

        # Navigate through multiple instances and back
        print("🔍 Navigating through multiple instances...")

        for i in range(3):  # Navigate through 3 instances
            next_button = self.driver.find_element(By.ID, "next-btn")
            next_button.click()
            self.wait_for_element(By.ID, "instance-text")
            time.sleep(1)
            print(f"🔍 Navigated to instance {i+2}")

        # Navigate back to first instance
        print("🔍 Navigating back to first instance...")
        for i in range(3):  # Navigate back through 3 instances
            prev_button = self.driver.find_element(By.ID, "prev-btn")
            prev_button.click()
            self.wait_for_element(By.ID, "instance-text")
            time.sleep(1)
            print(f"🔍 Navigated back to instance {3-i}")

        print("🔍 Back to first instance:")
        self.debug_print_instance_info()

        # Verify that first instance annotations are isolated (not persisted)
        print("🔍 Verifying first instance annotations are isolated after multiple cycles...")

        # Verify that first instance annotations are isolated (not persisted)
        print("🔍 Verifying first instance annotations are isolated after multiple cycles...")

        # Check likert - should NOT be selected
        try:
            selected_likert = self.driver.find_element(By.CSS_SELECTOR, 'input[name="quality_rating"]:checked')
            print(f"🔍 ERROR: Likert rating persisted after cycles: {selected_likert.get_attribute('value')}")
            assert False, "Likert rating persisted after multiple cycles when it should be isolated"
        except:
            print("🔍 SUCCESS: Likert rating isolated after multiple cycles")

        # Check radio - should NOT be selected
        try:
            selected_radio = self.driver.find_element(By.CSS_SELECTOR, 'input[name="sentiment"]:checked')
            print(f"🔍 ERROR: Radio button persisted after cycles: {selected_radio.get_attribute('value')}")
            assert False, "Radio button persisted after multiple cycles when it should be isolated"
        except:
            print("🔍 SUCCESS: Radio button isolated after multiple cycles")

        # Check slider - should be reset to default
        slider = self.driver.find_element(By.NAME, "complexity:::slider")
        slider_value = slider.get_attribute("value")
        print(f"🔍 Slider value: {slider_value}")
        if slider_value != "6":
            print("🔍 SUCCESS: Slider isolated after multiple cycles")
        else:
            print(f"🔍 ERROR: Slider persisted after cycles: {slider_value}")
            assert False, "Slider persisted after multiple cycles when it should be isolated"

        # Check text - should be empty
        textarea = self.driver.find_element(By.NAME, "summary:::text_box")
        textarea_value = textarea.get_attribute("value")
        print(f"🔍 Textarea value: '{textarea_value}'")
        if textarea_value == "":
            print("🔍 SUCCESS: Textarea isolated after multiple cycles")
        else:
            print(f"🔍 ERROR: Textarea persisted after cycles: '{textarea_value}'")
            assert False, "Textarea persisted after multiple cycles when it should be isolated"

        print("🔍 SUCCESS: First instance annotations are properly isolated after multiple navigation cycles")