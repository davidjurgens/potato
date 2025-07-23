# Selenium Test Authentication System

## Overview

All Selenium tests in this project now use a consistent authentication system based on the `BaseSeleniumTest` class. This ensures that every test has a unique, authenticated user session and eliminates authentication-related test failures.

## Authentication Flow

### 1. Automatic User Registration and Login

Each test inherits from `BaseSeleniumTest` which automatically:

1. **Creates a unique test user** for each test run
2. **Registers the user** via the web interface
3. **Logs in the user** and verifies authentication
4. **Provides a fresh WebDriver** instance for each test
5. **Cleans up** after each test

### 2. Test Isolation

- **Unique users**: Each test gets a user with a timestamp-based name (e.g., `test_user_TestClassName_1752587366`)
- **Fresh sessions**: Each test starts with a clean browser session
- **No conflicts**: Tests can run concurrently without interfering with each other

## Usage

### Basic Test Structure

```python
from tests.selenium.test_base import BaseSeleniumTest

class TestMyFeature(BaseSeleniumTest):
    """
    Test suite for my feature.

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_something(self):
        """Test that something works correctly."""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Your test logic here...
        self.wait_for_element(By.ID, "instance-text")

        # Test assertions...
        self.assertTrue(something_works)
```

### Available Helper Methods

The `BaseSeleniumTest` class provides several helper methods:

#### Authentication Methods
- `register_user()`: Registers a new test user
- `login_user()`: Logs in the test user
- `verify_authentication()`: Verifies the user is properly authenticated

#### Utility Methods
- `get_session_cookies()`: Get session cookies for API requests
- `wait_for_element(by, value, timeout=10)`: Wait for element to be present
- `wait_for_element_visible(by, value, timeout=10)`: Wait for element to be visible
- `execute_script_safe(script, *args)`: Execute JavaScript with error handling

#### Properties
- `self.driver`: Selenium WebDriver instance
- `self.server`: FlaskTestServer instance
- `self.test_user`: Current test user's username
- `self.test_password`: Current test user's password

## Test Configuration

### Server Setup
- **Port**: 9008 (configurable in `setUpClass`)
- **Config**: Uses `tests/configs/frontend-span-test.yaml`
- **Mode**: Production mode (not debug)
- **Headless**: Chrome runs in headless mode for CI/CD compatibility

### Browser Configuration
- **Browser**: Chrome with headless mode
- **Window Size**: 1920x1080
- **Extensions**: Disabled for consistency
- **Images**: Disabled for faster loading

## Migration Guide

### Before (Old Pattern)
```python
class TestOldPattern(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Manual server setup
        cls.server = FlaskTestServer(...)
        cls.driver = webdriver.Chrome(...)

    def setUp(self):
        # Manual user registration and login
        self.register_user()
        self.login_user()

    def register_user(self):
        # Manual registration code...

    def login_user(self):
        # Manual login code...
```

### After (New Pattern)
```python
from tests.selenium.test_base import BaseSeleniumTest

class TestNewPattern(BaseSeleniumTest):
    """
    Test suite for new pattern.

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_something(self):
        # User is already authenticated!
        self.driver.get(f"{self.server.base_url}/annotate")
        # Test logic...
```

## Benefits

### 1. Consistency
- All tests use the same authentication flow
- No more authentication-related test failures
- Standardized test setup and teardown

### 2. Reliability
- Unique users prevent test interference
- Fresh sessions for each test
- Proper cleanup after each test

### 3. Maintainability
- Single source of truth for authentication logic
- Easy to update authentication flow for all tests
- Clear separation of concerns

### 4. Debugging
- Better error messages for authentication issues
- Consistent logging and debugging output
- Easy to identify which test user is being used

## Troubleshooting

### Common Issues

#### 1. Authentication Failures
If a test fails with authentication errors:
- Check that the test inherits from `BaseSeleniumTest`
- Verify the server is running on the correct port
- Check that the test config file exists

#### 2. Element Not Found
If elements can't be found:
- Use `self.wait_for_element()` instead of `find_element()`
- Add appropriate timeouts for slow-loading elements
- Check that the user is properly authenticated

#### 3. JavaScript Errors
If JavaScript execution fails:
- Use `self.execute_script_safe()` for better error reporting
- Check that the page has fully loaded before executing scripts
- Verify that required JavaScript libraries are loaded

### Debug Mode

To run tests with more verbose output:
```bash
python -m pytest tests/selenium/test_my_feature.py -v -s
```

The `-s` flag shows print statements and the `-v` flag shows verbose output.

## Best Practices

### 1. Test Documentation
Always document your test class with:
- Purpose of the test suite
- Authentication note (handled by BaseSeleniumTest)
- Any special setup requirements

### 2. Element Waiting
Use the provided wait methods instead of direct element access:
```python
# Good
element = self.wait_for_element(By.ID, "my-element")

# Bad
element = self.driver.find_element(By.ID, "my-element")  # May fail if not loaded
```

### 3. JavaScript Execution
Use the safe JavaScript execution method:
```python
# Good
result = self.execute_script_safe("return window.myFunction()")

# Bad
result = self.driver.execute_script("return window.myFunction()")  # No error handling
```

### 4. Test Isolation
Don't rely on state from other tests:
- Each test should be independent
- Use unique data when possible
- Clean up any test-specific state

## File Structure

```
tests/selenium/
├── test_base.py              # Base class with authentication
├── test_span_offset_diagnostics.py  # Example test using base class
├── test_frontend_span_system.py     # Refactored test
├── README.md                 # This documentation
└── ...                       # Other test files
```

## Annotation Persistence Testing

This section documents patterns and common fixes for testing annotation persistence across different annotation types (likert, radio, slider, text, span).

### Key Testing Patterns

#### 1. Form Element Interaction
- **Click labels, not inputs**: For radio buttons and checkboxes, click the visible label instead of the hidden input
- **Use correct element names**: Ensure form element names match the config schema names
- **Wait for elements**: Always wait for form elements to be present before interacting

```python
# Good - Click the label
self.wait_for_element(By.ID, "likert_rating_label").click()

# Bad - Click the hidden input
self.driver.find_element(By.NAME, "likert_rating").click()
```

#### 2. Slider Configuration
- **Correct config keys**: Use `min_value` and `max_value` (not `min`/`max`)
- **Include starting_value**: Always specify a starting value for sliders

```yaml
# Good slider config
annotation_schemes:
  - name: complexity
    type: slider
    min_value: 1
    max_value: 5
    starting_value: 3
    description: "Rate complexity"
```

#### 3. Navigation Button IDs
- **Use correct button IDs**: Navigation buttons have specific IDs that must match
- **Check button visibility**: Ensure buttons are visible before clicking

```python
# Correct button IDs
next_button = self.wait_for_element(By.ID, "next-button")
prev_button = self.wait_for_element(By.ID, "prev-button")
```

#### 4. Annotation Isolation vs Persistence
- **Understand system behavior**: Annotations are isolated per instance, not persisted across instances
- **Test isolation**: Verify that annotations don't carry over between instances
- **Test persistence within instance**: Verify annotations persist when navigating away and back to the same instance

```python
# Test annotation isolation (correct behavior)
def test_annotation_isolation(self):
    # Submit annotation on instance 1
    self.submit_annotation("instance_1", "value1")

    # Navigate to instance 2
    self.navigate_to_next()

    # Verify instance 2 has no annotations (isolation)
    annotations = self.get_current_annotations()
    assert len(annotations) == 0
```

### Common Fixes Applied

#### 1. Form Element Selectors
**Problem**: Tests using incorrect element names or selectors
**Solution**: Use exact schema names from config and click visible labels

```python
# Fixed selector pattern
def submit_likert_annotation(self, value):
    # Click the label, not the input
    label = self.wait_for_element(By.ID, f"likert_rating_{value}_label")
    label.click()

    # Submit the form
    submit_button = self.wait_for_element(By.ID, "submit-button")
    submit_button.click()
```

#### 2. Slider Configuration
**Problem**: Slider config using wrong keys (`min`/`max` instead of `min_value`/`max_value`)
**Solution**: Use correct config keys and include `starting_value`

```yaml
# Fixed slider config
annotation_schemes:
  - name: complexity
    type: slider
    min_value: 1
    max_value: 5
    starting_value: 3
    description: "Rate complexity"
```

#### 3. Navigation Button IDs
**Problem**: Tests using incorrect button IDs
**Solution**: Use correct button IDs from the template

```python
# Fixed navigation
def navigate_to_next(self):
    next_button = self.wait_for_element(By.ID, "next-button")
    next_button.click()
    time.sleep(1)  # Wait for navigation
```

#### 4. Test Logic Corrections
**Problem**: Tests expecting annotations to persist across instances
**Solution**: Update tests to verify annotation isolation (correct behavior)

```python
# Fixed test logic
def test_annotation_persistence_within_instance(self):
    # Submit annotation
    self.submit_annotation("test_value")

    # Navigate away and back
    self.navigate_to_next()
    self.navigate_to_prev()

    # Verify annotation persists on same instance
    current_value = self.get_current_annotation_value()
    assert current_value == "test_value"

def test_annotation_isolation_between_instances(self):
    # Submit annotation on instance 1
    self.submit_annotation("value1")

    # Navigate to instance 2
    self.navigate_to_next()

    # Verify instance 2 has no annotations (isolation)
    annotations = self.get_current_annotations()
    assert len(annotations) == 0
```

### Comprehensive Test Config

For testing multiple annotation types, use a comprehensive config:

```yaml
annotation_schemes:
  - name: likert_rating
    type: likert
    labels: ["1", "2", "3", "4", "5"]
    description: "Rate on a scale of 1-5"

  - name: radio_choice
    type: radio
    labels: ["option_a", "option_b", "option_c"]
    description: "Choose one option"

  - name: slider_value
    type: slider
    min_value: 1
    max_value: 10
    starting_value: 5
    description: "Rate on a scale of 1-10"

  - name: text_input
    type: text
    description: "Enter your response"

  - name: span_annotation
    type: span
    labels: ["positive", "negative"]
    description: "Mark spans of text"
```

### Debugging Tips

#### 1. Print Debug Information
```python
def debug_current_state(self):
    print(f"Current instance: {self.get_current_instance_id()}")
    print(f"Current annotations: {self.get_current_annotations()}")
    print(f"Available form elements: {self.get_form_elements()}")
```

#### 2. Check Element Visibility
```python
def verify_element_visible(self, element_id):
    element = self.wait_for_element(By.ID, element_id)
    assert element.is_displayed(), f"Element {element_id} is not visible"
```

#### 3. Verify Config Compatibility
```python
def verify_config_compatibility(self):
    # Check that all expected form elements exist
    expected_elements = ["likert_rating", "radio_choice", "slider_value", "text_input"]
    for element in expected_elements:
        self.wait_for_element(By.NAME, element)
```

### Example: Complete Annotation Persistence Test

```python
from tests.selenium.test_base import BaseSeleniumTest
from selenium.webdriver.common.by import By
import time

class TestAnnotationPersistence(BaseSeleniumTest):
    """
    Test annotation persistence across different annotation types.

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_likert_annotation_persistence(self):
        """Test that likert annotations persist within the same instance."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Submit likert annotation
        likert_label = self.wait_for_element(By.ID, "likert_rating_3_label")
        likert_label.click()

        submit_button = self.wait_for_element(By.ID, "submit-button")
        submit_button.click()
        time.sleep(1)

        # Navigate away and back
        next_button = self.wait_for_element(By.ID, "next-button")
        next_button.click()
        time.sleep(1)

        prev_button = self.wait_for_element(By.ID, "prev-button")
        prev_button.click()
        time.sleep(1)

        # Verify annotation persists
        selected_likert = self.driver.find_element(By.CSS_SELECTOR, "input[name='likert_rating']:checked")
        assert selected_likert.get_attribute("value") == "3"

    def test_annotation_isolation(self):
        """Test that annotations don't persist across different instances."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Submit annotation on first instance
        likert_label = self.wait_for_element(By.ID, "likert_rating_4_label")
        likert_label.click()

        submit_button = self.wait_for_element(By.ID, "submit-button")
        submit_button.click()
        time.sleep(1)

        # Navigate to next instance
        next_button = self.wait_for_element(By.ID, "next-button")
        next_button.click()
        time.sleep(1)

        # Verify no annotations on new instance
        selected_elements = self.driver.find_elements(By.CSS_SELECTOR, "input[name='likert_rating']:checked")
        assert len(selected_elements) == 0
```

## Future Enhancements

### Potential Improvements
1. **Parallel Test Support**: Enhanced support for running tests in parallel
2. **Custom User Data**: Allow tests to specify custom user data
3. **Session Persistence**: Option to reuse sessions across related tests
4. **Performance Monitoring**: Track test execution times and performance metrics

### Jest Integration
Consider adding Jest tests for frontend JavaScript unit testing:
- **Unit Tests**: Test individual JavaScript functions
- **Component Tests**: Test React components (if applicable)
- **Integration Tests**: Test JavaScript integration with DOM
- **Mock Support**: Mock browser APIs and external dependencies

See the section on Jest advantages below for more details.

## Span Annotation Test Design

This section documents conventions and patterns for writing Selenium tests for span annotation features. Follow these guidelines to ensure new tests work reliably and are easy to maintain.

### Key Conventions
- **Inherit from `BaseSeleniumTest`**: Handles user registration, login, and server setup automatically.
- **Always use `self.wait_for_element`**: Wait for elements like `#instance-text` before interacting with the page.
- **Wait for span manager initialization**: Use JavaScript to check `window.spanManager && window.spanManager.isInitialized` before testing span features.
- **Create spans via UI or API**:
  - For UI: Simulate text selection and label click.
  - For API: Use `/updateinstance` with correct `instance_id` and schema, then reload annotations in the browser.
- **Check overlays, labels, and delete buttons**:
  - Use `.find_elements(By.CLASS_NAME, ...)` for `span-overlay`, `span-label`, and `span-delete-btn`.
  - Assert their presence and correct text.
- **Reload and verify state**: Refresh the page and check that spans persist.
- **Use robust selectors**: Prefer IDs and class names that are stable and unique.
- **Debug with print statements**: Use `print()` to output DOM state and test progress for easier debugging.

### Example: Span Label and Delete Button Test

```python
from tests.selenium.test_base import BaseSeleniumTest
from selenium.webdriver.common.by import By
import requests
import time

class TestSpanAnnotationSelenium(BaseSeleniumTest):
    def test_span_label_and_delete_button_visibility(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        # Wait for span manager
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.isInitialized) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)
        session_cookies = self.get_session_cookies()
        # Create span via API
        span_request = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'emotion_spans',
            'state': [{
                'name': 'positive', 'title': 'Positive sentiment',
                'start': 0, 'end': 15, 'value': 'I am absolutely'
            }]
        }
        response = requests.post(f"{self.server.base_url}/updateinstance", json=span_request, cookies=session_cookies)
        assert response.status_code == 200
        # Reload annotations
        self.execute_script_safe("""if (window.spanManager) return window.spanManager.loadAnnotations('1');""")
        time.sleep(3)
        # Check overlays, labels, delete buttons
        overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        labels = self.driver.find_elements(By.CLASS_NAME, "span-label")
        deletes = self.driver.find_elements(By.CLASS_NAME, "span-delete-btn")
        print(f"Found {len(overlays)} overlays, {len(labels)} labels, {len(deletes)} delete buttons")
        assert len(overlays) > 0 and len(labels) > 0 and len(deletes) > 0
        # Check label text
        assert labels[0].text == "positive"
        # Test delete button
        deletes[0].click()
        time.sleep(2)
        assert len(self.driver.find_elements(By.CLASS_NAME, "span-overlay")) == 0
```

### Tips
- Use the above test as a template for new span annotation tests.
- Always check the correct `instance_id` and schema for your test data.
- Use `self.execute_script_safe` for all JS execution.
- Print debug info to help diagnose failures in CI or local runs.

For more advanced examples, see `test_span_annotation_selenium.py` and related files.