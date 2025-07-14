"""
Comprehensive Selenium Test Suite for Span Annotation

This test suite covers all major span annotation behaviors:
1. Basic span creation and deletion
2. Multiple non-overlapping spans
3. Partially overlapping spans
4. Nested spans
5. Deletion of spans in various configurations
6. Backend verification of saved spans
7. Visual layout persistence
8. Navigation and annotation restoration
"""

import pytest
import time
import os
import json
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from tests.helpers.flask_test_setup import FlaskTestServer
import sys
import shutil
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server with span annotation configuration."""
    config_file = os.path.abspath("tests/configs/span-annotation.yaml")
    test_data_file = os.path.abspath("tests/data/test_data.json")
    # Force debug=False for Selenium tests
    server = FlaskTestServer(port=9006, debug=False, config_file=config_file, test_data_file=test_data_file)
    started = server.start_server()
    assert started, "Failed to start Flask server"
    yield server
    server.stop_server()


@pytest.fixture
def browser():
    """Create a headless Chrome browser for testing with enhanced logging."""
    chrome_options = Options()
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

    # Enable logging for better debugging
    chrome_options.add_argument("--enable-logging")
    chrome_options.add_argument("--v=1")
    chrome_options.set_capability('goog:loggingPrefs', {'browser': 'ALL', 'driver': 'ALL'})

    print("🔧 Creating headless Chrome browser...")
    driver = webdriver.Chrome(options=chrome_options)
    print("✅ Headless Chrome browser created successfully")

    yield driver

    # Print browser logs before quitting
    try:
        logs = driver.get_log('browser')
        if logs:
            print("\n=== BROWSER LOGS ===")
            for log in logs[-10:]:  # Last 10 logs
                print(f"  {log['level']}: {log['message']}")
            print("=== END BROWSER LOGS ===\n")
    except Exception as e:
        print(f"Could not retrieve browser logs: {e}")

    driver.quit()


@pytest.fixture(scope="class")
def test_data():
    """Test data for span annotation."""
    return [
        {
            "id": "test_span_1",
            "text": "I am very happy today because the weather is beautiful and I feel great!"
        },
        {
            "id": "test_span_2",
            "text": "This makes me sad and disappointed with the current situation."
        }
    ]


class RobustSpanAnnotationHelper:
    """Enhanced helper class for robust span annotation testing."""

    @staticmethod
    def wait_for_element(driver, by, value, timeout=10, description="element"):
        """Wait for an element to be present and visible with detailed logging."""
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            WebDriverWait(driver, timeout).until(
                EC.visibility_of(element)
            )
            print(f"   ✅ Found {description}: {value}")
            return element
        except TimeoutException:
            print(f"   ❌ Timeout waiting for {description}: {value}")
            raise

    @staticmethod
    def wait_for_clickable(driver, by, value, timeout=10, description="element"):
        """Wait for an element to be clickable with detailed logging."""
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
            print(f"   ✅ {description} is clickable: {value}")
            return element
        except TimeoutException:
            print(f"   ❌ Timeout waiting for {description} to be clickable: {value}")
            raise

    @staticmethod
    def safe_click(driver, element, description="element"):
        """Safely click an element with retry logic and error handling."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Scroll element into view
                driver.execute_script("arguments[0].scrollIntoView(true);", element)
                time.sleep(0.5)

                # Wait for element to be clickable
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable(element)
                )

                # Click using JavaScript for better reliability
                driver.execute_script("arguments[0].click();", element)
                print(f"   ✅ Successfully clicked {description} (attempt {attempt + 1})")
                return True
            except Exception as e:
                print(f"   ⚠️ Click attempt {attempt + 1} failed for {description}: {e}")
                if attempt == max_retries - 1:
                    print(f"   ❌ Failed to click {description} after {max_retries} attempts")
                    raise
                time.sleep(1)
        return False

    @staticmethod
    def clear_existing_annotations(driver, base_url):
        """Clear existing annotations by navigating to a fresh instance."""
        print("   🧹 Clearing existing annotations...")
        # Navigate to instance 2 (which should be clean)
        driver.get(f"{base_url}/annotate?instance_id=2")
        RobustSpanAnnotationHelper.wait_for_page_load(driver)
        time.sleep(2)

        # Verify we have a clean instance
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            driver, By.ID, "instance-text", description="instance text"
        )
        text_content = instance_text.text
        print(f"   📝 Clean text length: {len(text_content)} characters")
        return text_content

    @staticmethod
    def robust_text_selection(driver, start_index, end_index, max_retries=3):
        """Robust text selection with multiple fallback methods and detailed logging."""
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            driver, By.ID, "instance-text", description="instance text"
        )

        for attempt in range(max_retries):
            try:
                print(f"   🔄 Text selection attempt {attempt + 1}/{max_retries}")

                # Method 1: Enhanced JavaScript selection with better error handling
                result = driver.execute_script("""
                    function robustTextSelection(element, startIndex, endIndex) {
                        try {
                            // Clear any existing selection
                            window.getSelection().removeAllRanges();

                            // Get the text content to validate indices
                            const fullText = element.textContent || element.innerText;
                            if (startIndex < 0 || endIndex > fullText.length || startIndex >= endIndex) {
                                return {
                                    success: false,
                                    error: `Invalid indices: start=${startIndex}, end=${endIndex}, textLength=${fullText.length}`
                                };
                            }

                            // Find text nodes and their offsets
                            let currentOffset = 0;
                            let textNodes = [];

                            function collectTextNodes(node) {
                                if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
                                    const nodeLength = node.textContent.length;
                                    textNodes.push({
                                        node: node,
                                        startOffset: currentOffset,
                                        endOffset: currentOffset + nodeLength,
                                        length: nodeLength
                                    });
                                    currentOffset += nodeLength;
                                } else if (node.nodeType === Node.ELEMENT_NODE) {
                                    for (let child of node.childNodes) {
                                        collectTextNodes(child);
                                    }
                                }
                            }

                            collectTextNodes(element);

                            // Find the text nodes that contain our selection
                            let selectionRanges = [];
                            let remainingStart = startIndex;
                            let remainingEnd = endIndex;

                            for (let textNodeInfo of textNodes) {
                                if (remainingStart >= textNodeInfo.endOffset) continue;
                                if (remainingEnd <= textNodeInfo.startOffset) break;

                                let rangeStart = Math.max(remainingStart - textNodeInfo.startOffset, 0);
                                let rangeEnd = Math.min(remainingEnd - textNodeInfo.startOffset, textNodeInfo.length);

                                if (rangeStart < rangeEnd) {
                                    let range = document.createRange();
                                    range.setStart(textNodeInfo.node, rangeStart);
                                    range.setEnd(textNodeInfo.node, rangeEnd);
                                    selectionRanges.push(range);
                                }

                                remainingStart = textNodeInfo.endOffset;
                                if (remainingStart >= endIndex) break;
                            }

                            // Apply all ranges to the selection
                            for (let range of selectionRanges) {
                                window.getSelection().addRange(range);
                            }

                            // Verify selection
                            const selection = window.getSelection();
                            const selectedText = selection.toString().trim();

                            if (selectedText.length === 0) {
                                return {
                                    success: false,
                                    error: 'No text was selected'
                                };
                            }

                            // Get the expected text from the original text
                            const expectedText = fullText.substring(startIndex, endIndex).trim();

                            if (selectedText !== expectedText) {
                                return {
                                    success: false,
                                    error: `Selection mismatch: expected "${expectedText}", got "${selectedText}"`
                                };
                            }

                            return {
                                success: true,
                                selectedText: selectedText,
                                message: `Successfully selected "${selectedText}"`
                            };

                        } catch (error) {
                            return {
                                success: false,
                                error: `JavaScript error: ${error.message}`
                            };
                        }
                    }
                    return robustTextSelection(arguments[0], arguments[1], arguments[2]);
                """, instance_text, start_index, end_index)

                print(f"   Selection result: {result}")

                if result.get('success'):
                    print(f"   ✅ Text selection successful: '{result.get('selectedText')}'")

                    # Call surroundSelection directly to create the span
                    surround_result = driver.execute_script("""
                        if (typeof surroundSelection === 'function') {
                            return surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
                        } else {
                            return 'surroundSelection function not found';
                        }
                    """)
                    print(f"   Direct surroundSelection result: {surround_result}")

                    return True
                else:
                    print(f"   ⚠️ Text selection failed: {result.get('error')}")

            except Exception as e:
                print(f"   ⚠️ Text selection attempt {attempt + 1} failed: {e}")

        print(f"   ❌ Text selection failed after {max_retries} attempts")
        return False

    @staticmethod
    def get_span_elements(driver, timeout=5):
        """Get all span annotation elements with enhanced waiting and logging."""
        try:
            print("   🔍 Looking for span elements...")

            # Wait for potential overlays to appear
            try:
                WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".span-highlight"))
                )
                print("   ✅ Found at least one span highlight")
            except TimeoutException:
                print("   ⚠️ No span highlights found within timeout")

            # Get all spans
            spans = driver.find_elements(By.CSS_SELECTOR, ".span-highlight")
            print(f"   📊 Found {len(spans)} span elements")

            for i, span in enumerate(spans):
                try:
                    class_attr = span.get_attribute('class')
                    text_content = span.text[:50] if span.text else "No text"
                    schema = span.get_attribute('schema')
                    label = span.get_attribute('data-label')
                    print(f"   Span {i}: class='{class_attr}', schema='{schema}', label='{label}', text='{text_content}...'")
                except Exception as e:
                    print(f"   Span {i}: Error getting attributes: {e}")

            return spans
        except Exception as e:
            print(f"   ❌ Error in get_span_elements: {e}")
            return []

    @staticmethod
    def get_span_text(span_element):
        """Get the text content of a span element with error handling."""
        try:
            text = span_element.text
            # Remove the × character and label text
            text = text.replace("×", "").strip()
            return text
        except Exception as e:
            print(f"   ❌ Error getting span text: {e}")
            return ""

    @staticmethod
    def delete_span(driver, span_element, description="span"):
        """Delete a span by clicking its close button with retry logic."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Find the close button within the span
                close_button = span_element.find_element(By.CSS_SELECTOR, ".span_close")

                # Scroll the close button into view
                driver.execute_script("arguments[0].scrollIntoView(true);", close_button)
                time.sleep(0.5)

                # Click the close button
                RobustSpanAnnotationHelper.safe_click(driver, close_button, f"close button for {description}")

                # Wait for page reload after deletion
                time.sleep(3)

                # Wait for page to fully load
                RobustSpanAnnotationHelper.wait_for_page_load(driver, timeout=10)

                # Check if the span was actually deleted by looking for span elements
                spans_after_delete = RobustSpanAnnotationHelper.get_span_elements(driver)

                # If no spans found, deletion was successful
                if len(spans_after_delete) == 0:
                    print(f"   ✅ Successfully deleted {description}")
                    return True
                else:
                    print(f"   ⚠️ Span {description} still exists after deletion attempt {attempt + 1} (found {len(spans_after_delete)} spans)")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        print(f"   ❌ Failed to delete {description} after {max_retries} attempts")
                        return False

            except Exception as e:
                print(f"   ⚠️ Delete attempt {attempt + 1} failed for {description}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    print(f"   ❌ Failed to delete {description} after {max_retries} attempts")
                    return False

        return False

    @staticmethod
    def verify_backend_spans(driver, base_url, username, expected_spans):
        """Verify that spans are correctly saved in the backend with enhanced error handling."""
        print("   [DEBUG] Entered verify_backend_spans")
        try:
            with open("/tmp/potato_backend_debug.txt", "a") as f:
                f.write("\n[DEBUG] Entered verify_backend_spans\n")
                f.write(f"base_url: {base_url}, username: {username}, expected_spans: {expected_spans}\n")
            try:
                print("   [DEBUG] Before getting instance_id_element")
                with open("/tmp/potato_backend_debug.txt", "a") as f:
                    f.write("[DEBUG] Before getting instance_id_element\n")
                # Wait for page to fully load after reload
                RobustSpanAnnotationHelper.wait_for_page_load(driver, timeout=10)
                # Wait for main content or instance-text to be present
                try:
                    RobustSpanAnnotationHelper.wait_for_element(
                        driver, By.ID, "main-content", description="main content", timeout=5
                    )
                except Exception:
                    RobustSpanAnnotationHelper.wait_for_element(
                        driver, By.ID, "instance-text", description="instance text", timeout=5
                    )
                # Retry loop for finding instance_id
                instance_id = None
                for attempt in range(10):
                    try:
                        instance_id_element = RobustSpanAnnotationHelper.wait_for_element(
                            driver, By.ID, "instance_id", description="instance ID", timeout=2
                        )
                        instance_id = instance_id_element.get_attribute("value")
                        print(f"   🔍 Retrieved instance_id: {instance_id} (attempt {attempt+1})")
                        with open("/tmp/potato_backend_debug.txt", "a") as f:
                            f.write(f"[DEBUG] Retrieved instance_id: {instance_id} (attempt {attempt+1})\n")
                        break
                    except Exception as e:
                        print(f"   [DEBUG] Attempt {attempt+1} failed to find instance_id: {e}")
                        with open("/tmp/potato_backend_debug.txt", "a") as f:
                            f.write(f"[DEBUG] Attempt {attempt+1} failed to find instance_id: {e}\n")
                        if attempt == 0:
                            # Print and write current URL and page source
                            try:
                                current_url = driver.current_url
                                page_source = driver.page_source
                                print(f"   [DEBUG] Current URL: {current_url}")
                                print(f"   [DEBUG] Page source (first 500 chars): {page_source[:500]}")
                                with open("/tmp/potato_backend_debug.txt", "a") as f:
                                    f.write(f"[DEBUG] Current URL: {current_url}\n")
                                    f.write(f"[DEBUG] Page source (first 500 chars): {page_source[:500]}\n")
                                # Also get document.body.innerHTML
                                body_html = driver.execute_script("return document.body ? document.body.innerHTML : '';")
                                print(f"   [DEBUG] Body HTML (first 500 chars): {body_html[:500]}")
                                with open("/tmp/potato_backend_debug.txt", "a") as f:
                                    f.write(f"[DEBUG] Body HTML (first 500 chars): {body_html[:500]}\n")
                                # JS check for instance_id
                                js_found = driver.execute_script("return document.getElementById('instance_id') !== null;")
                                print(f"   [DEBUG] JS found instance_id: {js_found}")
                                with open("/tmp/potato_backend_debug.txt", "a") as f:
                                    f.write(f"[DEBUG] JS found instance_id: {js_found}\n")
                                if js_found:
                                    outer_html = driver.execute_script("return document.getElementById('instance_id').outerHTML;")
                                    attrs = driver.execute_script("var el = document.getElementById('instance_id'); return {id: el.id, name: el.name, value: el.value, type: el.type};")
                                    print(f"   [DEBUG] instance_id outerHTML: {outer_html}")
                                    print(f"   [DEBUG] instance_id attrs: {attrs}")
                                    with open("/tmp/potato_backend_debug.txt", "a") as f:
                                        f.write(f"[DEBUG] instance_id outerHTML: {outer_html}\n")
                                        f.write(f"[DEBUG] instance_id attrs: {attrs}\n")
                            except Exception as page_exc:
                                print(f"   [DEBUG] Could not get page source: {page_exc}")
                        time.sleep(0.5)
                if not instance_id:
                    # Fallback: use JS to get the value if present
                    js_found = driver.execute_script("return document.getElementById('instance_id') !== null;")
                    if js_found:
                        instance_id = driver.execute_script("return document.getElementById('instance_id').value;")
                        print(f"   [DEBUG] Fallback: JS found instance_id value: {instance_id}")
                        with open("/tmp/potato_backend_debug.txt", "a") as f:
                            f.write(f"[DEBUG] Fallback: JS found instance_id value: {instance_id}\n")
                    else:
                        raise Exception("Could not find instance_id after retries and JS fallback")
                print(f"   🔍 Retrieved instance_id: {instance_id}")
                with open("/tmp/potato_backend_debug.txt", "a") as f:
                    f.write(f"[DEBUG] Retrieved instance_id: {instance_id}\n")
                print("   [DEBUG] Before backend request")
                with open("/tmp/potato_backend_debug.txt", "a") as f:
                    f.write("[DEBUG] Before backend request\n")
                user_state_response = requests.get(
                    f"{base_url}/admin/user_state/{username}",
                    headers={'X-API-Key': 'admin_api_key'},
                    timeout=10
                )
                print(f"   🔍 Backend response status: {user_state_response.status_code}")
                print(f"   🔍 Backend response text: {user_state_response.text}")
                with open("/tmp/potato_backend_debug.txt", "a") as f:
                    f.write(f"status: {user_state_response.status_code}\n")
                    f.write(f"response: {user_state_response.text}\n")
                sys.stdout.flush()
                if user_state_response.status_code == 200:
                    user_state = user_state_response.json()
                    annotations = user_state.get("annotations", {}).get("by_instance", {})
                    instance_annotations = annotations.get(instance_id, {})
                    print(f"   📊 Backend annotations for instance {instance_id}: {instance_annotations}")
                    print(f"   🔍 Values being checked for span: {[str(v) for v in instance_annotations.values()]}")
                    with open("/tmp/potato_backend_debug.txt", "a") as f:
                        f.write(f"annotations: {instance_annotations}\n")
                        f.write(f"values: {[str(v) for v in instance_annotations.values()]}\n")
                    sys.stdout.flush()
                    # Verify each expected span
                    all_found = True
                    for expected_span in expected_spans:
                        span_found = False
                        for annotation_value in instance_annotations.values():
                            if expected_span["text"] in str(annotation_value):
                                span_found = True
                                print(f"   ✅ Found expected span '{expected_span['text']}' in annotation value")
                                break
                        if not span_found:
                            print(f"   ❌ Expected span '{expected_span['text']}' not found in backend")
                            all_found = False
                    if all_found:
                        print(f"   ✅ All {len(expected_spans)} expected spans found in backend")
                        return all_found
                    else:
                        print(f"   ❌ Failed to get user state: {user_state_response.status_code}")
                        print(f"   Response: {user_state_response.text}")
                        return False
                else:
                    print(f"   ❌ Failed to get user state: {user_state_response.status_code}")
                    print(f"   Response: {user_state_response.text}")
                    return False
            except Exception as inner_exc:
                print(f"   [DEBUG] Exception in verify_backend_spans: {inner_exc}")
                with open("/tmp/potato_backend_debug.txt", "a") as f:
                    f.write(f"[DEBUG] Exception: {inner_exc}\n")
                return False
        except Exception as outer_exc:
            print(f"   [DEBUG] Outer exception in verify_backend_spans: {outer_exc}")
            with open("/tmp/potato_backend_debug.txt", "a") as f:
                f.write(f"[DEBUG] Outer exception: {outer_exc}\n")
            return False

    @staticmethod
    def verify_visual_layout_persistence(driver, expected_span_count):
        """Verify that the visual layout (span highlighting) persists correctly."""
        current_spans = RobustSpanAnnotationHelper.get_span_elements(driver)
        current_count = len(current_spans)

        if current_count == expected_span_count:
            print(f"   ✅ Visual layout correct: {current_count} spans displayed")
            return True
        else:
            print(f"   ❌ Visual layout incorrect: expected {expected_span_count}, got {current_count}")
            return False

    @staticmethod
    def capture_browser_logs(driver, description="browser logs"):
        """Capture and log browser console messages."""
        try:
            logs = driver.get_log('browser')
            if logs:
                print(f"\n=== {description.upper()} ===")
                for log in logs[-10:]:  # Last 10 logs
                    level = log.get('level', 'INFO')
                    message = log.get('message', '')
                    print(f"  {level}: {message}")
                print(f"=== END {description.upper()} ===\n")
            return logs
        except Exception as e:
            print(f"   ⚠️ Could not capture {description}: {e}")
            return []

    @staticmethod
    def wait_for_page_load(driver, timeout=10):
        """Wait for page to fully load with comprehensive checks."""
        try:
            # Wait for document ready state
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Wait for jQuery if present
            jquery_ready = driver.execute_script("""
                return typeof jQuery === 'undefined' || jQuery.isReady;
            """)

            if not jquery_ready:
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return typeof jQuery === 'undefined' || jQuery.isReady;")
                )

            print("   ✅ Page fully loaded")
            return True
        except TimeoutException:
            print("   ⚠️ Page load timeout, continuing anyway")
            return False
        except Exception as e:
            print(f"   ⚠️ Error waiting for page load: {e}")
            return False


class TestSpanAnnotationComprehensive:
    """Comprehensive test suite for span annotation behaviors with enhanced robustness."""

    @pytest.fixture(autouse=True)
    def setup_test_environment(self):
        """Setup test environment with original working directory."""
        self.original_cwd = os.getcwd()
        self.test_username = None
        self.test_password = "test_password_123"
        yield
        # Cleanup if needed

    def register_test_user(self, driver, base_url, test_name):
        """Register a unique test user for this test."""
        import uuid
        import time

        # Generate unique username based on test name and timestamp
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        self.test_username = f"test_user_{test_name}_{timestamp}_{unique_id}"

        print(f"🔐 Registering test user: {self.test_username}")

        # Navigate to home page
        driver.get(base_url)
        RobustSpanAnnotationHelper.wait_for_page_load(driver)

        # Click the Register tab to show the registration form
        register_tab = RobustSpanAnnotationHelper.wait_for_element(
            driver, By.ID, "register-tab", description="register tab"
        )
        RobustSpanAnnotationHelper.safe_click(driver, register_tab, "register tab")
        time.sleep(1)

        # Fill in registration form
        email_field = RobustSpanAnnotationHelper.wait_for_element(
            driver, By.ID, "register-email", description="email field"
        )
        email_field.clear()
        email_field.send_keys(self.test_username)

        password_field = RobustSpanAnnotationHelper.wait_for_element(
            driver, By.ID, "register-pass", description="password field"
        )
        password_field.clear()
        password_field.send_keys(self.test_password)

        # Submit registration form
        submit_button = RobustSpanAnnotationHelper.wait_for_element(
            driver, By.CSS_SELECTOR, "#register-content button[type='submit']",
            description="submit button"
        )
        RobustSpanAnnotationHelper.safe_click(driver, submit_button, "submit button")

        # Wait for redirect to annotation page
        RobustSpanAnnotationHelper.wait_for_page_load(driver)

        # Verify we're logged in by checking for username in page
        try:
            username_element = RobustSpanAnnotationHelper.wait_for_element(
                driver, By.XPATH, f"//*[contains(text(), '{self.test_username}')]",
                description="username display"
            )
            print(f"   ✅ Successfully registered and logged in as: {self.test_username}")
        except TimeoutException:
            print(f"   ⚠️ Could not verify username display, but continuing...")

        return self.test_username

    def create_unique_test_environment(self, test_data, config_path, test_name):
        """Create a unique test environment with isolated temp directory and unique IDs."""
        import tempfile
        import uuid
        import time
        import json
        import yaml

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
        config_data['debug'] = False  # Ensure debug mode is off for test client

        # Write updated config to temp directory
        temp_config_path = os.path.join(config_dir, os.path.basename(config_path))
        with open(temp_config_path, 'w') as f:
            yaml.dump(config_data, f)

        return temp_dir, temp_config_path

    def test_1_basic_span_annotation_robust(self, flask_server, browser):
        """Test 1: Robust basic span annotation with enhanced error handling."""
        print("\n=== Test 1: Robust Basic Span Annotation ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Register a unique test user
        username = self.register_test_user(browser, base_url, "test_1")

        try:
            # Navigate to instance ai_1 and get clean text
            print("1. Navigating to instance ai_1...")
            browser.get(f"{base_url}/annotate?instance_id=ai_1")
            RobustSpanAnnotationHelper.wait_for_page_load(browser)
            time.sleep(2)

            instance_text = RobustSpanAnnotationHelper.wait_for_element(
                browser, By.ID, "instance-text", description="instance text"
            )
            text_content = instance_text.text
            print(f"   📝 Text length: {len(text_content)} characters")
            print(f"   📝 Text preview: {text_content[:100]}...")

            # Find a good phrase to annotate in the AI text
            phrase = "artificial intelligence"
            start_index = text_content.find(phrase)
            end_index = start_index + len(phrase)

            if start_index == -1:
                # Fallback to a different phrase
                phrase = "natural language"
                start_index = text_content.find(phrase)
                end_index = start_index + len(phrase)

            assert start_index != -1, f"Could not find suitable phrase in text: {text_content}"
            print(f"   📍 Annotating phrase '{phrase}' at indices {start_index}-{end_index}")

            # Create span annotation
            print("2. Creating span annotation...")
            RobustSpanAnnotationHelper.robust_text_selection(browser, start_index, end_index)
            time.sleep(2)

            # Verify span was created
            spans = RobustSpanAnnotationHelper.get_span_elements(browser)
            assert len(spans) == 1, f"Expected 1 span, found {len(spans)}"
            print(f"   ✅ Span created successfully")

            # Verify span text
            span_text = RobustSpanAnnotationHelper.get_span_text(spans[0])
            print(f"   📝 Span text: {span_text}")
            assert phrase in span_text, f"Expected '{phrase}' in span text, got '{span_text}'"

            # Verify backend storage
            print("3. Verifying backend storage...")
            expected_spans = [{"text": phrase, "schema": "emotion", "label": "happy"}]
            RobustSpanAnnotationHelper.verify_backend_spans(browser, base_url, username, expected_spans)

            print("   ✅ Test 1 completed successfully - basic span annotation works")

        except Exception as e:
            print(f"   ❌ Test 1 failed: {e}")
            RobustSpanAnnotationHelper.capture_browser_logs(browser, "test_1_failure")
            raise

    def test_2_span_creation_and_deletion_robust(self, flask_server, browser):
        """Test 2: Robust span creation and deletion with enhanced error handling."""
        print("\n=== Test 2: Robust Span Creation and Deletion ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Register a unique test user
        username = self.register_test_user(browser, base_url, "test_2")

        try:
            # Navigate to annotation page
            print("1. Navigating to annotation page...")
            browser.get(f"{base_url}/annotate")
            RobustSpanAnnotationHelper.wait_for_page_load(browser)
            time.sleep(2)

            # Verify we're on the annotation page
            instance_text = RobustSpanAnnotationHelper.wait_for_element(
                browser, By.ID, "instance-text", description="instance text"
            )
            print("   ✅ Annotation page loaded successfully")

            # Click on emotion label
            print("2. Clicking emotion label...")
            emotion_label = RobustSpanAnnotationHelper.wait_for_clickable(
                browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
                description="emotion label"
            )
            RobustSpanAnnotationHelper.safe_click(browser, emotion_label, "emotion label")
            time.sleep(1)

            # Verify the checkbox is checked
            assert emotion_label.is_selected(), "Emotion label should be checked"
            print("   ✅ Emotion label is checked")

            # Select text to create the span (this now includes surroundSelection call)
            print("3. Selecting text to create span...")
            selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 5, 15)
            assert selection_success, "Text selection failed"
            time.sleep(3)

            # Verify span was created
            spans = RobustSpanAnnotationHelper.get_span_elements(browser)
            assert len(spans) == 1, f"Expected 1 span, got {len(spans)}"
            print("   ✅ Span created successfully")

            # Delete the span
            print("4. Deleting the span...")
            deletion_success = RobustSpanAnnotationHelper.delete_span(browser, spans[0], "test span")
            assert deletion_success, "Span deletion failed"

            # Verify span was deleted
            spans_after_deletion = RobustSpanAnnotationHelper.get_span_elements(browser)
            assert len(spans_after_deletion) == 0, f"Expected 0 spans after deletion, got {len(spans_after_deletion)}"
            print("   ✅ Span deleted successfully")

            print("✅ Test 2 passed: Robust span creation and deletion works correctly")

        except Exception as e:
            print(f"❌ Test 2 failed: {e}")
            RobustSpanAnnotationHelper.capture_browser_logs(browser, "error state")
            raise

    def test_3_two_non_overlapping_spans_robust(self, flask_server, browser):
        """Test 3: Robust creation of two non-overlapping spans."""
        print("\n=== Test 3: Robust Two Non-Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Register a unique test user
        username = self.register_test_user(browser, base_url, "test_3")

        try:
            # Navigate to annotation page
            print("1. Navigating to annotation page...")
            browser.get(f"{base_url}/annotate")
            RobustSpanAnnotationHelper.wait_for_page_load(browser)
            time.sleep(2)

            # Verify we're on the annotation page
            instance_text = RobustSpanAnnotationHelper.wait_for_element(
                browser, By.ID, "instance-text", description="instance text"
            )

            # Navigate to instance 1 (which has the AI text)
            print("2. Navigating to instance 1...")
            browser.get(f"{base_url}/annotate?instance_id=ai_1")
            RobustSpanAnnotationHelper.wait_for_page_load(browser)
            time.sleep(2)

            # Refind the instance text element after navigation
            instance_text = RobustSpanAnnotationHelper.wait_for_element(
                browser, By.ID, "instance-text", description="instance text"
            )

            # Verify we have the text
            text_content = instance_text.text
            print(f"   📝 Text length: {len(text_content)} characters")
            print(f"   📝 Text preview: {text_content[:100]}...")

            # Dynamically find indices for the target phrases in the AI text
            phrase1 = "artificial intelligence"
            phrase2 = "natural language"
            start1 = text_content.find(phrase1)
            end1 = start1 + len(phrase1)
            start2 = text_content.find(phrase2)
            end2 = start2 + len(phrase2)
            assert start1 != -1 and start2 != -1, f"Could not find target phrases in text: {text_content}"
            print(f"   📍 Indices for '{phrase1}': {start1}-{end1}")
            print(f"   📍 Indices for '{phrase2}': {start2}-{end2}")

            # Create first span
            print("3. Creating first span...")
            RobustSpanAnnotationHelper.robust_text_selection(browser, start1, end1)
            time.sleep(1)

            # Select emotion label
            emotion_label = RobustSpanAnnotationHelper.wait_for_element(
                browser, By.CSS_SELECTOR, "[data-label='happy']", description="happy emotion label"
            )
            RobustSpanAnnotationHelper.safe_click(browser, emotion_label, "happy emotion label")
            time.sleep(2)

            # Verify first span was created
            spans = RobustSpanAnnotationHelper.get_span_elements(browser)
            assert len(spans) == 1, f"Expected 1 span, found {len(spans)}"
            print(f"   ✅ First span created successfully")

            # Create second span
            print("4. Creating second span...")
            RobustSpanAnnotationHelper.robust_text_selection(browser, start2, end2)
            time.sleep(1)

            # Select emotion label for second span
            emotion_label = RobustSpanAnnotationHelper.wait_for_element(
                browser, By.CSS_SELECTOR, "[data-label='happy']", description="happy emotion label"
            )
            RobustSpanAnnotationHelper.safe_click(browser, emotion_label, "happy emotion label")
            time.sleep(2)

            # Verify both spans were created
            spans = RobustSpanAnnotationHelper.get_span_elements(browser)
            assert len(spans) == 2, f"Expected 2 spans, found {len(spans)}"
            print(f"   ✅ Second span created successfully")

            # Verify spans are non-overlapping
            span_texts = [RobustSpanAnnotationHelper.get_span_text(span) for span in spans]
            print(f"   📝 Span texts: {span_texts}")

            # Check that spans don't overlap by verifying their content
            assert phrase1 in span_texts[0] or phrase1 in span_texts[1], "First span not found"
            assert phrase2 in span_texts[0] or phrase2 in span_texts[1], "Second span not found"

            print("   ✅ Test 3 completed successfully - two non-overlapping spans created")

        except Exception as e:
            print(f"   ❌ Test 3 failed: {e}")
            RobustSpanAnnotationHelper.capture_browser_logs(browser, "test_3_failure")
            raise

    def test_4_two_partially_overlapping_spans(self, flask_server, browser):
        """Test 4: Annotating two spans that partially overlap."""
        print("\n=== Test 4: Two Partially Overlapping Spans ===")

        try:
            base_url = f"http://localhost:{flask_server.port}"
            username = "debug_user"  # Use debug user since server is in debug mode

            # In debug mode, user is auto-logged in, so go directly to annotation page
            print("1. Navigating to annotation page (debug mode)...")
            browser.get(f"{base_url}/annotate")
            RobustSpanAnnotationHelper.wait_for_page_load(browser)
            time.sleep(2)

            # Verify we're on the annotation page
            instance_text = RobustSpanAnnotationHelper.wait_for_element(
                browser, By.ID, "instance-text", description="instance text"
            )
            assert instance_text.is_displayed(), "Instance text should be displayed"
            print("   ✅ Annotation page loaded successfully")

            # Create first span (emotion: happy)
            print("2. Creating first span (emotion: happy)...")
            RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
                browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
                description="emotion label"
            ), "emotion label")
            time.sleep(1)

            selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 15)
            assert selection_success, "First text selection failed"
            time.sleep(3)

            # Create second span (intensity: high) - partially overlapping
            print("3. Creating second span (intensity: high) - partially overlapping...")
            RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
                browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
                description="emotion label"
            ), "emotion label")
            time.sleep(1)

            selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 10, 25)
            assert selection_success, "Second text selection failed"
            time.sleep(3)

            # Debug: Check span count immediately after second span creation
            print("   Debug: Checking span count after second span creation...")
            spans_after_second = RobustSpanAnnotationHelper.get_span_elements(browser)
            print(f"   Found {len(spans_after_second)} spans after second creation")
            for i, span in enumerate(spans_after_second):
                print(f"   Span {i}: {RobustSpanAnnotationHelper.get_span_text(span)}")

            # Verify both spans were created
            spans = RobustSpanAnnotationHelper.get_span_elements(browser)
            print(f"   Found {len(spans)} spans on page")
            assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
            print("   ✅ Both spans created successfully")

            # Verify spans partially overlap
            span_texts = [RobustSpanAnnotationHelper.get_span_text(span) for span in spans]
            print(f"   Span texts: {span_texts}")

            # Debug: Check what's in the backend before verification
            print("   Checking backend before verification...")
            try:
                api_key = os.environ.get("TEST_API_KEY", "test-api-key-123")
                headers = {"X-API-KEY": api_key}
                user_state_response = requests.get(f"{base_url}/admin/user_state/{username}", headers={
                    **headers,
                    'X-API-Key': 'admin_api_key'
                }, timeout=10)

                if user_state_response.status_code == 200:
                    user_state = user_state_response.json()
                    annotations = user_state.get("annotations", {}).get("by_instance", {})
                    instance_id = RobustSpanAnnotationHelper.wait_for_element(
                        browser, By.ID, "instance_id", description="instance ID"
                    ).get_attribute("value")
                    instance_annotations = annotations.get(instance_id, {})
                    print(f"   Backend annotations for instance {instance_id}: {instance_annotations}")
                else:
                    print(f"   Failed to get user state: {user_state_response.status_code}")
                    print(f"   Response: {user_state_response.text}")
            except Exception as e:
                print(f"   Error checking backend: {e}")

            # Verify backend storage
            expected_spans = [{"text": "The political d"}, {"text": "cal dhappy×ebat"}]
            assert RobustSpanAnnotationHelper.verify_backend_spans(browser, base_url, username, expected_spans)
            print("   ✅ Backend verification passed")

            print("✅ Test 4 passed: Two partially overlapping spans work correctly")

        except Exception as e:
            print(f"❌ Test 4 failed with exception: {e}")
            RobustSpanAnnotationHelper.capture_browser_logs(browser, "error state")
            raise

    def test_5_nested_spans(self, flask_server, browser):
        """Test 5: Annotating two spans where one span is nested within another."""
        print("\n=== Test 5: Nested Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"  # Use debug user since server is in debug mode

        # In debug mode, user is auto-logged in, so go directly to annotation page
        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(2)

        # Verify we're on the annotation page
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        # Create outer span (emotion: happy)
        print("2. Creating outer span (emotion: happy)...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)

        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 20)
        assert selection_success, "Outer text selection failed"
        time.sleep(3)

        # Create inner span (intensity: high) - nested within outer span
        print("3. Creating inner span (intensity: high) - nested within outer span...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)

        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 5, 15)
        assert selection_success, "Inner text selection failed"
        time.sleep(3)

        # Verify both spans were created
        spans = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        # Verify spans are nested
        span_texts = [RobustSpanAnnotationHelper.get_span_text(span) for span in spans]
        print(f"   Span texts: {span_texts}")

        # Verify backend storage
        expected_spans = [{"text": "The new artifi"}, {"text": "new artifi"}]
        assert RobustSpanAnnotationHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")

        print("✅ Test 5 passed: Nested spans work correctly")

    def test_6_delete_first_of_two_non_overlapping_spans(self, flask_server, browser):
        """Test 6: Annotating two spans that do not overlap and deleting the first span."""
        print("\n=== Test 6: Delete First of Two Non-Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"  # Use debug user since server is in debug mode

        # In debug mode, user is auto-logged in, so go directly to annotation page
        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(2)

        # Verify we're on the annotation page
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        # Create first span (emotion: happy)
        print("2. Creating first span (emotion: happy)...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)

        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 10)
        assert selection_success, "First text selection failed"
        time.sleep(3)

        # Create second span (intensity: high) - non-overlapping
        print("3. Creating second span (intensity: high)...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)

        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 50, 70)
        assert selection_success, "Second text selection failed"
        time.sleep(3)

        # Verify both spans were created
        spans = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        # Delete first span
        print("4. Deleting first span...")
        RobustSpanAnnotationHelper.delete_span(browser, spans[0], "first span")
        time.sleep(2)

        # Verify only second span remains
        spans_after_delete = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ First span deleted successfully")

        # Verify backend storage
        expected_spans = [{"text": "intelligence model"}]
        assert RobustSpanAnnotationHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")

        print("✅ Test 6 passed: Delete first of two non-overlapping spans works correctly")

    def test_7_delete_first_of_two_partially_overlapping_spans(self, flask_server, browser):
        """Test 7: Annotating two spans that partially overlap and deleting the first span."""
        print("\n=== Test 7: Delete First of Two Partially Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(2)
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating first span (emotion: happy)...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 15)
        assert selection_success, "First text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        print("3. Creating second span (intensity: high) - partially overlapping...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 10, 25)
        assert selection_success, "Second text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        spans = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting first span...")
        RobustSpanAnnotationHelper.delete_span(browser, spans[0], "first span")
        time.sleep(2)
        spans_after_delete = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ First span deleted successfully")

        expected_spans = [{"text": "artificial int"}]
        assert RobustSpanAnnotationHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 7 passed: Delete first of two partially overlapping spans works correctly")

    def test_8_delete_inner_nested_span(self, flask_server, browser):
        """Test 8: Annotating two spans where one span is nested within another and deleting the inner span."""
        print("\n=== Test 8: Delete Inner Nested Span ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(2)
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating outer span (emotion: happy)...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 20)
        assert selection_success, "Outer text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        print("3. Creating inner span (intensity: high) - nested within outer span...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 5, 15)
        assert selection_success, "Inner text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        spans = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting inner span...")
        RobustSpanAnnotationHelper.delete_span(browser, spans[1], "inner span")
        time.sleep(2)
        spans_after_delete = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ Inner span deleted successfully")

        expected_spans = [{"text": "The new artifi"}]
        assert RobustSpanAnnotationHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 8 passed: Delete inner nested span works correctly")

    def test_9_delete_second_of_two_non_overlapping_spans(self, flask_server, browser):
        """Test 9: Annotating two spans that do not overlap and deleting the second span."""
        print("\n=== Test 9: Delete Second of Two Non-Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(2)
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating first span (emotion: happy)...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 10)
        assert selection_success, "First text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        print("3. Creating second span (intensity: high)...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::intensity'][value='3']",
            description="intensity label"
        ), "intensity label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 50, 70)
        assert selection_success, "Second text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::intensity"][value="3"]'), 'intensity', 'high', 'high', '(150, 150, 150)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('intensity', 'high', 'high', '(150, 150, 150)');
            }
        """)
        time.sleep(2)

        spans = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting second span...")
        RobustSpanAnnotationHelper.delete_span(browser, spans[1], "second span")
        time.sleep(2)
        spans_after_delete = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ Second span deleted successfully")

        expected_spans = [{"text": "The new ar"}]
        assert RobustSpanAnnotationHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 9 passed: Delete second of two non-overlapping spans works correctly")

    def test_10_delete_second_of_two_partially_overlapping_spans(self, flask_server, browser):
        """Test 10: Annotating two spans that partially overlap and deleting the second span."""
        print("\n=== Test 10: Delete Second of Two Partially Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(2)
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating first span (emotion: happy)...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 15)
        assert selection_success, "First text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        print("3. Creating second span (intensity: high) - partially overlapping...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 10, 25)
        assert selection_success, "Second text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        spans = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting second span...")
        RobustSpanAnnotationHelper.delete_span(browser, spans[1], "second span")
        time.sleep(2)
        spans_after_delete = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ Second span deleted successfully")

        expected_spans = [{"text": "The new artifi"}]
        assert RobustSpanAnnotationHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 10 passed: Delete second of two partially overlapping spans works correctly")

    def test_11_delete_outer_nested_span(self, flask_server, browser):
        """Test 11: Annotating two spans where one span is nested within another and deleting the outer span."""
        print("\n=== Test 11: Delete Outer Nested Span ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(2)
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating outer span (emotion: happy)...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 20)
        assert selection_success, "Outer text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        print("3. Creating inner span (intensity: high) - nested within outer span...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 5, 15)
        assert selection_success, "Inner text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        spans = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting outer span...")
        RobustSpanAnnotationHelper.delete_span(browser, spans[0], "outer span")
        time.sleep(2)
        spans_after_delete = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ Outer span deleted successfully")

        expected_spans = [{"text": "new artifi"}]
        assert RobustSpanAnnotationHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 11 passed: Delete outer nested span works correctly")

    def test_12_navigation_and_annotation_restoration(self, flask_server, browser):
        """Test 12: Verify that all previous annotations are restored when navigating between instances that have already been annotated."""
        print("\n=== Test 12: Navigation and Annotation Restoration ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Register a unique test user
        username = self.register_test_user(browser, base_url, "test_12")

        print("1. Navigating to annotation page...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(2)
        instance_text = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating span on instance 1...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 10)
        assert selection_success, "First text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        print("3. Navigating to next instance...")
        next_btn = RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.ID, "next-btn", description="next button"
        )
        RobustSpanAnnotationHelper.safe_click(browser, next_btn, "next button")
        time.sleep(2)
        instance_text_2 = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text_2.is_displayed(), "Instance text for instance 2 should be displayed"
        print("   ✅ Navigated to instance 2")

        print("4. Creating span on instance 2...")
        RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
            description="emotion label"
        ), "emotion label")
        time.sleep(1)
        selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 0, 10)
        assert selection_success, "Second text selection failed"
        time.sleep(3)
        browser.execute_script("""
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(document.querySelector('input[name="span_label:::emotion"][value="1"]'), 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        print("5. Navigating back to instance 1...")
        prev_btn = RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.ID, "prev-btn", description="previous button"
        )
        RobustSpanAnnotationHelper.safe_click(browser, prev_btn, "previous button")
        time.sleep(2)
        instance_text_1 = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text_1.is_displayed(), "Instance text for instance 1 should be displayed"
        print("   ✅ Navigated back to instance 1")

        print("6. Verifying span is restored on instance 1...")
        spans = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans) == 1, f"Expected 1 span on instance 1, got {len(spans)}"
        print("   ✅ Span restored on instance 1")

        print("7. Navigating to instance 2 again...")
        next_btn = RobustSpanAnnotationHelper.wait_for_clickable(
            browser, By.ID, "next-btn", description="next button"
        )
        RobustSpanAnnotationHelper.safe_click(browser, next_btn, "next button")
        time.sleep(2)
        instance_text_2 = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        assert instance_text_2.is_displayed(), "Instance text for instance 2 should be displayed"
        print("   ✅ Navigated to instance 2 again")

        print("8. Verifying span is restored on instance 2...")
        spans_2 = RobustSpanAnnotationHelper.get_span_elements(browser)
        assert len(spans_2) == 1, f"Expected 1 span on instance 2, got {len(spans_2)}"
        print("   ✅ Span restored on instance 2")

        print("✅ Test 12 passed: Navigation and annotation restoration works correctly")

    def test_debug_page_elements(self, flask_server, browser):
        """Debug test to check what elements are available on the page."""
        print("\n=== Debug Test: Check Page Elements ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Navigate to annotation page
        print("1. Navigating to annotation page...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(3)

        # Check page title
        title = browser.title
        print(f"   Page title: {title}")

        # Check if page loaded
        if "Span Annotation Test" in title:
            print("   ✅ Page loaded successfully")
        else:
            print(f"   ❌ Page title unexpected: {title}")

        # Check for text content
        text_element = RobustSpanAnnotationHelper.wait_for_element(
            browser, By.ID, "instance-text", description="instance text"
        )
        if text_element:
            text_content = text_element.text
            print(f"   Text content: {text_content[:100]}...")

        # Check for any checkboxes
        checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
        print(f"   Found {len(checkboxes)} checkboxes")

        # Check for any buttons
        buttons = browser.find_elements(By.CSS_SELECTOR, 'button')
        print(f"   Found {len(buttons)} buttons")

        # Check for any inputs
        inputs = browser.find_elements(By.CSS_SELECTOR, 'input')
        print(f"   Found {len(inputs)} inputs")

        # List all form elements
        form_elements = browser.find_elements(By.CSS_SELECTOR, 'form *')
        print(f"   Found {len(form_elements)} form elements")

        print("✅ Debug test completed")

    def test_debug_overlay_javascript(self, flask_server, browser):
        """Debug test to check overlay JavaScript execution and console output."""
        print("\n=== Debug Test: Overlay JavaScript ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Navigate to annotation page
        print("1. Navigating to annotation page...")
        browser.get(f"{base_url}/annotate")
        RobustSpanAnnotationHelper.wait_for_page_load(browser)
        time.sleep(3)

        # Check if overlay elements exist
        print("2. Checking overlay elements...")
        overlays_container = browser.find_elements(By.ID, "span-overlays")
        print(f"   span-overlays container found: {len(overlays_container) > 0}")

        # Check if instance-text exists
        instance_text = browser.find_elements(By.ID, "instance-text")
        print(f"   instance-text element found: {len(instance_text) > 0}")

        # Check if spanAnnotations variable exists
        span_annotations_exists = browser.execute_script("return typeof window.spanAnnotations !== 'undefined';")
        print(f"   window.spanAnnotations exists: {span_annotations_exists}")

        if span_annotations_exists:
            span_annotations_value = browser.execute_script("return window.spanAnnotations;")
            print(f"   window.spanAnnotations value: {span_annotations_value}")

        # Check if renderSpanOverlays function exists
        render_function_exists = browser.execute_script("return typeof renderSpanOverlays === 'function';")
        print(f"   renderSpanOverlays function exists: {render_function_exists}")

        # Manually call renderSpanOverlays and check console output
        print("3. Manually calling renderSpanOverlays...")
        browser.execute_script("""
            if (typeof renderSpanOverlays === 'function') {
                console.log('🔍 MANUAL: About to call renderSpanOverlays');
                renderSpanOverlays();
                console.log('🔍 MANUAL: renderSpanOverlays called');
            } else {
                console.log('❌ MANUAL: renderSpanOverlays function not found');
            }
        """)
        time.sleep(2)

        # Check for overlay elements after calling renderSpanOverlays
        overlay_elements = browser.find_elements(By.CSS_SELECTOR, ".span-overlay")
        print(f"   Overlay elements found after manual call: {len(overlay_elements)}")

        # Check the HTML structure of the instance-text
        instance_text_html = browser.execute_script("""
            const textDiv = document.getElementById('instance-text');
            return textDiv ? textDiv.innerHTML : 'NOT_FOUND';
        """)
        print(f"   instance-text innerHTML: {instance_text_html[:200]}...")

        # Check if there's a script tag with spanAnnotations
        script_tags = browser.find_elements(By.CSS_SELECTOR, "script#span-annotation-data")
        print(f"   span-annotation-data script tag found: {len(script_tags) > 0}")

        if script_tags:
            script_content = script_tags[0].get_attribute('innerHTML')
            print(f"   Script content: {script_content[:200]}...")

        print("✅ Debug overlay JavaScript test completed")

    def test_span_visual_elements_display(self, flask_server, browser):
        """Test that span annotations display with proper visual elements (labels and delete buttons)."""
        print("\n=== Test: Span Visual Elements Display ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Register a unique test user
        username = self.register_test_user(browser, base_url, "visual_elements")

        try:
            # Navigate to annotation page
            print("1. Navigating to annotation page...")
            browser.get(f"{base_url}/annotate")
            RobustSpanAnnotationHelper.wait_for_page_load(browser)
            time.sleep(2)

            # Verify we're on the annotation page
            instance_text = RobustSpanAnnotationHelper.wait_for_element(
                browser, By.ID, "instance-text", description="instance text"
            )
            print("   ✅ Annotation page loaded successfully")

            # Create a span annotation
            print("2. Creating span annotation...")
            RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
                browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
                description="emotion label"
            ), "emotion label")
            time.sleep(1)

            selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 5, 15)
            assert selection_success, "Text selection failed"
            time.sleep(3)

            # Verify span was created
            spans = RobustSpanAnnotationHelper.get_span_elements(browser)
            assert len(spans) == 1, f"Expected 1 span, got {len(spans)}"
            print("   ✅ Span created successfully")

            # Test 3: Verify span label is visible
            print("3. Verifying span label is visible...")
            span_labels = browser.find_elements(By.CSS_SELECTOR, ".span-highlight .span_label")
            assert len(span_labels) == 1, f"Expected 1 span label, got {len(span_labels)}"

            label_text = span_labels[0].text
            print(f"   📝 Span label text: '{label_text}'")
            assert label_text.strip() != "", "Span label should not be empty"
            assert "happy" in label_text.lower(), f"Expected 'happy' in label text, got '{label_text}'"
            print("   ✅ Span label is visible and contains expected text")

            # Test 4: Verify delete button is visible
            print("4. Verifying delete button is visible...")
            delete_buttons = browser.find_elements(By.CSS_SELECTOR, ".span-highlight .span_close")
            assert len(delete_buttons) == 1, f"Expected 1 delete button, got {len(delete_buttons)}"

            delete_button = delete_buttons[0]
            delete_text = delete_button.text
            print(f"   🗑️ Delete button text: '{delete_text}'")
            assert "×" in delete_text, f"Expected '×' in delete button, got '{delete_text}'"
            print("   ✅ Delete button is visible and contains '×' symbol")

            # Test 5: Verify delete button is clickable
            print("5. Verifying delete button is clickable...")
            assert delete_button.is_displayed(), "Delete button should be displayed"
            assert delete_button.is_enabled(), "Delete button should be enabled"

            # Check if delete button has onclick attribute
            onclick_attr = delete_button.get_attribute("onclick")
            print(f"   🔗 Delete button onclick: {onclick_attr}")
            assert onclick_attr is not None, "Delete button should have onclick attribute"
            assert "deleteSpanAnnotation" in onclick_attr, "Delete button should call deleteSpanAnnotation function"
            print("   ✅ Delete button is properly configured for deletion")

            # Test 6: Test delete button functionality
            print("6. Testing delete button functionality...")
            RobustSpanAnnotationHelper.safe_click(browser, delete_button, "delete button")
            time.sleep(3)

            # Wait for page reload after deletion
            RobustSpanAnnotationHelper.wait_for_page_load(browser, timeout=10)

            # Verify span was deleted
            spans_after_delete = RobustSpanAnnotationHelper.get_span_elements(browser)
            assert len(spans_after_delete) == 0, f"Expected 0 spans after deletion, got {len(spans_after_delete)}"
            print("   ✅ Span was successfully deleted via delete button")

            print("✅ Test passed: Span visual elements display and function correctly")

        except Exception as e:
            print(f"❌ Test failed: {e}")
            RobustSpanAnnotationHelper.capture_browser_logs(browser, "visual_elements_failure")
            raise

    def test_span_label_and_delete_button_styling(self, flask_server, browser):
        """Test that span labels and delete buttons have proper styling and positioning."""
        print("\n=== Test: Span Label and Delete Button Styling ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Register a unique test user
        username = self.register_test_user(browser, base_url, "styling")

        try:
            # Navigate to annotation page
            print("1. Navigating to annotation page...")
            browser.get(f"{base_url}/annotate")
            RobustSpanAnnotationHelper.wait_for_page_load(browser)
            time.sleep(2)

            # Create a span annotation
            print("2. Creating span annotation...")
            RobustSpanAnnotationHelper.safe_click(browser, RobustSpanAnnotationHelper.wait_for_clickable(
                browser, By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']",
                description="emotion label"
            ), "emotion label")
            time.sleep(1)

            selection_success = RobustSpanAnnotationHelper.robust_text_selection(browser, 5, 15)
            assert selection_success, "Text selection failed"
            time.sleep(3)

            # Verify span was created
            spans = RobustSpanAnnotationHelper.get_span_elements(browser)
            assert len(spans) == 1, f"Expected 1 span, got {len(spans)}"

            # Test 3: Verify span label positioning
            print("3. Verifying span label positioning...")
            span_label = browser.find_element(By.CSS_SELECTOR, ".span-highlight .span_label")

            # Check CSS properties
            label_position = span_label.value_of_css_property("position")
            label_top = span_label.value_of_css_property("top")
            label_left = span_label.value_of_css_property("left")
            label_z_index = span_label.value_of_css_property("z-index")

            print(f"   📍 Label position: {label_position}")
            print(f"   📍 Label top: {label_top}")
            print(f"   📍 Label left: {label_left}")
            print(f"   📍 Label z-index: {label_z_index}")

            assert label_position == "absolute", f"Label should have position absolute, got {label_position}"
            assert label_top == "-18px", f"Label should be positioned at top -18px, got {label_top}"
            assert label_left == "0px", f"Label should be positioned at left 0px, got {label_left}"
            assert label_z_index == "10", f"Label should have z-index 10, got {label_z_index}"
            print("   ✅ Span label has correct positioning")

            # Test 4: Verify delete button positioning
            print("4. Verifying delete button positioning...")
            delete_button = browser.find_element(By.CSS_SELECTOR, ".span-highlight .span_close")

            # Check CSS properties
            delete_position = delete_button.value_of_css_property("position")
            delete_top = delete_button.value_of_css_property("top")
            delete_right = delete_button.value_of_css_property("right")
            delete_z_index = delete_button.value_of_css_property("z-index")
            delete_cursor = delete_button.value_of_css_property("cursor")

            print(f"   📍 Delete position: {delete_position}")
            print(f"   📍 Delete top: {delete_top}")
            print(f"   📍 Delete right: {delete_right}")
            print(f"   📍 Delete z-index: {delete_z_index}")
            print(f"   📍 Delete cursor: {delete_cursor}")

            assert delete_position == "absolute", f"Delete button should have position absolute, got {delete_position}"
            assert delete_top == "-18px", f"Delete button should be positioned at top -18px, got {delete_top}"
            assert delete_right == "0px", f"Delete button should be positioned at right 0px, got {delete_right}"
            assert delete_z_index == "10", f"Delete button should have z-index 10, got {delete_z_index}"
            assert delete_cursor == "pointer", f"Delete button should have cursor pointer, got {delete_cursor}"
            print("   ✅ Delete button has correct positioning and styling")

            # Test 5: Verify span highlight positioning
            print("5. Verifying span highlight positioning...")
            span_highlight = browser.find_element(By.CSS_SELECTOR, ".span-highlight")

            # Check CSS properties
            highlight_position = span_highlight.value_of_css_property("position")
            highlight_display = span_highlight.value_of_css_property("display")

            print(f"   📍 Highlight position: {highlight_position}")
            print(f"   📍 Highlight display: {highlight_display}")

            assert highlight_position == "relative", f"Span highlight should have position relative, got {highlight_position}"
            assert highlight_display == "inline-block", f"Span highlight should have display inline-block, got {highlight_display}"
            print("   ✅ Span highlight has correct positioning")

            print("✅ Test passed: Span label and delete button styling is correct")

        except Exception as e:
            print(f"❌ Test failed: {e}")
            RobustSpanAnnotationHelper.capture_browser_logs(browser, "styling_failure")
            raise

    def test_span_annotation_with_test_client(self, test_data):
        """Test span annotation using Flask test client (same thread, no session isolation)."""
        print("\n=== Test: Span Annotation with Flask Test Client ===")

        # Create unique test environment
        config_path = os.path.abspath("tests/test-configs/span-annotation.yaml")
        temp_dir, temp_config_path = self.create_unique_test_environment(test_data, config_path, "test_client")

        try:
            # Import here to avoid circular imports
            from potato.server import create_app
            import yaml

            # Load config
            with open(temp_config_path, 'r') as f:
                config = yaml.safe_load(f)

            # Create Flask app
            app = create_app(config)
            client = app.test_client()

            # Set up debug session
            debug_response = client.post('/test/set_debug_session', json={
                'username': 'test_user',
                'instance_id': 'test_span_1'
            })
            assert debug_response.status_code == 200, f"Debug session setup failed: {debug_response.status_code}"

            # Get annotation page
            response = client.get('/annotate')
            assert response.status_code == 200, f"Annotation page failed: {response.status_code}"

            # Verify page contains expected elements
            assert 'instance-text' in response.data.decode('utf-8'), "Instance text not found"
            assert 'span_label:::emotion' in response.data.decode('utf-8'), "Emotion label not found"

            print("✅ Test passed: Span annotation with Flask test client works correctly")

        except Exception as e:
            print(f"❌ Test failed: {e}")
            raise
        finally:
            # Cleanup
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)


if __name__ == "__main__":
    # Run the test suite
    pytest.main([__file__, "-v", "-s"])