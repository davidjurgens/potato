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