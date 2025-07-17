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

## Creating New Server Tests

### Basic Test Structure

```python
"""
Test description for the new test module.
"""

import pytest
import json
import tempfile
import os
from tests.helpers.flask_test_setup import FlaskTestServer


class TestNewFeature:
    """Test suite for the new feature."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with test data."""
        # Create temporary directory
        test_dir = tempfile.mkdtemp()

        # Create test data
        test_data = [
            {"id": "test_1", "text": "Test item 1"},
            {"id": "test_2", "text": "Test item 2"}
        ]

        data_file = os.path.join(test_dir, 'test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "Test Task",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "test_scheme",
                    "type": "radio",
                    "labels": ["option_1", "option_2"],
                    "description": "Test annotation scheme"
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
            port=9007,  # Use unique port
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