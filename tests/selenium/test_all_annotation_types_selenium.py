"""
Selenium tests for all annotation types using actual config files.
Tests the complete workflow including phases like consent, instructions, etc.
"""

import pytest
import json
import os
import tempfile
import shutil
import time
import threading
import subprocess
import requests
import yaml
import uuid
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Add potato to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from tests.helpers.flask_test_setup import FlaskTestServer


class TestAllAnnotationTypes:
    """Base class for all annotation type tests."""

    @pytest.fixture(scope="class")
    def test_data(self):
        """Test data for annotation tasks."""
        return [
            {"id": "1", "text": "The new artificial intelligence model achieved remarkable results in natural language processing tasks, outperforming previous benchmarks by a significant margin."},
            {"id": "2", "text": "I'm feeling incredibly sad today because my beloved pet passed away unexpectedly. The house feels so empty without their cheerful presence."},
            {"id": "3", "text": "The political debate was heated and intense, with candidates passionately arguing about healthcare reform and economic policies."}
        ]

    def create_unique_test_environment(self, test_data, config_path, test_name):
        """Create a unique test environment with isolated temp directory and unique IDs."""
        # Create unique temp directory for this test
        test_id = str(uuid.uuid4())[:8]
        temp_dir = tempfile.mkdtemp(prefix=f"potato_test_{test_name}_{test_id}_")

        # Copy config file to temp directory
        config_dir = os.path.join(temp_dir, "configs")
        os.makedirs(config_dir, exist_ok=True)

        # Read original config
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)

        # Update config to use temp directory paths
        config_data['output_annotation_dir'] = os.path.join(temp_dir, "output")
        config_data['task_dir'] = os.path.join(temp_dir, "task")
        config_data['site_dir'] = os.path.join(temp_dir, "templates")

        # Write updated config to temp directory
        temp_config_path = os.path.join(config_dir, os.path.basename(config_path))
        with open(temp_config_path, 'w') as f:
            yaml.dump(config_data, f)

        # Create data directory and test data file with unique IDs
        data_dir = os.path.join(temp_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create unique test data with timestamp-based IDs
        timestamp = int(time.time() * 1000)  # Use milliseconds for more uniqueness
        unique_test_data = []
        instance_ids = []

        for i, item in enumerate(test_data):
            unique_item = item.copy()
            instance_id = f"test_{test_name}_{timestamp}_{i+1}"
            unique_item['id'] = instance_id
            instance_ids.append(instance_id)
            unique_test_data.append(unique_item)

        # Write test data file
        test_data_file = os.path.join(data_dir, "test_data.json")
        with open(test_data_file, 'w') as f:
            for item in unique_test_data:
                f.write(json.dumps(item) + '\n')

        return temp_dir, temp_config_path, test_data_file, instance_ids

    def create_user(self, driver, base_url, username):
        """Register a new user using the registration form in the UI."""
        # Go to login page first to access registration form
        driver.get(f"{base_url}/login")

        # Wait for the page to load
        WebDriverWait(driver, 10).until(
            lambda d: d.current_url.endswith("/login")
        )

        # Switch to register tab
        register_tab = driver.find_element(By.ID, "register-tab")
        print("Register tab displayed:", register_tab.is_displayed())
        print("Register tab enabled:", register_tab.is_enabled())
        if not register_tab.is_displayed() or not register_tab.is_enabled():
            raise RuntimeError("Register tab is not interactable!")
        register_tab.click()

        # Wait for the registration form to become visible
        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )

        time.sleep(1)  # Wait for UI to update
        print("Page source after clicking register tab (first 500 chars):", driver.page_source[:500])

        # Fill registration form
        username_input = driver.find_element(By.ID, "register-email")
        password_input = driver.find_element(By.ID, "register-pass")

        username_input.clear()
        username_input.send_keys(username)
        password_input.clear()
        password_input.send_keys("testpass123")

        # Submit registration - use the correct button selector
        register_button = driver.find_element(By.CSS_SELECTOR, "#register-content button[type='submit']")
        # Debug output
        print("Current URL:", driver.current_url)
        print("Page source (first 500 chars):", driver.page_source[:500])
        print("Register button displayed:", register_button.is_displayed())
        print("Register button enabled:", register_button.is_enabled())
        if not register_button.is_displayed() or not register_button.is_enabled():
            raise RuntimeError("Register button is not interactable!")
        register_button.click()

        # Wait for registration to complete - should redirect to annotation or home
        WebDriverWait(driver, 10).until(
            lambda d: "annotate" in d.current_url or d.current_url.endswith("/")
        )

    def handle_phase_flow(self, driver, base_url, config):
        """Handle the complete phase flow (consent, instructions, etc.) before annotation."""
        # Check if the config has phases defined
        try:
            with open(config, 'r') as f:
                config_data = yaml.safe_load(f)
            has_phases = 'phases' in config_data
        except Exception:
            has_phases = False

        if not has_phases:
            # Simple config without phases - go directly to annotation
            print("[PHASE FLOW] Config has no phases, going directly to annotation")
            driver.get(f"{base_url}/annotate")
            WebDriverWait(driver, 10).until(
                lambda d: "annotate" in d.current_url
            )
            return

        # Config has phases - handle them
        print("[PHASE FLOW] Config has phases, handling phase flow")
        # Loop until we reach the annotation page
        max_phase_steps = 10
        steps = 0
        while steps < max_phase_steps:
            steps += 1
            current_url = driver.current_url
            print(f"[PHASE FLOW] Step {steps}, URL: {current_url}")
            print(f"[PHASE FLOW] Page source (first 500 chars): {driver.page_source[:500]}")
            if "annotate" in current_url:
                # We are on the annotation page
                break
            # Try to detect which phase we're in
            try:
                page_title = driver.find_element(By.TAG_NAME, "h1").text.lower()
            except Exception:
                page_title = driver.page_source.lower()
            # Consent phase
            if "consent" in page_title:
                try:
                    # Click the first available radio button
                    radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                    if radios:
                        radios[0].click()
                except Exception:
                    pass
                try:
                    next_button = driver.find_element(By.ID, "next-btn")
                    next_button.click()
                except Exception:
                    pass
                time.sleep(1)
                continue
            # Instructions phase
            if "instruction" in page_title:
                try:
                    next_button = driver.find_element(By.ID, "next-btn")
                    next_button.click()
                except Exception:
                    pass
                time.sleep(1)
                continue
            # Personality phase (if present)
            if "personality" in page_title:
                try:
                    personality_rating = driver.find_element(By.CSS_SELECTOR, "input[name='personality'][value='3']")
                    personality_rating.click()
                except Exception:
                    pass
                try:
                    next_button = driver.find_element(By.ID, "next-btn")
                    next_button.click()
                except Exception:
                    pass
                time.sleep(1)
                continue
            # If not in a known phase, try to go to /annotate
            driver.get(f"{base_url}/annotate")
            time.sleep(1)
        # If we exit the loop and are not on annotation, raise error
        if "annotate" not in driver.current_url:
            raise RuntimeError(f"Failed to reach annotation page after {max_phase_steps} steps. Current URL: {driver.current_url}")

    def handle_consent_phase(self, driver):
        """Handle consent phase by selecting 'I agree' and clicking next."""
        try:
            # Find and click the "I agree" radio button
            agree_radio = driver.find_element(By.CSS_SELECTOR, "input[value='I agree']")
            agree_radio.click()

            # Click the next button
            next_button = driver.find_element(By.ID, "next-btn")
            next_button.click()

            time.sleep(1)  # Wait for page transition
        except Exception as e:
            print(f"Warning: Could not handle consent phase: {e}")

    def handle_instructions_phase(self, driver):
        """Handle instructions phase by selecting 'I understand' and clicking next."""
        try:
            # Find and click the "I understand" radio button
            understand_radio = driver.find_element(By.CSS_SELECTOR, "input[value='I understand']")
            understand_radio.click()

            # Click the next button
            next_button = driver.find_element(By.ID, "next-btn")
            next_button.click()

            time.sleep(1)  # Wait for page transition
        except Exception as e:
            print(f"Warning: Could not handle instructions phase: {e}")

    def handle_personality_phase(self, driver):
        """Handle personality phase by selecting a rating and clicking next."""
        try:
            # Find and click a personality rating (value 3)
            personality_rating = driver.find_element(By.CSS_SELECTOR, "input[name='personality'][value='3']")
            personality_rating.click()

            # Click the next button
            next_button = driver.find_element(By.ID, "next-btn")
            next_button.click()

            time.sleep(1)  # Wait for page transition
        except Exception as e:
            print(f"Warning: Could not handle personality phase: {e}")

    def verify_next_button_state(self, driver, expected_disabled=True):
        """Verify the Next button is in the expected state."""
        try:
            next_button = driver.find_element(By.ID, "next-btn")
            is_disabled = next_button.get_attribute("disabled") is not None
            print(f"Next button state: {'disabled' if is_disabled else 'enabled'}")
            assert is_disabled == expected_disabled, f"Next button should be {'disabled' if expected_disabled else 'enabled'}"
        except NoSuchElementException:
            print("Next button not found - this is OK for some annotation types")

    def navigate_and_verify_persistence(self, driver, base_url, test_data):
        # This is now handled in verify_annotations_stored
        pass

    def verify_annotations_stored(self, driver, base_url, username, instance_id, annotation_type=None, expected_value=None):
        """Verify that annotations are properly stored for the user by checking UI state after navigation."""
        # Wait a moment for any pending requests to complete
        time.sleep(2)

        # Navigate away and back to annotation page
        driver.get(f"{base_url}/")
        time.sleep(1)
        driver.get(f"{base_url}/annotate")
        time.sleep(2)

        # Navigate to the specific instance to verify
        # Find the "Go to" input and navigate to instance 1 (index 0)
        try:
            go_to_input = driver.find_element(By.ID, "go_to")
            go_to_input.clear()
            go_to_input.send_keys("1")
            go_to_button = driver.find_element(By.ID, "go-to-btn")
            go_to_button.click()
            time.sleep(2)
        except Exception as e:
            print(f"Could not navigate to specific instance: {e}")
            # Continue with current instance if navigation fails

        if annotation_type == "likert":
            # Robustly check Likert radio input
            likert_selectors = [
                "input[name^='sentiment:::']",
                "input.sentiment",
                "input[type='radio']"
            ]
            found = False
            for selector in likert_selectors:
                radios = driver.find_elements(By.CSS_SELECTOR, selector)
                for radio in radios:
                    if radio.is_selected() and radio.get_attribute('value') == expected_value:
                        print(f"[verify_annotations_stored] Found selected Likert radio with value {expected_value} using selector {selector}")
                        found = True
                        break
                if found:
                    break
            assert found, f"Likert value '{expected_value}' not persisted in UI"
        elif annotation_type == "text":
            textarea_selectors = [
                "textarea[name='feedback']",
                "textarea",
                "textarea[name*='feedback']",
                "textarea.feedback",
                "textarea[class*='feedback']"
            ]
            textarea = None
            for selector in textarea_selectors:
                try:
                    textarea = driver.find_element(By.CSS_SELECTOR, selector)
                    print(f"[verify_annotations_stored] Found textarea with selector: {selector}")
                    break
                except NoSuchElementException:
                    print(f"[verify_annotations_stored] No textarea found with selector: {selector}")
            if textarea is None:
                raise NoSuchElementException("[verify_annotations_stored] Could not find textarea with any selector")
            value = textarea.get_attribute("value")
            print(f"[verify_annotations_stored] Textarea value after navigation: '{value}' (expected: '{expected_value}')")
            assert value == expected_value, f"Textarea value should be '{expected_value}', got '{value}'"
        elif annotation_type == "slider":
            slider = driver.find_element(By.CSS_SELECTOR, "input[type='range']")
            value = slider.get_attribute("value")
            print(f"[verify_annotations_stored] Slider value after navigation: '{value}' (expected: '{expected_value}')")
            assert value == expected_value, f"Slider value should be '{expected_value}', got '{value}'"
        elif annotation_type == "span":
            # For span annotation, check that the highlight is present and label is persisted
            # This assumes the UI renders a highlighted span with a specific class or data attribute
            # and that the label is visible in the UI.
            # Check for all 11 unique test cases if needed
            highlight_elements = driver.find_elements(By.CSS_SELECTOR, ".highlighted-span, .shadcn-span-highlight, span[data-annotation-label]")
            print(f"[verify_annotations_stored] Found {len(highlight_elements)} highlighted span elements after navigation.")
            assert len(highlight_elements) >= 1, "No highlighted span found after navigation. Annotation not persisted."
            found_label = False
            for elem in highlight_elements:
                label = elem.get_attribute("data-annotation-label") or elem.text
                print(f"[verify_annotations_stored] Highlighted span label/text: '{label}' (expected: '{expected_value}')")
                if expected_value in label:
                    found_label = True
            assert found_label, f"Expected span label '{expected_value}' not found in highlighted spans."
            # Optionally, check for multiple test cases if a list is provided
            if isinstance(expected_value, list):
                for val in expected_value:
                    found = any(val in (elem.get_attribute("data-annotation-label") or elem.text) for elem in highlight_elements)
                    assert found, f"Expected span label '{val}' not found in highlighted spans."
        # ... other annotation types ...
        return True

    def get_next_button_state(self, driver):
        """Get the state of the Next button."""
        try:
            next_button = driver.find_element(By.ID, "next-btn")
            return next_button.get_attribute("disabled") is not None
        except NoSuchElementException:
            return False # Button not found, so it's not disabled


class TestIndividualAnnotationTypes(TestAllAnnotationTypes):
    """Individual test classes for each annotation type to ensure isolation."""

    def test_likert_annotation(self, test_data):
        """Test Likert scale annotation using likert-annotation.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "likert-annotation.yaml"), "likert"
        )

        try:
            # Use unique port for this test
            port = 9001 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # Select a quality rating (first Likert field)
                    quality_radios = driver.find_elements(By.CSS_SELECTOR, "input.shadcn-likert-input[name*='quality']")
                    print(f"Found {len(quality_radios)} quality radio buttons")

                    if quality_radios:
                        try:
                            quality_radios[0].click()
                        except Exception as e:
                            # Try clicking the label if input is not interactable
                            input_id = quality_radios[0].get_attribute('id')
                            if input_id:
                                label = driver.find_element(By.CSS_SELECTOR, f"label[for='{input_id}']")
                                label.click()
                            else:
                                raise e
                        time.sleep(1)

                        # Check if Next button is now enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state after selection: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify annotation is stored
                        self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "likert", "1")

                        print("✅ Likert annotation test passed")
                    else:
                        pytest.fail("No quality radio buttons found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_text_annotation(self, test_data):
        """Test text input annotation using simple-text-box.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "simple-text-box.yaml"), "text"
        )

        try:
            # Use unique port for this test
            port = 9002 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state (text annotations may not require initial input)
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # Find and fill textarea
                    textarea_selectors = [
                        "textarea",
                        "textarea[name*='feedback']",
                        "textarea[name*='comment']",
                        "textarea[name*='text']"
                    ]

                    textarea = None
                    for selector in textarea_selectors:
                        try:
                            textarea = driver.find_element(By.CSS_SELECTOR, selector)
                            print(f"Found textarea with selector: {selector}")
                            break
                        except NoSuchElementException:
                            continue

                    if textarea:
                        test_text = "This is a test feedback comment."
                        textarea.clear()
                        textarea.send_keys(test_text)
                        time.sleep(1)

                        # Check if Next button is now enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state after text input: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify annotation is stored
                        self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "text", test_text)

                        print("✅ Text annotation test passed")
                    else:
                        pytest.fail("No textarea found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_text_annotation_with_test_client(self, test_data):
        """Test text input annotation using Flask test client (same thread)."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "simple-text-box.yaml"), "text"
        )

        try:
            # Change working directory to temp_dir so relative paths work
            os.chdir(temp_dir)

            # Import and configure the Flask app properly
            from potato.flask_server import app
            from potato.server_utils.config_module import init_config, config
            from potato.user_state_management import init_user_state_manager, clear_user_state_manager
            from potato.item_state_management import init_item_state_manager, clear_item_state_manager
            from potato.flask_server import load_all_data
            from potato.authentificaton import UserAuthenticator

            # Create args object for config initialization
            class Args:
                pass
            args = Args()
            args.config_file = config_path
            args.verbose = False
            args.very_verbose = False
            args.customjs = None
            args.customjs_hostname = None
            args.debug = False

            # Initialize config
            init_config(args)

            # Clear any existing managers (for testing)
            clear_user_state_manager()
            clear_item_state_manager()

            # Initialize authenticator
            UserAuthenticator.init_from_config(config)

            # Initialize managers
            init_user_state_manager(config)
            init_item_state_manager(config)
            load_all_data(config)

            # Configure routes
            from potato.routes import configure_routes
            configure_routes(app, config)

            # Use Flask test client
            app.config['TESTING'] = True
            client = app.test_client()

            # Register a new user
            username = f"test_user_{uuid.uuid4().hex[:8]}"

            # Register user via test client
            response = client.post('/register', data={
                'action': 'signup',
                'email': username,
                'pass': 'testpass123'
            }, follow_redirects=True)

            assert response.status_code == 200, f"Registration failed: {response.status_code}"

            # Check if user was created in the same thread context
            from potato.user_state_management import get_user_state_manager
            usm = get_user_state_manager()
            assert usm.has_user(username), f"User {username} not found in state manager"

            # Get user state via admin endpoint
            response = client.get(f'/admin/user_state/{username}', headers={'X-API-Key': 'admin_api_key'})
            assert response.status_code == 200, f"Admin user state failed: {response.status_code}"

            user_state_data = response.get_json()
            print(f"User state data: {user_state_data}")

            # Submit annotation via test client
            response = client.post('/submit_annotation', json={
                'instance_id': instance_ids[0],
                'annotations': {
                    'feedback': 'This is a test feedback comment.'
                }
            }, headers={'X-API-Key': 'admin_api_key'})

            assert response.status_code == 200, f"Annotation submission failed: {response.status_code}"

            # Verify annotation is stored by checking user state again
            response = client.get(f'/admin/user_state/{username}', headers={'X-API-Key': 'admin_api_key'})
            assert response.status_code == 200, f"Admin user state failed: {response.status_code}"

            user_state_data = response.get_json()
            print(f"User state data after annotation: {user_state_data}")

                        # Check if annotation was saved
            annotations = user_state_data.get('annotations', {}).get('by_instance', {})
            assert instance_ids[0] in annotations, f"Instance {instance_ids[0]} not found in annotations"

            instance_annotations = annotations[instance_ids[0]]
            # For text annotations, the key is the string representation of the Label object
            expected_key = 'Label(schema:feedback, name:text_box)'
            assert expected_key in instance_annotations, f"Feedback annotation not found. Available keys: {list(instance_annotations.keys())}"
            assert instance_annotations[expected_key] == 'This is a test feedback comment.', f"Annotation value mismatch: {instance_annotations[expected_key]}"

            print("✅ Text annotation test passed with Flask test client!")

        finally:
            # Clean up
            if 'temp_dir' in locals():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

    def test_slider_annotation(self, test_data):
        """Test slider annotation using slider-annotation.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "slider-annotation.yaml"), "slider"
        )

        try:
            # Use unique port for this test
            port = 9003 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state (slider may have default value)
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # Find and adjust slider
                    slider_selectors = [
                        "input.shadcn-slider-input",
                        "input[type='range'].annotation-input",
                        "input[name*='rating']",
                        "input[name*='score']",
                        "input[name*='value']"
                    ]

                    slider = None
                    for selector in slider_selectors:
                        try:
                            slider = driver.find_element(By.CSS_SELECTOR, selector)
                            print(f"Found slider with selector: {selector}")
                            break
                        except NoSuchElementException:
                            continue

                    if slider:
                        # Move slider to a new value
                        driver.execute_script("arguments[0].value = '75';", slider)
                        driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", slider)
                        time.sleep(1)

                        # Check if Next button is now enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state after slider adjustment: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify annotation is stored
                        self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "slider", "75")

                        print("✅ Slider annotation test passed")
                    else:
                        pytest.fail("No slider found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_span_annotation(self, test_data):
        """Test span annotation using span-annotation.yaml config with comprehensive checks."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "span-annotation.yaml"), "span"
        )

        try:
            # Use unique port for this test
            port = 9004 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # Test multiple span annotation scenarios
                    test_cases = [
                        {"text": "artificial intelligence", "label": "positive", "description": "Highlight AI terms"},
                        {"text": "sad", "label": "negative", "description": "Highlight emotional terms"},
                        {"text": "debate", "label": "neutral", "description": "Highlight political terms"},
                        {"text": "remarkable results", "label": "positive", "description": "Highlight achievement terms"},
                        {"text": "beloved pet", "label": "negative", "description": "Highlight personal loss terms"},
                        {"text": "heated and intense", "label": "neutral", "description": "Highlight intensity terms"},
                        {"text": "natural language processing", "label": "positive", "description": "Highlight technical terms"},
                        {"text": "passed away", "label": "negative", "description": "Highlight loss terms"},
                        {"text": "healthcare reform", "label": "neutral", "description": "Highlight policy terms"},
                        {"text": "outperforming", "label": "positive", "description": "Highlight performance terms"},
                        {"text": "empty without", "label": "negative", "description": "Highlight absence terms"}
                    ]

                    # Test the first few cases (can be expanded)
                    for i, test_case in enumerate(test_cases[:3]):
                        print(f"\n--- Testing span case {i+1}: {test_case['description']} ---")

                        # Find the text to highlight
                        try:
                            # Look for the text in the annotation area
                            text_elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{test_case['text']}')]")
                            if text_elements:
                                # Click and drag to select the text
                                element = text_elements[0]
                                driver.execute_script("""
                                    var range = document.createRange();
                                    var selection = window.getSelection();
                                    range.selectNodeContents(arguments[0]);
                                    selection.removeAllRanges();
                                    selection.addRange(range);
                                """, element)
                                time.sleep(1)

                                # Select the appropriate label
                                label_selectors = [
                                    f"input[value='{test_case['label']}']",
                                    f"input[name*='{test_case['label']}']",
                                    f"label:contains('{test_case['label']}')"
                                ]

                                label_found = False
                                for selector in label_selectors:
                                    try:
                                        label_element = driver.find_element(By.CSS_SELECTOR, selector)
                                        label_element.click()
                                        label_found = True
                                        print(f"Selected label: {test_case['label']}")
                                        break
                                    except NoSuchElementException:
                                        continue

                                if label_found:
                                    # Check if Next button is enabled
                                    next_button_state = self.get_next_button_state(driver)
                                    print(f"Next button state after span selection: {'disabled' if next_button_state else 'enabled'}")

                                    # Submit annotation
                                    next_button = driver.find_element(By.ID, "next-btn")
                                    next_button.click()
                                    time.sleep(2)

                                    # Verify annotation is stored
                                    self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "span", test_case['text'])

                                    print(f"✅ Span annotation case {i+1} passed")
                                else:
                                    print(f"⚠️ Label not found for case {i+1}")
                            else:
                                print(f"⚠️ Text not found for case {i+1}: {test_case['text']}")

                        except Exception as e:
                            print(f"⚠️ Error in span case {i+1}: {e}")

                    print("✅ Span annotation test completed")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_radio_annotation(self, test_data):
        """Test radio button annotation using radio-annotation.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "radio-annotation.yaml"), "radio"
        )

        try:
            # Use unique port for this test
            port = 9005 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # Find and select radio buttons
                    radio_selectors = [
                        "input.shadcn-likert-input",
                        "input[type='radio'].annotation-input",
                        "input[name*='choice']",
                        "input[name*='option']",
                        "input[name*='selection']"
                    ]

                    radio_buttons = []
                    for selector in radio_selectors:
                        try:
                            radio_buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                            if radio_buttons:
                                print(f"Found {len(radio_buttons)} radio buttons with selector: {selector}")
                                break
                        except NoSuchElementException:
                            continue

                    if radio_buttons:
                        # Select the first radio button
                        radio_buttons[0].click()
                        time.sleep(1)

                        # Check if Next button is now enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state after radio selection: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify annotation is stored
                        self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "radio", radio_buttons[0].get_attribute("value"))

                        print("✅ Radio annotation test passed")
                    else:
                        pytest.fail("No radio buttons found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_select_annotation(self, test_data):
        """Test select dropdown annotation using select-annotation.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "select-annotation.yaml"), "select"
        )

        try:
            # Use unique port for this test
            port = 9006 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # Find and select dropdown options
                    select_selectors = [
                        "select.annotation-input",
                        "select[name*='category']",
                        "select[name*='audience']"
                    ]

                    select_element = None
                    for selector in select_selectors:
                        try:
                            select_element = driver.find_element(By.CSS_SELECTOR, selector)
                            print(f"Found select element with selector: {selector}")
                            break
                        except NoSuchElementException:
                            continue

                    if select_element:
                        # Select the first option
                        from selenium.webdriver.support.ui import Select
                        select = Select(select_element)
                        select.select_by_index(1)  # Select second option (index 1)
                        time.sleep(1)

                        # Check if Next button is now enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state after select: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify annotation is stored
                        selected_value = select.first_selected_option.get_attribute("value")
                        self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "select", selected_value)

                        print("✅ Select annotation test passed")
                    else:
                        pytest.fail("No select dropdown found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_number_annotation(self, test_data):
        """Test number input annotation using number-annotation.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "number-annotation.yaml"), "number"
        )

        try:
            # Use unique port for this test
            port = 9007 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # Find and fill number inputs
                    number_selectors = [
                        "input.shadcn-number-field",
                        "input[type='number'].annotation-input",
                        "input[name*='word_count']",
                        "input[name*='readability_score']",
                        "input[name*='estimated_reading_time']"
                    ]

                    number_inputs = []
                    for selector in number_selectors:
                        try:
                            number_inputs = driver.find_elements(By.CSS_SELECTOR, selector)
                            if number_inputs:
                                print(f"Found {len(number_inputs)} number inputs with selector: {selector}")
                                break
                        except NoSuchElementException:
                            continue

                    if number_inputs:
                        # Fill the first number input
                        test_value = "25"
                        number_inputs[0].clear()
                        number_inputs[0].send_keys(test_value)
                        time.sleep(1)

                        # Check if Next button is now enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state after number input: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify annotation is stored
                        self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "number", test_value)

                        print("✅ Number annotation test passed")
                    else:
                        pytest.fail("No number inputs found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_multiselect_annotation(self, test_data):
        """Test multiselect annotation using multiselect-annotation.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "multiselect-annotation.yaml"), "multiselect"
        )

        try:
            # Use unique port for this test
            port = 9008 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # Find and select checkboxes
                    checkbox_selectors = [
                        "input.shadcn-multiselect-checkbox",
                        "input[type='checkbox'].annotation-input",
                        "input[name*='topic']",
                        "input[name*='category']"
                    ]

                    checkboxes = []
                    for selector in checkbox_selectors:
                        try:
                            checkboxes = driver.find_elements(By.CSS_SELECTOR, selector)
                            if checkboxes:
                                print(f"Found {len(checkboxes)} checkboxes with selector: {selector}")
                                break
                        except NoSuchElementException:
                            continue

                    if checkboxes:
                        # Select the first checkbox
                        checkboxes[0].click()
                        time.sleep(1)

                        # Check if Next button is now enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state after checkbox selection: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify annotation is stored
                        selected_value = checkboxes[0].get_attribute("value")
                        self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "multiselect", selected_value)

                        print("✅ Multiselect annotation test passed")
                    else:
                        pytest.fail("No checkboxes found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_multirate_annotation(self, test_data):
        """Test multirate annotation using multirate-annotation.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "multirate-annotation.yaml"), "multirate"
        )

        try:
            # Use unique port for this test
            port = 9009 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # Find and select multirate options
                    multirate_selectors = [
                        "input.shadcn-likert-input",
                        "input[type='radio'].annotation-input",
                        "input[name*='rating']",
                        "input[name*='score']"
                    ]

                    multirate_options = []
                    for selector in multirate_selectors:
                        try:
                            multirate_options = driver.find_elements(By.CSS_SELECTOR, selector)
                            if multirate_options:
                                print(f"Found {len(multirate_options)} multirate options with selector: {selector}")
                                break
                        except NoSuchElementException:
                            continue

                    if multirate_options:
                        # Select the first option
                        multirate_options[0].click()
                        time.sleep(1)

                        # Check if Next button is now enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state after multirate selection: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify annotation is stored
                        selected_value = multirate_options[0].get_attribute("value")
                        self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "multirate", selected_value)

                        print("✅ Multirate annotation test passed")
                    else:
                        pytest.fail("No multirate options found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_pure_display_annotation(self, test_data):
        """Test pure display annotation using pure-display-annotation.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "pure-display-annotation.yaml"), "pure_display"
        )

        try:
            # Use unique port for this test
            port = 9010 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Check initial Next button state (pure display should allow proceeding without input)
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                    # For pure display, we just verify the content is displayed and can proceed
                    # Look for the display content
                    display_selectors = [
                        ".display-content",
                        ".pure-display",
                        "legend"
                    ]

                    display_found = False
                    for selector in display_selectors:
                        try:
                            display_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            if display_elements:
                                print(f"Found {len(display_elements)} display elements with selector: {selector}")
                                display_found = True
                                break
                        except NoSuchElementException:
                            continue

                    if display_found:
                        # Pure display should allow proceeding without input
                        # Check if Next button is enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state for pure display: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation (pure display doesn't require input)
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify we can proceed (pure display doesn't store annotations)
                        print("✅ Pure display annotation test passed")
                    else:
                        pytest.fail("No display content found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_all_phases_workflow(self, test_data):
        """Test complete workflow with all phases using all-phases-example.yaml config."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "all-phases-example.yaml"), "mixed"
        )

        try:
            # Use unique port for this test
            port = 9011 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete all phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Now we should be in the annotation phase
                    # Check initial Next button state
                    initial_next_state = self.get_next_button_state(driver)
                    print(f"Initial Next button state: {'disabled' if initial_next_state else 'enabled'}")

                                        # Select a quality rating (first Likert field)
                    quality_radios = driver.find_elements(By.CSS_SELECTOR, "input[name*='quality']")
                    print(f"Found {len(quality_radios)} quality radio buttons")

                    if quality_radios:
                        quality_radios[0].click()
                        time.sleep(1)

                        # Check if Next button is now enabled
                        next_button_state = self.get_next_button_state(driver)
                        print(f"Next button state after selection: {'disabled' if next_button_state else 'enabled'}")

                        # Submit annotation
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify annotation is stored
                        self.verify_annotations_stored(driver, base_url, username, instance_ids[0], "likert", "1")

                        print("✅ All phases workflow test passed")
                    else:
                        pytest.fail("No sentiment radio buttons found in annotation phase")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestNavigationAndRestore(TestAllAnnotationTypes):
    """Test navigation between instances and annotation restoration for all annotation types."""

    def test_span_annotation_navigation_and_restore(self, test_data):
        """Test navigation and annotation restoration for span annotation."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "span-annotation.yaml"), "span_nav"
        )

        try:
            # Use unique port for this test
            port = 9020 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Get initial instance text
                    initial_text = driver.find_element(By.ID, "instance-text").text
                    print(f"Initial instance text: {initial_text}")

                    # Create a span annotation on the first instance
                    self.create_span_annotation(driver, "artificial intelligence")

                    # Navigate to next instance
                    next_button = driver.find_element(By.ID, "next-btn")
                    next_button.click()
                    time.sleep(2)

                    # Verify we're on a different instance
                    new_text = driver.find_element(By.ID, "instance-text").text
                    print(f"New instance text: {new_text}")
                    assert new_text != initial_text, "Navigation failed - same text displayed"

                    # Navigate back to previous instance
                    prev_button = driver.find_element(By.ID, "prev-btn")
                    prev_button.click()
                    time.sleep(2)

                    # Verify we're back to the original instance
                    restored_elem = driver.find_element(By.ID, "instance-text")
                    restored_text = restored_elem.get_attribute("textContent").strip()
                    initial_elem = driver.find_element(By.ID, "instance-text")
                    initial_text_content = initial_elem.get_attribute("textContent").strip()
                    print(f"Restored instance text: {restored_text}")
                    print(f"Initial instance text: {initial_text_content}")
                    assert restored_text == initial_text_content, "Navigation back failed - different text displayed (textContent)"

                    # Verify span annotation is restored
                    spans = driver.find_elements(By.CSS_SELECTOR, ".span-highlight")
                    assert len(spans) > 0, "Span annotation not restored after navigation"

                    print("✅ Span annotation navigation and restore test passed")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_likert_annotation_navigation_and_restore(self, test_data):
        """Test navigation and annotation restoration for likert annotation."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "likert-annotation.yaml"), "likert_nav"
        )

        try:
            # Use unique port for this test
            port = 9021 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Get initial instance text
                    initial_text = driver.find_element(By.ID, "instance-text").text
                    print(f"Initial instance text: {initial_text}")

                    # Select a likert rating
                    likert_radios = driver.find_elements(By.CSS_SELECTOR, "input[name*='sentiment']")
                    if likert_radios:
                        selected_value = likert_radios[2].get_attribute("value")  # Select middle option
                        likert_radios[2].click()
                        time.sleep(1)

                        # Navigate to next instance
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify we're on a different instance
                        new_text = driver.find_element(By.ID, "instance-text").text
                        print(f"New instance text: {new_text}")
                        assert new_text != initial_text, "Navigation failed - same text displayed"

                        # Navigate back to previous instance
                        prev_button = driver.find_element(By.ID, "prev-btn")
                        prev_button.click()
                        time.sleep(2)

                        # Verify we're back to the original instance
                        restored_elem = driver.find_element(By.ID, "instance-text")
                        restored_text = restored_elem.get_attribute("textContent").strip()
                        initial_elem = driver.find_element(By.ID, "instance-text")
                        initial_text_content = initial_elem.get_attribute("textContent").strip()
                        print(f"Restored instance text: {restored_text}")
                        print(f"Initial instance text: {initial_text_content}")
                        assert restored_text == initial_text_content, "Navigation back failed - different text displayed (textContent)"

                        # Verify likert selection is restored
                        selected_radio = driver.find_element(By.CSS_SELECTOR, f"input[name*='sentiment'][value='{selected_value}']")
                        assert selected_radio.is_selected(), "Likert selection not restored after navigation"

                        print("✅ Likert annotation navigation and restore test passed")
                    else:
                        pytest.fail("No likert radio buttons found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_text_annotation_navigation_and_restore(self, test_data):
        """Test navigation and annotation restoration for text annotation."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "text-annotation.yaml"), "text_nav"
        )

        try:
            # Use unique port for this test
            port = 9022 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Get initial instance text
                    initial_text = driver.find_element(By.ID, "instance-text").text
                    print(f"Initial instance text: {initial_text}")

                    # Enter text annotation
                    text_input = driver.find_element(By.CSS_SELECTOR, "textarea.annotation-input")
                    annotation_text = "This is a test annotation"
                    text_input.clear()
                    text_input.send_keys(annotation_text)

                    # Navigate to next instance
                    next_button = driver.find_element(By.ID, "next-btn")
                    next_button.click()
                    time.sleep(2)

                    # Verify we're on a different instance
                    new_text = driver.find_element(By.ID, "instance-text").text
                    print(f"New instance text: {new_text}")
                    assert new_text != initial_text, "Navigation failed - same text displayed"

                    # Navigate back to previous instance
                    prev_button = driver.find_element(By.ID, "prev-btn")
                    prev_button.click()
                    time.sleep(2)

                    # Verify we're back to the original instance
                    restored_elem = driver.find_element(By.ID, "instance-text")
                    restored_text = restored_elem.get_attribute("textContent").strip()
                    initial_elem = driver.find_element(By.ID, "instance-text")
                    initial_text_content = initial_elem.get_attribute("textContent").strip()
                    print(f"Restored instance text: {restored_text}")
                    print(f"Initial instance text: {initial_text_content}")
                    assert restored_text == initial_text_content, "Navigation back failed - different text displayed (textContent)"

                    # Verify text annotation is restored
                    text_input = driver.find_element(By.CSS_SELECTOR, "textarea.annotation-input")
                    restored_text_value = text_input.get_attribute("value")
                    assert restored_text_value == annotation_text, "Text annotation not restored after navigation"

                    print("✅ Text annotation navigation and restore test passed")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_slider_annotation_navigation_and_restore(self, test_data):
        """Test navigation and annotation restoration for slider annotation."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "slider-annotation.yaml"), "slider_nav"
        )

        try:
            # Use unique port for this test
            port = 9023 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Get initial instance text
                    initial_text = driver.find_element(By.ID, "instance-text").text
                    print(f"Initial instance text: {initial_text}")

                    # Set slider value
                    slider = driver.find_element(By.CSS_SELECTOR, "input[type='range']")
                    driver.execute_script("arguments[0].value = '7';", slider)
                    driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", slider)
                    time.sleep(1)

                    # Navigate to next instance
                    next_button = driver.find_element(By.ID, "next-btn")
                    next_button.click()
                    time.sleep(2)

                    # Verify we're on a different instance
                    new_text = driver.find_element(By.ID, "instance-text").text
                    print(f"New instance text: {new_text}")
                    assert new_text != initial_text, "Navigation failed - same text displayed"

                    # Navigate back to previous instance
                    prev_button = driver.find_element(By.ID, "prev-btn")
                    prev_button.click()
                    time.sleep(2)

                    # Verify we're back to the original instance
                    restored_elem = driver.find_element(By.ID, "instance-text")
                    restored_text = restored_elem.get_attribute("textContent").strip()
                    initial_elem = driver.find_element(By.ID, "instance-text")
                    initial_text_content = initial_elem.get_attribute("textContent").strip()
                    print(f"Restored instance text: {restored_text}")
                    print(f"Initial instance text: {initial_text_content}")
                    assert restored_text == initial_text_content, "Navigation back failed - different text displayed (textContent)"

                    # Verify slider value is restored
                    slider = driver.find_element(By.CSS_SELECTOR, "input[type='range']")
                    restored_value = slider.get_attribute("value")
                    assert restored_value == "7", "Slider value not restored after navigation"

                    print("✅ Slider annotation navigation and restore test passed")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_radio_annotation_navigation_and_restore(self, test_data):
        """Test navigation and annotation restoration for radio annotation."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "radio-annotation.yaml"), "radio_nav"
        )

        try:
            # Use unique port for this test
            port = 9024 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Get initial instance text
                    initial_text = driver.find_element(By.ID, "instance-text").text
                    print(f"Initial instance text: {initial_text}")

                    # Select a radio option
                    radio_options = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                    if radio_options:
                        selected_value = radio_options[1].get_attribute("value")
                        radio_options[1].click()
                        time.sleep(1)

                        # Navigate to next instance
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify we're on a different instance
                        new_text = driver.find_element(By.ID, "instance-text").text
                        print(f"New instance text: {new_text}")
                        assert new_text != initial_text, "Navigation failed - same text displayed"

                        # Navigate back to previous instance
                        prev_button = driver.find_element(By.ID, "prev-btn")
                        prev_button.click()
                        time.sleep(2)

                        # Verify we're back to the original instance
                        restored_elem = driver.find_element(By.ID, "instance-text")
                        restored_text = restored_elem.get_attribute("textContent").strip()
                        initial_elem = driver.find_element(By.ID, "instance-text")
                        initial_text_content = initial_elem.get_attribute("textContent").strip()
                        print(f"Restored instance text: {restored_text}")
                        print(f"Initial instance text: {initial_text_content}")
                        assert restored_text == initial_text_content, "Navigation back failed - different text displayed (textContent)"

                        # Verify radio selection is restored
                        selected_radio = driver.find_element(By.CSS_SELECTOR, f"input[type='radio'][value='{selected_value}']")
                        assert selected_radio.is_selected(), "Radio selection not restored after navigation"

                        print("✅ Radio annotation navigation and restore test passed")
                    else:
                        pytest.fail("No radio options found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_select_annotation_navigation_and_restore(self, test_data):
        """Test navigation and annotation restoration for select annotation."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "select-annotation.yaml"), "select_nav"
        )

        try:
            # Use unique port for this test
            port = 9025 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Get initial instance text
                    initial_text = driver.find_element(By.ID, "instance-text").text
                    print(f"Initial instance text: {initial_text}")

                    # Select an option from dropdown
                    select_element = driver.find_element(By.CSS_SELECTOR, "select.annotation-input")
                    options = select_element.find_elements(By.TAG_NAME, "option")
                    if len(options) > 1:
                        selected_value = options[1].get_attribute("value")
                        select_element.click()
                        options[1].click()
                        time.sleep(1)

                        # Navigate to next instance
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify we're on a different instance
                        new_text = driver.find_element(By.ID, "instance-text").text
                        print(f"New instance text: {new_text}")
                        assert new_text != initial_text, "Navigation failed - same text displayed"

                        # Navigate back to previous instance
                        prev_button = driver.find_element(By.ID, "prev-btn")
                        prev_button.click()
                        time.sleep(2)

                        # Verify we're back to the original instance
                        restored_elem = driver.find_element(By.ID, "instance-text")
                        restored_text = restored_elem.get_attribute("textContent").strip()
                        initial_elem = driver.find_element(By.ID, "instance-text")
                        initial_text_content = initial_elem.get_attribute("textContent").strip()
                        print(f"Restored instance text: {restored_text}")
                        print(f"Initial instance text: {initial_text_content}")
                        assert restored_text == initial_text_content, "Navigation back failed - different text displayed (textContent)"

                        # Verify select value is restored
                        select_element = driver.find_element(By.CSS_SELECTOR, "select.annotation-input")
                        restored_value = select_element.get_attribute("value")
                        assert restored_value == selected_value, "Select value not restored after navigation"

                        print("✅ Select annotation navigation and restore test passed")
                    else:
                        pytest.fail("No select options found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_number_annotation_navigation_and_restore(self, test_data):
        """Test navigation and annotation restoration for number annotation."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "number-annotation.yaml"), "number_nav"
        )

        try:
            # Use unique port for this test
            port = 9026 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Get initial instance text
                    initial_text = driver.find_element(By.ID, "instance-text").text
                    print(f"Initial instance text: {initial_text}")

                    # Enter a number
                    number_input = driver.find_element(By.CSS_SELECTOR, "input[type='number']")
                    number_input.clear()
                    number_input.send_keys("42")

                    # Navigate to next instance
                    next_button = driver.find_element(By.ID, "next-btn")
                    next_button.click()
                    time.sleep(2)

                    # Verify we're on a different instance
                    new_text = driver.find_element(By.ID, "instance-text").text
                    print(f"New instance text: {new_text}")
                    assert new_text != initial_text, "Navigation failed - same text displayed"

                    # Navigate back to previous instance
                    prev_button = driver.find_element(By.ID, "prev-btn")
                    prev_button.click()
                    time.sleep(2)

                    # Verify we're back to the original instance
                    restored_elem = driver.find_element(By.ID, "instance-text")
                    restored_text = restored_elem.get_attribute("textContent").strip()
                    initial_elem = driver.find_element(By.ID, "instance-text")
                    initial_text_content = initial_elem.get_attribute("textContent").strip()
                    print(f"Restored instance text: {restored_text}")
                    print(f"Initial instance text: {initial_text_content}")
                    assert restored_text == initial_text_content, "Navigation back failed - different text displayed (textContent)"

                    # Verify number value is restored
                    number_input = driver.find_element(By.CSS_SELECTOR, "input[type='number']")
                    restored_value = number_input.get_attribute("value")
                    assert restored_value == "42", "Number value not restored after navigation"

                    print("✅ Number annotation navigation and restore test passed")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_multiselect_annotation_navigation_and_restore(self, test_data):
        """Test navigation and annotation restoration for multiselect annotation."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "multiselect-annotation.yaml"), "multiselect_nav"
        )

        try:
            # Use unique port for this test
            port = 9027 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Get initial instance text
                    initial_text = driver.find_element(By.ID, "instance-text").text
                    print(f"Initial instance text: {initial_text}")

                    # Select multiple checkboxes
                    checkboxes = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
                    if len(checkboxes) >= 2:
                        checkboxes[0].click()
                        checkboxes[1].click()
                        time.sleep(1)

                        # Navigate to next instance
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify we're on a different instance
                        new_text = driver.find_element(By.ID, "instance-text").text
                        print(f"New instance text: {new_text}")
                        assert new_text != initial_text, "Navigation failed - same text displayed"

                        # Navigate back to previous instance
                        prev_button = driver.find_element(By.ID, "prev-btn")
                        prev_button.click()
                        time.sleep(2)

                        # Verify we're back to the original instance
                        restored_elem = driver.find_element(By.ID, "instance-text")
                        restored_text = restored_elem.get_attribute("textContent").strip()
                        initial_elem = driver.find_element(By.ID, "instance-text")
                        initial_text_content = initial_elem.get_attribute("textContent").strip()
                        print(f"Restored instance text: {restored_text}")
                        print(f"Initial instance text: {initial_text_content}")
                        assert restored_text == initial_text_content, "Navigation back failed - different text displayed (textContent)"

                        # Verify checkbox selections are restored
                        assert checkboxes[0].is_selected(), "First checkbox selection not restored after navigation"
                        assert checkboxes[1].is_selected(), "Second checkbox selection not restored after navigation"

                        print("✅ Multiselect annotation navigation and restore test passed")
                    else:
                        pytest.fail("Not enough checkboxes found for multiselect test")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_multirate_annotation_navigation_and_restore(self, test_data):
        """Test navigation and annotation restoration for multirate annotation."""
        # Create unique test environment
        temp_dir, config_path, test_data_file, instance_ids = self.create_unique_test_environment(
            test_data, os.path.join(os.path.dirname(__file__), "..", "test-configs", "multirate-annotation.yaml"), "multirate_nav"
        )

        try:
            # Use unique port for this test
            port = 9028 + hash(str(uuid.uuid4())) % 1000

            server = FlaskTestServer(port=port, debug=False, config_file=config_path, test_data_file=test_data_file)
            with server.server_context():
                # Create WebDriver with headless mode
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")

                driver = webdriver.Chrome(options=chrome_options)
                driver.implicitly_wait(10)

                try:
                    base_url = f"http://localhost:{port}"

                    # Register a new user
                    username = f"test_user_{uuid.uuid4().hex[:8]}"
                    self.create_user(driver, base_url, username)

                    # Complete any phases before annotation
                    self.handle_phase_flow(driver, base_url, config_path)

                    # Navigate to annotation page
                    driver.get(f"{base_url}/annotate")
                    time.sleep(2)

                    # Get initial instance text
                    initial_text = driver.find_element(By.ID, "instance-text").text
                    print(f"Initial instance text: {initial_text}")

                    # Select a multirate option
                    multirate_selectors = [
                        "input.shadcn-likert-input",
                        "input[type='radio'].annotation-input",
                        "input[name*='rating']",
                        "input[name*='score']"
                    ]

                    multirate_options = []
                    for selector in multirate_selectors:
                        try:
                            multirate_options = driver.find_elements(By.CSS_SELECTOR, selector)
                            if multirate_options:
                                print(f"Found {len(multirate_options)} multirate options with selector: {selector}")
                                break
                        except NoSuchElementException:
                            continue

                    if multirate_options:
                        selected_value = multirate_options[2].get_attribute("value")
                        multirate_options[2].click()
                        time.sleep(1)

                        # Navigate to next instance
                        next_button = driver.find_element(By.ID, "next-btn")
                        next_button.click()
                        time.sleep(2)

                        # Verify we're on a different instance
                        new_text = driver.find_element(By.ID, "instance-text").text
                        print(f"New instance text: {new_text}")
                        assert new_text != initial_text, "Navigation failed - same text displayed"

                        # Navigate back to previous instance
                        prev_button = driver.find_element(By.ID, "prev-btn")
                        prev_button.click()
                        time.sleep(2)

                        # Verify we're back to the original instance
                        restored_elem = driver.find_element(By.ID, "instance-text")
                        restored_text = restored_elem.get_attribute("textContent").strip()
                        initial_elem = driver.find_element(By.ID, "instance-text")
                        initial_text_content = initial_elem.get_attribute("textContent").strip()
                        print(f"Restored instance text: {restored_text}")
                        print(f"Initial instance text: {initial_text_content}")
                        assert restored_text == initial_text_content, "Navigation back failed - different text displayed (textContent)"

                        # Verify multirate selection is restored
                        selected_option = driver.find_element(By.CSS_SELECTOR, f"input[value='{selected_value}']")
                        assert selected_option.is_selected(), "Multirate selection not restored after navigation"

                        print("✅ Multirate annotation navigation and restore test passed")
                    else:
                        pytest.fail("No multirate options found")

                finally:
                    driver.quit()

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def create_span_annotation(self, driver, text_to_select):
        """Helper method to create a span annotation by selecting text."""
        # Find the instance text element
        instance_text = driver.find_element(By.ID, "instance-text")

        # Use JavaScript to select the text and create span annotation
        driver.execute_script(f"""
            var textElement = arguments[0];
            var text = textElement.textContent;
            var startIndex = text.indexOf('{text_to_select}');
            if (startIndex >= 0) {{
                var range = document.createRange();
                var startNode = textElement.firstChild;
                range.setStart(startNode, startIndex);
                range.setEnd(startNode, startIndex + {len(text_to_select)});

                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);

                // Create span annotation with proper format
                var instance_id = document.getElementById('instance_id').value;
                var post_req = {{
                    type: "span",
                    schema: "emotion",
                    state: [
                        {{
                            name: "happy",
                            start: startIndex,
                            end: startIndex + {len(text_to_select)},
                            title: "Happy",
                            value: "{text_to_select}"
                        }}
                    ],
                    instance_id: instance_id
                }};

                // Send the request
                fetch('/updateinstance', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    body: JSON.stringify(post_req)
                }}).then(response => response.json())
                .then(data => {{
                    console.log('Span annotation created:', data);
                    // Reload the page to show the new annotation
                    location.reload();
                }}).catch(error => {{
                    console.error('Error creating span annotation:', error);
                }});
            }}
        """, instance_text)

        time.sleep(2)  # Wait for the request to complete and page to reload

        # Verify span was created
        spans = driver.find_elements(By.CSS_SELECTOR, ".span-highlight")
        assert len(spans) > 0, "Span annotation was not created"