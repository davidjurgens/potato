# Server Test Documentation

## Overview

The server tests in `tests/server/` verify the Flask backend functionality using the `FlaskTestServer` class from `tests/helpers/flask_test_setup.py`. These tests run against a real Flask server instance and test actual HTTP endpoints, making them integration tests rather than unit tests.

## Test Architecture

### FlaskTestServer Class

The `FlaskTestServer` class provides a complete Flask server environment for testing:

- **Production Mode**: Server runs in production mode (`debug=False`) by default
- **Admin Authentication**: Automatically adds admin API key headers for admin endpoints
- **Session Management**: Handles user sessions and authentication
- **Config Management**: Supports both dict and file-based configurations
- **Cleanup**: Proper server shutdown and resource cleanup

### Key Features

1. **Automatic Admin API Key**: Admin endpoints (`/admin/*`) automatically get the `X-API-Key: admin_api_key` header
2. **Session Persistence**: Maintains session cookies across requests
3. **Config Validation**: Ensures all required config fields are present
4. **Template Resolution**: Uses real template files from the project
5. **Data File Path Resolution**: Automatically resolves relative data file paths

## Test Categories

### 1. Integration Tests (`test_flask_integration.py`)
- Basic server startup and response testing
- Server configuration validation
- Multiple request handling

### 2. Workflow Tests
- **Annotation Workflow** (`test_annotation_workflow.py`): Complete annotation process
- **Multi-Phase Workflow** (`test_multi_phase_workflow.py`): Phase transitions and consent
- **Agreement Workflow** (`test_agreement_workflow.py`): Multi-annotator agreement
- **Active Learning** (`test_active_learning_workflow.py`): Active learning features

### 3. State Management Tests
- **Backend State** (`test_backend_state.py`): User and item state management
- **User State Endpoint** (`test_user_state_endpoint.py`): User state API endpoints

### 4. Assignment Strategy Tests
- **Assignment Strategies** (`test_assignment_strategies.py`): Different assignment algorithms
- **Comprehensive Assignment** (`test_assignment_strategies_comprehensive.py`): Extended assignment testing

### 5. Annotation Type Tests
- **Annotation Types** (`test_annotation_types.py`): Different annotation schemes
- **Annotation Types Workflow** (`test_annotation_types_workflow.py`): Workflow with various types

### 6. Error Handling Tests
- **Error Handling Workflow** (`test_error_handling_workflow.py`): Error scenarios and recovery

### 7. Span Annotation Tests
- **Robust Span Annotation** (`test_robust_span_annotation.py`): Span annotation edge cases

## Annotation Persistence Testing

This section documents patterns and common fixes for testing annotation persistence across different annotation types using server-side API endpoints.

### Key Testing Patterns

#### 1. Annotation Submission via API
- **Use `/updateinstance` endpoint**: Submit annotations via POST to `/updateinstance`
- **Correct request format**: Include `instance_id`, `type`, `schema`, and `state`
- **Session management**: Maintain session cookies across requests

```python
def submit_annotation(self, session, instance_id, annotation_type, schema, state):
    """Submit annotation via API endpoint."""
    annotation_data = {
        "instance_id": instance_id,
        "type": annotation_type,
        "schema": schema,
        "state": state
    }

    response = session.post(
        f"{self.flask_server.base_url}/updateinstance",
        json=annotation_data
    )
    assert response.status_code == 200
    return response
```

#### 2. Annotation Retrieval
- **Use `/api/current_instance`**: Get current instance data including annotations
- **Check response format**: Verify annotations are included in the response
- **Parse annotation state**: Extract and verify annotation values

```python
def get_current_annotations(self, session):
    """Get current instance annotations."""
    response = session.get(f"{self.flask_server.base_url}/api/current_instance")
    assert response.status_code == 200

    data = response.json()
    return data.get('annotations', {})
```

#### 3. Instance Navigation
- **Use `/annotate` with POST**: Navigate between instances using POST to `/annotate`
- **Include navigation parameters**: Use `next` or `prev` parameters
- **Verify instance changes**: Check that instance ID changes after navigation

```python
def navigate_to_next(self, session):
    """Navigate to next instance."""
    response = session.post(f"{self.flask_server.base_url}/annotate", data={"next": "true"})
    assert response.status_code == 200
    return response

def navigate_to_prev(self, session):
    """Navigate to previous instance."""
    response = session.post(f"{self.flask_server.base_url}/annotate", data={"prev": "true"})
    assert response.status_code == 200
    return response
```

#### 4. Annotation Isolation Testing
- **Test per-instance isolation**: Verify annotations don't persist across instances
- **Test within-instance persistence**: Verify annotations persist when navigating away and back
- **Clear annotations**: Test annotation clearing functionality

```python
def test_annotation_isolation(self, flask_server):
    """Test that annotations are isolated per instance."""
    session = requests.Session()

    # Setup user
    user_data = {"email": "test_user", "pass": "test_password"}
    session.post(f"{flask_server.base_url}/register", data=user_data)
    session.post(f"{flask_server.base_url}/auth", data=user_data)

    # Submit annotation on instance 1
    annotation_data = {
        "instance_id": "test_1",
        "type": "likert",
        "schema": "likert_rating",
        "state": [{"name": "likert_rating", "value": "4"}]
    }
    response = session.post(f"{flask_server.base_url}/updateinstance", json=annotation_data)
    assert response.status_code == 200

    # Navigate to instance 2
    response = session.post(f"{flask_server.base_url}/annotate", data={"next": "true"})
    assert response.status_code == 200

    # Verify instance 2 has no annotations (isolation)
    response = session.get(f"{flask_server.base_url}/api/current_instance")
    assert response.status_code == 200

    data = response.json()
    annotations = data.get('annotations', {})
    assert len(annotations) == 0  # No annotations on new instance
```

### Common Fixes Applied

#### 1. Session Management
**Problem**: Tests losing session state between requests
**Solution**: Use `requests.Session()` to maintain cookies and session state

```python
# Good - Use session for state persistence
session = requests.Session()
session.post(f"{flask_server.base_url}/register", data=user_data)
session.post(f"{flask_server.base_url}/auth", data=user_data)

# Use same session for all subsequent requests
response = session.get(f"{flask_server.base_url}/annotate")
```

#### 2. Request Format
**Problem**: Incorrect JSON format for annotation submission
**Solution**: Use correct request structure with proper nesting

```python
# Correct annotation request format
annotation_data = {
    "instance_id": "test_1",
    "type": "likert",
    "schema": "likert_rating",
    "state": [
        {
            "name": "likert_rating",
            "value": "4"
        }
    ]
}
```

#### 3. Response Validation
**Problem**: Not properly validating API responses
**Solution**: Check status codes and response content

```python
def validate_annotation_response(self, response, expected_status=200):
    """Validate annotation API response."""
    assert response.status_code == expected_status

    if expected_status == 200:
        data = response.json()
        assert "success" in data or "status" in data
```

#### 4. Instance ID Management
**Problem**: Using hardcoded instance IDs that don't match test data
**Solution**: Get instance IDs dynamically from API responses

```python
def get_current_instance_id(self, session):
    """Get current instance ID from API."""
    response = session.get(f"{flask_server.base_url}/api/current_instance")
    assert response.status_code == 200

    data = response.json()
    return data.get('instance_id')
```

### Comprehensive Test Config

For testing multiple annotation types, use a comprehensive config:

```python
config = {
    "debug": False,
    "annotation_task_name": "Comprehensive Annotation Test",
    "require_password": False,
    "authentication": {"method": "in_memory"},
    "data_files": ["test_data.jsonl"],
    "item_properties": {"text_key": "text", "id_key": "id"},
    "annotation_schemes": [
        {
            "name": "likert_rating",
            "type": "likert",
            "labels": ["1", "2", "3", "4", "5"],
            "description": "Rate on a scale of 1-5"
        },
        {
            "name": "radio_choice",
            "type": "radio",
            "labels": ["option_a", "option_b", "option_c"],
            "description": "Choose one option"
        },
        {
            "name": "slider_value",
            "type": "slider",
            "min_value": 1,
            "max_value": 10,
            "starting_value": 5,
            "description": "Rate on a scale of 1-10"
        },
        {
            "name": "text_input",
            "type": "text",
            "description": "Enter your response"
        },
        {
            "name": "span_annotation",
            "type": "span",
            "labels": ["positive", "negative"],
            "description": "Mark spans of text"
        }
    ],
    "output_annotation_dir": "/tmp/test_output",
    "task_dir": "/tmp/test_task",
    "site_file": "base_template.html",
    "alert_time_each_instance": 0
}
```

### Debugging Tips

#### 1. Print Request/Response Details
```python
def debug_api_call(self, method, url, data=None, cookies=None):
    """Debug API call with detailed logging."""
    print(f"Making {method} request to {url}")
    if data:
        print(f"Request data: {data}")
    if cookies:
        print(f"Cookies: {cookies}")

    if method == "GET":
        response = requests.get(url, cookies=cookies)
    else:
        response = requests.post(url, json=data, cookies=cookies)

    print(f"Response status: {response.status_code}")
    print(f"Response content: {response.text[:500]}")
    return response
```

#### 2. Verify Session State
```python
def verify_session_state(self, session):
    """Verify current session state."""
    response = session.get(f"{self.flask_server.base_url}/api/current_instance")
    print(f"Current instance response: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Current instance: {data.get('instance_id')}")
        print(f"Current annotations: {data.get('annotations')}")
```

#### 3. Check Server Logs
```python
def check_server_logs(self):
    """Check for relevant server log messages."""
    # Server logs are automatically captured by FlaskTestServer
    # Look for authentication, annotation, and navigation messages
    pass
```

### Example: Complete Annotation Persistence Test

```python
import pytest
import requests
import json
import tempfile
import os
from tests.helpers.flask_test_setup import FlaskTestServer

class TestAnnotationPersistence:
    """Test annotation persistence across different annotation types."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with comprehensive annotation config."""
        test_dir = tempfile.mkdtemp()

        # Create test data
        test_data = [
            {"id": "test_1", "text": "Test item 1"},
            {"id": "test_2", "text": "Test item 2"},
            {"id": "test_3", "text": "Test item 3"}
        ]

        data_file = os.path.join(test_dir, 'test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create comprehensive config
        config = {
            "debug": False,
            "annotation_task_name": "Comprehensive Annotation Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "likert_rating",
                    "type": "likert",
                    "labels": ["1", "2", "3", "4", "5"],
                    "description": "Rate on a scale of 1-5"
                },
                {
                    "name": "radio_choice",
                    "type": "radio",
                    "labels": ["option_a", "option_b", "option_c"],
                    "description": "Choose one option"
                },
                {
                    "name": "slider_value",
                    "type": "slider",
                    "min_value": 1,
                    "max_value": 10,
                    "starting_value": 5,
                    "description": "Rate on a scale of 1-10"
                },
                {
                    "name": "text_input",
                    "type": "text",
                    "description": "Enter your response"
                }
            ],
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }

        # Write config file
        config_file = os.path.join(test_dir, 'test_config.yaml')
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create and start server
        server = FlaskTestServer(
            port=9007,
            debug=False,
            config_file=config_file
        )

        if not server.start():
            pytest.fail("Failed to start Flask test server")

        yield server

        # Cleanup
        server.stop()
        import shutil
        shutil.rmtree(test_dir)

    def test_likert_annotation_persistence(self, flask_server):
        """Test that likert annotations persist within the same instance."""
        session = requests.Session()

        # Setup user
        user_data = {"email": "test_user", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Get current instance
        response = session.get(f"{flask_server.base_url}/api/current_instance")
        assert response.status_code == 200
        data = response.json()
        instance_id = data['instance_id']

        # Submit likert annotation
        annotation_data = {
            "instance_id": instance_id,
            "type": "likert",
            "schema": "likert_rating",
            "state": [{"name": "likert_rating", "value": "3"}]
        }
        response = session.post(f"{flask_server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

        # Navigate away and back
        session.post(f"{flask_server.base_url}/annotate", data={"next": "true"})
        session.post(f"{flask_server.base_url}/annotate", data={"prev": "true"})

        # Verify annotation persists
        response = session.get(f"{flask_server.base_url}/api/current_instance")
        assert response.status_code == 200

        data = response.json()
        annotations = data.get('annotations', {})
        assert 'likert_rating' in annotations
        assert annotations['likert_rating'] == '3'

    def test_annotation_isolation(self, flask_server):
        """Test that annotations don't persist across different instances."""
        session = requests.Session()

        # Setup user
        user_data = {"email": "test_user2", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Get current instance
        response = session.get(f"{flask_server.base_url}/api/current_instance")
        assert response.status_code == 200
        data = response.json()
        instance_id = data['instance_id']

        # Submit annotation on first instance
        annotation_data = {
            "instance_id": instance_id,
            "type": "likert",
            "schema": "likert_rating",
            "state": [{"name": "likert_rating", "value": "4"}]
        }
        response = session.post(f"{flask_server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

        # Navigate to next instance
        response = session.post(f"{flask_server.base_url}/annotate", data={"next": "true"})
        assert response.status_code == 200

        # Verify new instance has no annotations
        response = session.get(f"{flask_server.base_url}/api/current_instance")
        assert response.status_code == 200

        data = response.json()
        annotations = data.get('annotations', {})
        assert len(annotations) == 0  # No annotations on new instance
```

## Path Security and Temporary Files

**CRITICAL: All test files must be created within the `tests/` directory structure.**

- **Config files**: Must be within `tests/output/` or subdirectories
- **Data files**: Must be within `tests/` directory structure
- **Task directory**: Must be set to the directory containing the config file
- **File paths**: All paths in config must be relative to `task_dir` or within `tests/`
- **No system temp directories**: Do NOT use `/tmp`, `/var`, or system temp directories

### Using Test Utilities

Always use the test utilities for creating secure test configurations:

```python
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    TestConfigManager
)
```

## Creating New Server Tests

### Basic Test Structure

```python
"""
Test description for the new test module.
"""

import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestNewFeature:
    """Test suite for the new feature."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with test data."""
        # Use TestConfigManager for secure test setup
        annotation_schemes = [
            {
                "name": "test_scheme",
                "annotation_type": "radio",
                "labels": ["option_1", "option_2"],
                "description": "Test annotation scheme"
            }
        ]

        with TestConfigManager("test_feature", annotation_schemes) as test_config:
            # Create and start server
            server = FlaskTestServer(
                port=9007,  # Use unique port
                debug=False,
                config_file=test_config.config_path
            )

            if not server.start():
                pytest.fail("Failed to start Flask test server")

            yield server

            # Cleanup
            server.stop()
            # TestConfigManager handles directory cleanup automatically

    def test_new_feature(self, flask_server):
        """Test the new feature functionality."""
        # Test using production endpoints
        session = requests.Session()

        # Register and login user
        user_data = {"email": "test_user", "pass": "test_password"}
        reg_response = session.post(f"{flask_server.base_url}/register", data=user_data)
        assert reg_response.status_code in [200, 302]

        login_response = session.post(f"{flask_server.base_url}/auth", data=user_data)
        assert login_response.status_code in [200, 302]

        # Test the feature
        response = session.get(f"{flask_server.base_url}/annotate")
        assert response.status_code == 200

        # Add your specific test logic here
```

### Advanced Test Patterns

#### 1. Testing Admin Endpoints

```python
def test_admin_endpoint(self, flask_server):
    """Test admin endpoint with automatic API key."""
    # FlaskTestServer automatically adds admin API key
    response = flask_server.get("/admin/system_state")
    assert response.status_code == 200

    # Or use the session directly
    response = flask_server.session.get(
        f"{flask_server.base_url}/admin/system_state",
        headers={'X-API-Key': 'admin_api_key'}
    )
    assert response.status_code == 200
```

#### 2. Testing User Sessions

```python
def test_user_session(self, flask_server):
    """Test user session management."""
    session = requests.Session()

    # Register and login
    user_data = {"email": "test_user", "pass": "test_password"}
    session.post(f"{flask_server.base_url}/register", data=user_data)
    session.post(f"{flask_server.base_url}/auth", data=user_data)

    # Test authenticated endpoint
    response = session.get(f"{flask_server.base_url}/annotate")
    assert response.status_code == 200
```

#### 3. Testing Annotation Workflows

```python
def test_annotation_workflow(self, flask_server):
    """Test complete annotation workflow."""
    session = requests.Session()

    # Setup user
    user_data = {"email": "test_user", "pass": "test_password"}
    session.post(f"{flask_server.base_url}/register", data=user_data)
    session.post(f"{flask_server.base_url}/auth", data=user_data)

    # Submit annotation
    annotation_data = {
        "instance_id": "test_1",
        "type": "radio",
        "schema": "test_scheme",
        "state": [{"name": "option_1", "value": "option_1"}]
    }

    response = session.post(
        f"{flask_server.base_url}/updateinstance",
        json=annotation_data
    )
    assert response.status_code == 200
```

## Configuration Patterns

### Minimal Config

```python
config = {
    "debug": False,
    "annotation_task_name": "Test Task",
    "require_password": False,
    "authentication": {"method": "in_memory"},
    "data_files": ["test_data.jsonl"],
    "item_properties": {"text_key": "text", "id_key": "id"},
    "annotation_schemes": [
        {
            "name": "test_scheme",
            "type": "radio",
            "labels": ["option_1", "option_2"],
            "description": "Test scheme"
        }
    ],
    "output_annotation_dir": "/tmp/test_output",
    "task_dir": "/tmp/test_task",
    "site_file": "base_template.html",
    "alert_time_each_instance": 0
}
```

### Multi-Phase Config

```python
config = {
    # ... basic config ...
    "phases": {
        "order": ["consent", "instructions", "annotation"],
        "consent": {
            "type": "consent",
            "file": "consent.json"
        },
        "instructions": {
            "type": "instructions",
            "file": "instructions.json"
        },
        "annotation": {
            "type": "annotation"
        }
    }
}
```

### Span Annotation Config

```python
config = {
    # ... basic config ...
    "annotation_schemes": [
        {
            "name": "span_scheme",
            "type": "span",
            "labels": ["positive", "negative"],
            "description": "Mark spans of text"
        }
    ]
}
```

## Best Practices

### 1. Test Isolation
- Each test should use unique data and users
- Clean up temporary files and directories
- Use unique ports for each test class

### 2. Error Handling
- Test both success and failure scenarios
- Verify proper error responses and status codes
- Test edge cases and invalid inputs

### 3. Authentication
- Use production endpoints for user registration/login
- Test both authenticated and unauthenticated access
- Verify proper session management

### 4. Data Management
- Create realistic test data
- Test with various data sizes and formats
- Verify data persistence and retrieval

### 5. Performance
- Keep tests focused and fast
- Avoid unnecessary server restarts
- Use appropriate timeouts

## Running Tests

### Run All Server Tests
```bash
python -m pytest tests/server/ -v
```

### Run Specific Test File
```bash
python -m pytest tests/server/test_backend_state.py -v
```

### Run Specific Test Method
```bash
python -m pytest tests/server/test_backend_state.py::TestBackendState::test_health_check -v
```

### Run with Debug Output
```bash
python -m pytest tests/server/ -v -s
```

## Troubleshooting

### Common Issues

1. **Port Conflicts**: Use unique ports for each test class
2. **File Paths**: Ensure data files use absolute paths or are relative to project root
3. **Template Issues**: Verify template files exist and are accessible
4. **Authentication**: Check that admin API key is being sent for admin endpoints
5. **Session Management**: Ensure proper session handling for user endpoints

### Debug Mode

To debug test issues:
```python
# Add debug prints
print(f"Server URL: {flask_server.base_url}")
print(f"Response status: {response.status_code}")
print(f"Response content: {response.text[:500]}")

# Use pytest -s to see print statements
```

### Server Logs

The FlaskTestServer provides detailed logging:
- Server startup/shutdown messages
- Configuration validation
- Request/response details
- Error messages and stack traces

## Integration with CI/CD

Server tests are designed to run in CI/CD environments:
- Headless operation (no GUI required)
- Automatic cleanup of resources
- Consistent behavior across environments
- Proper error reporting and exit codes

## Future Enhancements

1. **Parallel Test Support**: Enhanced support for running tests in parallel
2. **Test Data Factories**: Reusable test data generation
3. **Mock External Services**: Mock external dependencies
4. **Performance Benchmarks**: Track test execution times
5. **Coverage Reporting**: Measure test coverage for server endpoints