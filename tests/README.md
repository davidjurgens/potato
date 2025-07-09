# Potato Test Suite

This directory contains comprehensive tests for the Potato annotation platform, covering both backend functionality and frontend user interface testing.

## Test Structure

### Backend Tests
- **`test_app_lifecycle.py`** - Server startup, debug mode, home page functionality
- **`test_auth.py`** - Authentication and session management
- **`test_annotation_api.py`** - Annotation submission and retrieval APIs
- **`test_user_state.py`** - User state transitions and phase logic
- **`test_annotation_types.py`** - Tests for different annotation types using simple examples
- **`test_annotation_schemas.py`** - Tests for annotation schema HTML generation
- **`test_annotation_workflow.py`** - End-to-end annotation workflow testing

### Config Validation Tests
- **`test_config_validation.py`** - Config file validation, required fields, annotation scheme validation, and stress testing
- **`test_config_server_integration.py`** - How Flask server uses config values, error handling, and various config scenarios

### Frontend Tests (Selenium)
- **`test_frontend_annotation.py`** - Annotation UI interaction testing
- **`test_frontend_login.py`** - Login UI and session flow testing

### Configuration
- **`conftest.py`** - Pytest fixtures and shared test setup
- **`pytest.ini`** - Pytest configuration and markers

## Annotation Types Tested

The test suite covers all major annotation types supported by Potato:

1. **Likert Scale** (`likert`) - Rating scales with radio buttons
2. **Checkbox/Multiselect** (`multiselect`) - Multiple choice selections
3. **Slider** (`slider`) - Range-based ratings
4. **Span Annotation** (`highlight`) - Text highlighting and labeling
5. **Radio Buttons** (`radio`) - Single choice selections
6. **Text Input** (`text`) - Free text responses
7. **Multirate** (`multirate`) - Rating matrices
8. **Select Dropdown** (`select`) - Dropdown selections
9. **Number Input** (`number`) - Numeric inputs
10. **Pure Display** (`pure_display`) - Information-only displays

## Running Tests

### Prerequisites

1. Install test dependencies:
```bash
pip install -r requirements-test.txt
```

2. For Selenium tests, install ChromeDriver:
```bash
# On macOS with Homebrew
brew install chromedriver

# Or download from https://chromedriver.chromium.org/
```

### Running All Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=potato --cov-report=html
```

### Running Specific Test Categories

```bash
# Run only backend tests (exclude Selenium)
pytest -m "not selenium"

# Run only Selenium tests
pytest -m selenium

# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run specific test file
pytest tests/test_annotation_types.py

# Run specific test class
pytest tests/test_annotation_types.py::TestAnnotationTypes

# Run specific test method
pytest tests/test_annotation_types.py::TestAnnotationTypes::test_likert_annotation_backend

# Run config validation tests
pytest tests/test_config_validation.py

# Run config stress tests only
pytest tests/test_config_validation.py::TestConfigStressTesting

# Run config server integration tests
pytest tests/test_config_server_integration.py
```

### Debug Mode Testing

The tests use the `--debug` flag to bypass authentication and automatically log in as `debug_user`. This allows for faster testing without manual authentication steps.

## Test Data

Tests use the simple examples from `project-hub/simple_examples/`:
- Config files in `configs/`
- Sample data in `data/`
- Various annotation types and formats

## Test Output

- **HTML Reports**: Generated in `test-results/report.html`
- **Coverage Reports**: Generated in `test-results/coverage/`
- **Console Output**: Verbose test results with pass/fail status

## Adding New Tests

### Backend Tests
1. Create test functions with descriptive names
2. Use the `client` fixture for Flask app testing
3. Test both success and error cases
4. Mock external dependencies when needed

### Frontend Tests
1. Mark tests with `@pytest.mark.selenium`
2. Use the `driver` fixture for Selenium WebDriver
3. Test user interactions and UI elements
4. Include proper cleanup in `finally` blocks

### Example Test Structure
```python
def test_new_feature(client):
    """Test description"""
    # Arrange
    # Act
    response = client.get("/some-endpoint")
    # Assert
    assert response.status_code == 200
    assert "expected content" in response.data

@pytest.mark.selenium
def test_new_ui_feature(driver):
    """Test UI feature"""
    try:
        driver.get("http://localhost:9000/")
        # Test UI interactions
        element = driver.find_element(By.ID, "some-element")
        element.click()
        assert "expected result" in driver.page_source
    finally:
        driver.quit()
```

## Continuous Integration

The test suite is designed to work with CI/CD pipelines:
- Fast unit tests for quick feedback
- Integration tests for end-to-end validation
- Selenium tests for UI validation (can be run separately)
- Coverage reporting for code quality metrics

## Troubleshooting

### Selenium Issues
- Ensure ChromeDriver is installed and in PATH
- Check Chrome browser version compatibility
- Use `--headless` mode for CI environments

### Server Issues
- Tests use different ports (9001, 9002) to avoid conflicts
- Debug mode is enabled for all tests
- Temporary directories are cleaned up automatically

### Import Issues
- Ensure `potato` module is in Python path
- Check that all dependencies are installed
- Verify test file structure matches imports