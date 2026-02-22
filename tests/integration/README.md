# Integration Tests

## Overview

Integration tests in `tests/integration/` verify complete user journeys through the Potato annotation platform. These are end-to-end tests that:

1. Start real Flask servers with actual config files
2. Use Selenium browsers to simulate user interactions
3. Test workflows from registration to annotation completion
4. Catch configuration errors and broken functionality

## Test Architecture

### IntegrationTestServer

The `IntegrationTestServer` class (in `base.py`) provides:

- **Server Lifecycle Management**: Start/stop Flask servers as subprocesses
- **Error Capture**: Captures stdout/stderr to detect startup errors
- **Working Directory Resolution**: Automatically determines the correct working directory for configs
- **Port Management**: Finds available ports automatically

```python
from tests.integration.base import IntegrationTestServer

# Start a server
server = IntegrationTestServer("path/to/config.yaml", port=9100)
success, error = server.start(timeout=30)

if success:
    # server.base_url is available
    print(f"Server running at {server.base_url}")

# Always stop the server
server.stop()
```

### BaseIntegrationTest

The `BaseIntegrationTest` class (in `base.py`) provides:

- Browser setup (headless Chrome)
- User registration and login helpers
- Annotation interaction utilities
- Screenshot capture on failure
- Proper cleanup

```python
from tests.integration.base import BaseIntegrationTest

class TestMyFeature(BaseIntegrationTest):
    config_path = "examples/classification/check-box/config.yaml"
    base_port = 9200

    def test_something(self):
        # Server is already started
        self.register_and_login()
        self.wait_for_annotation_page()

        # Test annotation
        self.click_checkbox("option_1")
        self.navigate_next()
```

## Test Categories

### 1. Smoke Tests (`test_smoke.py`)

Critical path tests that verify basic functionality:

- **Server Startup**: All example configs can start a server
- **Home Page**: Loads without JavaScript errors
- **Registration**: New users can register
- **Annotation Page**: Renders with expected elements
- **Basic Annotation**: Checkboxes/radios can be clicked

```bash
pytest tests/integration/test_smoke.py -v -m smoke
```

### 2. Workflow Tests (`test_workflows.py`)

Complete user journey tests:

- **Onboarding**: First-time annotator experience
- **Returning User**: Login and resume work
- **Multi-Phase**: Consent → Instructions → Training → Annotation
- **Error Recovery**: Session preservation after refresh

```bash
pytest tests/integration/test_workflows.py -v -m workflow
```

### 3. Annotation Types E2E (`test_annotation_types_e2e.py`)

End-to-end tests for each annotation type:

- Checkbox/multiselect
- Radio buttons
- Sliders
- Text input
- Span annotation

```bash
pytest tests/integration/test_annotation_types_e2e.py -v -m e2e
```

### 4. Persistence Tests (`test_persistence.py`)

State preservation tests:

- Annotations persist after navigation
- Session survives page refresh
- Cross-instance isolation

```bash
pytest tests/integration/test_persistence.py -v -m persistence
```

### 5. Edge Case Tests (`test_edge_cases.py`)

Boundary condition tests:

- Empty data files
- Unicode content
- Very long text
- Concurrent users

```bash
pytest tests/integration/test_edge_cases.py -v -m edge_case
```

## Fixtures (conftest.py)

### Available Fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `project_root` | session | Project root Path |
| `example_configs` | session | List of all example config files |
| `temp_output_dir` | function | Temporary directory for outputs |
| `base_port` | module | Random port in 9100-9900 range |
| `server_factory` | function | Factory to create test servers |
| `browser` | function | Chrome WebDriver instance |
| `chrome_options` | function | Chrome options for testing |
| `test_user` | function | Unique test user credentials |

### Config Parametrization

Tests using the `config_file` fixture are automatically parametrized to run for each example config:

```python
def test_server_starts(self, config_file: Path):
    # This test runs once for each config in examples/
    server = IntegrationTestServer(str(config_file))
    ...
```

### Known Issues

Some configs have known issues documented in `conftest.py`:

```python
CONFIGS_WITH_KNOWN_ISSUES = {
    "audio-annotation": "Missing required field: site_dir",
    "pairwise-comparison": "TypeError in pairwise comparison annotation",
}
```

Tests for these configs are marked `xfail` and documented for investigation.

## Custom Markers

| Marker | Description |
|--------|-------------|
| `@pytest.mark.smoke` | Fast, critical path tests |
| `@pytest.mark.workflow` | Complete user journey tests |
| `@pytest.mark.e2e` | Full annotation cycle tests |
| `@pytest.mark.persistence` | State preservation tests |
| `@pytest.mark.edge_case` | Boundary condition tests |
| `@pytest.mark.slow` | Tests taking >30 seconds |

## Running Tests

### Run All Integration Tests

```bash
pytest tests/integration/ -v
```

### Run by Marker

```bash
# Smoke tests only (fast)
pytest tests/integration/ -v -m smoke

# Workflow tests
pytest tests/integration/ -v -m workflow

# Skip slow tests
pytest tests/integration/ -v -m "not slow"
```

### Run Specific Test

```bash
pytest tests/integration/test_smoke.py::TestServerStartup::test_server_starts_successfully -v
```

### Run with Debug Output

```bash
pytest tests/integration/ -v -s --tb=long
```

## Screenshots

Failed tests automatically capture screenshots to:
```
tests/output/screenshots/
```

## Debugging Tips

### 1. Server Won't Start

Check the error output from `IntegrationTestServer`:

```python
server = IntegrationTestServer(config_path)
success, error = server.start()
if not success:
    print(f"Error: {error}")
    print(f"stdout: {server.startup_output}")
    print(f"stderr: {server.startup_errors}")
```

### 2. Element Not Found

Use explicit waits:

```python
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

element = WebDriverWait(browser, 10).until(
    EC.presence_of_element_located((By.ID, "my-element"))
)
```

### 3. Check Browser State

Take screenshots during debugging:

```python
browser.save_screenshot("debug_screenshot.png")
print(f"URL: {browser.current_url}")
print(f"Page source: {browser.page_source[:500]}")
```

### 4. Check JavaScript Errors

```python
logs = browser.get_log('browser')
for log in logs:
    if log['level'] == 'SEVERE':
        print(f"JS Error: {log['message']}")
```

## Writing New Integration Tests

### Template

```python
"""
Test description.
"""

import pytest
from pathlib import Path
from selenium.webdriver.common.by import By

from tests.integration.base import IntegrationTestServer

PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.mark.workflow
class TestMyFeature:
    """Test my feature."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with config."""
        config_path = PROJECT_ROOT / "examples" / "classification" / "check-box" / "config.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed: {error}")
        yield server
        server.stop()

    def test_something(self, server, browser, test_user):
        """Test that something works."""
        # Navigate and register
        browser.get(server.base_url)
        # ... registration code ...

        # Test assertions
        assert browser.find_elements(By.ID, "expected-element")
```

### Best Practices

1. **Unique Ports**: Each test class should use a unique port range
2. **Cleanup**: Always stop servers in fixture teardown
3. **Screenshots**: Capture screenshots on failure for debugging
4. **Skip vs Fail**: Use `pytest.skip()` for environment issues, `pytest.fail()` for actual bugs
5. **Explicit Waits**: Use WebDriverWait instead of `time.sleep()` when possible
6. **Isolation**: Each test should create its own user to avoid conflicts
