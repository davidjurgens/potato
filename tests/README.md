# Potato Test Suite

This directory contains comprehensive tests for the Potato annotation platform, covering both backend functionality and frontend user interface testing.

## Test File Security Policy

**IMPORTANT: All test configuration and data files must reside within the `tests/` directory.**

- **Temporary files**: Must be created in `tests/output/` or its subdirectories
- **Config files**: Must be within `tests/` directory structure
- **Data files**: Must be within `tests/` directory structure
- **Path validation**: All file paths in configs must be relative to `task_dir` or within `tests/`
- **No system temp directories**: Do NOT use `/tmp`, `/var`, or system temp directories for test files

This is required for path security and to ensure tests run in all environments.

## Test Utilities

Use the `tests/helpers/test_utils.py` module for creating secure test configurations:

```python
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    create_span_annotation_config,
    create_comprehensive_annotation_config,
    TestConfigManager
)

# Example: Create a span annotation test
test_dir = create_test_directory("my_span_test")
config_file, data_file = create_span_annotation_config(test_dir)

# Example: Using context manager for automatic cleanup
with TestConfigManager("my_test", annotation_schemes) as test_config:
    # Use test_config.config_path, test_config.data_path
    pass  # Automatic cleanup on exit
```

## Test Structure

### Server Tests (`tests/server/`)
Server tests use the `FlaskTestServer` class to test against real Flask server instances. These are integration tests that verify actual HTTP endpoints and server behavior.

**📖 [Server Test Documentation](server/README.md)** - Complete guide to server testing
**📋 [Quick Reference](server/QUICK_REFERENCE.md)** - Common patterns and code snippets
**📝 [Test Template](server/test_template.py)** - Template for creating new server tests

**Key Server Test Files:**
- **`test_backend_state.py`** - User and item state management
- **`test_annotation_workflow.py`** - Complete annotation process testing
- **`test_multi_phase_workflow.py`** - Phase transitions and consent workflows
- **`test_agreement_workflow.py`** - Multi-annotator agreement testing
- **`test_assignment_strategies.py`** - Different assignment algorithms
- **`test_annotation_types.py`** - Various annotation scheme testing
- **`test_error_handling_workflow.py`** - Error scenarios and recovery
- **`test_robust_span_annotation.py`** - Span annotation edge cases

### Selenium Tests (`tests/selenium/`)
Frontend tests using Selenium WebDriver to test the user interface and browser interactions.

**📖 [Selenium Test Documentation](selenium/README.md)** - Complete guide to Selenium testing

**Key Selenium Test Files:**
- **`test_frontend_span_system.py`** - Span annotation UI testing
- **`test_user_state_contract.py`** - User state contract verification
- **`test_api_contract.py`** - API contract testing via frontend
- **`test_multirate_annotation.py`** - Multi-rate annotation UI testing

### Unit Tests (`tests/unit/`)
Pure unit tests that test individual functions and classes without external dependencies.

**Key Unit Test Files:**
- **`test_annotation_types.py`** - Annotation type validation
- **`test_config_validation.py`** - Configuration validation
- **`test_user_state.py`** - User state management logic

### Test Infrastructure
- **`tests/helpers/flask_test_setup.py`** - FlaskTestServer class and test utilities
- **`tests/selenium/test_base.py`** - BaseSeleniumTest class for Selenium tests
- **`tests/conftest.py`** - Pytest fixtures and shared test setup
- **`tests/configs/`** - Test configuration files
- **`tests/data/`** - Test data files

## Test Architecture

### Server Tests (Integration)
- **FlaskTestServer**: Real Flask server instance for testing
- **Production Mode**: Tests run against production server (not debug mode)
- **Admin Authentication**: Automatic admin API key for admin endpoints
- **Session Management**: Full user session and authentication testing
- **Config Management**: File-based and dict-based configuration testing

### Selenium Tests (UI Integration)
- **BaseSeleniumTest**: Base class with automatic user registration/login
- **Headless Chrome**: Browser runs in headless mode for CI compatibility
- **Production Server**: Tests against real Flask server (not debug mode)
- **User Isolation**: Each test gets unique user account
- **Session Persistence**: Maintains user sessions across requests

### Unit Tests (Isolated)
- **Mock Interfaces**: No external dependencies
- **Fast Execution**: Quick feedback for development
- **Pure Functions**: Test individual components in isolation

## Annotation Types Tested

The test suite covers all major annotation types supported by Potato:

1. **Likert Scale** (`likert`) - Rating scales with radio buttons
2. **Checkbox/Multiselect** (`multiselect`) - Multiple choice selections
3. **Slider** (`slider`) - Range-based ratings
4. **Span Annotation** (`span`) - Text highlighting and labeling
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
# Run only server tests (integration)
pytest tests/server/ -v

# Run only Selenium tests (UI)
pytest tests/selenium/ -v

# Run only unit tests (isolated)
pytest tests/unit/ -v

# Run specific test file
pytest tests/server/test_backend_state.py -v

# Run specific test class
pytest tests/server/test_backend_state.py::TestBackendState -v

# Run specific test method
pytest tests/server/test_backend_state.py::TestBackendState::test_health_check -v

# Run with debug output
pytest tests/server/ -v -s
```

### Test Categories by Type

```bash
# Integration tests (server + Selenium)
pytest tests/server/ tests/selenium/ -v

# Unit tests only
pytest tests/unit/ -v

# All tests except Selenium (faster)
pytest tests/server/ tests/unit/ -v

# All tests except server (faster)
pytest tests/selenium/ tests/unit/ -v
```

## Creating New Tests

### Server Tests
1. **Use the template**: Copy `tests/server/test_template.py`
2. **Follow patterns**: See `tests/server/QUICK_REFERENCE.md`
3. **Use FlaskTestServer**: Always use the FlaskTestServer class
4. **Test production mode**: Server runs in production mode (`debug=False`)
5. **Use unique ports**: Each test class should use a different port

### Selenium Tests
1. **Inherit from BaseSeleniumTest**: Automatic user registration/login
2. **Use headless mode**: Chrome runs in headless mode
3. **Test production server**: Tests against real Flask server
4. **Follow UI patterns**: See `tests/selenium/README.md`

### Unit Tests
1. **No external dependencies**: Use mocks for external services
2. **Fast execution**: Keep tests quick for development feedback
3. **Pure functions**: Test individual components in isolation

## Test Data

Tests use various data sources:
- **Server tests**: Create temporary test data files
- **Selenium tests**: Use `tests/configs/` and `tests/data/`
- **Unit tests**: Use mock data or simple test fixtures

## Test Output

- **HTML Reports**: Generated in `test-results/report.html`
- **Coverage Reports**: Generated in `test-results/coverage/`
- **Console Output**: Verbose test results with pass/fail status

## Continuous Integration

The test suite is designed to work with CI/CD pipelines:
- **Unit tests**: Fast feedback for development
- **Server tests**: Integration validation
- **Selenium tests**: UI validation (can be run separately)
- **Coverage reporting**: Code quality metrics

## Troubleshooting

### Server Test Issues
- **Port conflicts**: Use unique ports for each test class
- **File paths**: Ensure data files use absolute paths or are relative to project root
- **Admin endpoints**: FlaskTestServer automatically adds admin API key
- **Session management**: Use proper session handling for user endpoints

### Selenium Test Issues
- **ChromeDriver**: Ensure ChromeDriver is installed and in PATH
- **Browser compatibility**: Check Chrome browser version compatibility
- **Headless mode**: Tests run in headless mode for CI environments
- **User authentication**: BaseSeleniumTest handles user registration/login

### Unit Test Issues
- **Import paths**: Ensure `potato` module is in Python path
- **Dependencies**: Check that all dependencies are installed
- **Mock setup**: Verify mock objects are properly configured

## Documentation

- **[Server Test Guide](server/README.md)** - Complete server testing documentation
- **[Selenium Test Guide](selenium/README.md)** - Complete Selenium testing documentation
- **[Quick Reference](server/QUICK_REFERENCE.md)** - Common test patterns and code snippets
- **[Test Template](server/test_template.py)** - Template for new server tests