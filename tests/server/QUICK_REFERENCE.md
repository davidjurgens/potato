# Server Test Quick Reference

## Common Test Patterns

### 1. Basic Server Setup

```python
@pytest.fixture(scope="class", autouse=True)
def flask_server(self, request):
    """Create Flask test server."""
    test_dir = tempfile.mkdtemp()

    # Create test data
    test_data = [{"id": "test_1", "text": "Test item"}]
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
                "description": "Test scheme"
            }
        ],
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "task_dir": test_dir,
        "site_file": "base_template.html",
        "alert_time_each_instance": 0
    }

    # Write config file
    config_file = os.path.join(test_dir, 'test_config.yaml')
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    # Create and start server
    server = FlaskTestServer(port=9007, debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start server")

    yield server

    # Cleanup
    server.stop()
    shutil.rmtree(test_dir)
```

### 2. User Authentication

```python
def test_user_auth(self, flask_server):
    """Test user registration and login."""
    session = requests.Session()

    # Register user
    user_data = {"email": "test_user", "pass": "test_password"}
    reg_response = session.post(f"{flask_server.base_url}/register", data=user_data)
    assert reg_response.status_code in [200, 302]

    # Login user
    login_response = session.post(f"{flask_server.base_url}/auth", data=user_data)
    assert login_response.status_code in [200, 302]

    # Test authenticated access
    response = session.get(f"{flask_server.base_url}/annotate")
    assert response.status_code == 200
```

### 3. Admin Endpoint Testing

```python
def test_admin_endpoint(self, flask_server):
    """Test admin endpoint with automatic API key."""
    # FlaskTestServer automatically adds admin API key
    response = flask_server.get("/admin/system_state")
    assert response.status_code in [200, 404]  # 404 if endpoint doesn't exist

    # Or manually add API key
    response = flask_server.session.get(
        f"{flask_server.base_url}/admin/system_state",
        headers={'X-API-Key': 'admin_api_key'}
    )
    assert response.status_code in [200, 404]
```

### 4. Annotation Submission

```python
def test_annotation_submission(self, flask_server):
    """Test annotation submission workflow."""
    session = requests.Session()

    # Setup user
    user_data = {"email": "annotator", "pass": "password"}
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

### 5. Multi-Phase Workflow

```python
def test_multi_phase_workflow(self, flask_server):
    """Test multi-phase annotation workflow."""
    session = requests.Session()

    # Setup user
    user_data = {"email": "phase_user", "pass": "password"}
    session.post(f"{flask_server.base_url}/register", data=user_data)
    session.post(f"{flask_server.base_url}/auth", data=user_data)

    # Test consent phase
    consent_data = {
        "instance_id": "consent_1",
        "type": "radio",
        "schema": "consent_scheme",
        "state": [{"name": "agree", "value": "I agree"}]
    }
    response = session.post(f"{flask_server.base_url}/updateinstance", json=consent_data)
    assert response.status_code == 200

    # Test instructions phase
    instructions_data = {
        "instance_id": "instructions_1",
        "type": "radio",
        "schema": "instructions_scheme",
        "state": [{"name": "understand", "value": "I understand"}]
    }
    response = session.post(f"{flask_server.base_url}/updateinstance", json=instructions_data)
    assert response.status_code == 200
```

### 6. Error Handling

```python
def test_error_handling(self, flask_server):
    """Test error handling scenarios."""
    # Test invalid endpoint
    response = flask_server.get("/nonexistent")
    assert response.status_code == 404

    # Test invalid login
    session = requests.Session()
    invalid_data = {"email": "invalid", "pass": "wrong"}
    response = session.post(f"{flask_server.base_url}/auth", data=invalid_data)
    assert response.status_code in [200, 302, 401, 403]

    # Test invalid annotation data
    session = requests.Session()
    user_data = {"email": "error_user", "pass": "password"}
    session.post(f"{flask_server.base_url}/register", data=user_data)
    session.post(f"{flask_server.base_url}/auth", data=user_data)

    invalid_annotation = {
        "instance_id": "nonexistent",
        "type": "invalid_type",
        "schema": "invalid_schema",
        "state": []
    }
    response = session.post(f"{flask_server.base_url}/updateinstance", json=invalid_annotation)
    # Should return error status
    assert response.status_code in [400, 404, 422]
```

### 7. Concurrent Testing

```python
def test_concurrent_requests(self, flask_server):
    """Test server stability under concurrent load."""
    import threading

    results = []

    def make_request():
        try:
            response = flask_server.get("/")
            results.append(response.status_code)
        except Exception as e:
            results.append(f"Error: {e}")

    # Start multiple threads
    threads = [threading.Thread(target=make_request) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Verify results
    for result in results:
        if isinstance(result, int):
            assert result in [200, 302]
```

## Common Configurations

### Radio Button Annotation

```python
config = {
    "annotation_schemes": [
        {
            "name": "radio_scheme",
            "type": "radio",
            "labels": ["option_1", "option_2", "option_3"],
            "description": "Choose one option."
        }
    ]
}
```

### Checkbox Annotation

```python
config = {
    "annotation_schemes": [
        {
            "name": "checkbox_scheme",
            "type": "checkbox",
            "labels": ["feature_1", "feature_2", "feature_3"],
            "description": "Select all that apply."
        }
    ]
}
```

### Text Annotation

```python
config = {
    "annotation_schemes": [
        {
            "name": "text_scheme",
            "type": "text",
            "description": "Enter your response."
        }
    ]
}
```

### Span Annotation

```python
config = {
    "annotation_schemes": [
        {
            "name": "span_scheme",
            "type": "span",
            "labels": ["positive", "negative", "neutral"],
            "description": "Mark spans of text."
        }
    ]
}
```

### Multi-Phase Configuration

```python
config = {
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

## Common Assertions

### Status Code Checks

```python
# Success responses
assert response.status_code == 200  # OK
assert response.status_code in [200, 302]  # OK or redirect

# Error responses
assert response.status_code == 404  # Not found
assert response.status_code == 400  # Bad request
assert response.status_code == 401  # Unauthorized
assert response.status_code == 403  # Forbidden
assert response.status_code == 422  # Unprocessable entity
```

### Content Checks

```python
# Check response content
assert "expected_text" in response.text
assert response.json()["key"] == "expected_value"

# Check JSON response structure
data = response.json()
assert "required_field" in data
assert isinstance(data["list_field"], list)
assert len(data["list_field"]) > 0
```

### Session Checks

```python
# Check if user is authenticated
response = session.get(f"{flask_server.base_url}/annotate")
assert response.status_code == 200  # Should be accessible

# Check if user is not authenticated
response = requests.get(f"{flask_server.base_url}/annotate")
assert response.status_code in [302, 401, 403]  # Should redirect or deny
```

## Debugging Tips

### Add Debug Prints

```python
def test_with_debug(self, flask_server):
    """Test with debug output."""
    print(f"Server URL: {flask_server.base_url}")

    response = flask_server.get("/")
    print(f"Response status: {response.status_code}")
    print(f"Response headers: {dict(response.headers)}")
    print(f"Response content: {response.text[:500]}")

    assert response.status_code == 200
```

### Check Server State

```python
def test_server_state(self, flask_server):
    """Check server state via admin endpoints."""
    try:
        response = flask_server.get("/admin/system_state")
        if response.status_code == 200:
            state = response.json()
            print(f"Server state: {state}")
    except Exception as e:
        print(f"Could not get server state: {e}")
```

### Run with Verbose Output

```bash
# Run with verbose output
python -m pytest tests/server/test_my_test.py -v -s

# Run specific test method
python -m pytest tests/server/test_my_test.py::TestClass::test_method -v -s

# Run with maximum verbosity
python -m pytest tests/server/test_my_test.py -vvv -s
```

## Port Allocation

Use unique ports for each test class to avoid conflicts:

```python
# Test class 1
server = FlaskTestServer(port=9001, ...)

# Test class 2
server = FlaskTestServer(port=9002, ...)

# Test class 3
server = FlaskTestServer(port=9003, ...)
```

## Common Imports

```python
import pytest
import json
import tempfile
import os
import requests
import shutil
import yaml
from tests.helpers.flask_test_setup import FlaskTestServer
```