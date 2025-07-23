# Test Routes Documentation

This document describes the test routes added to the Potato annotation platform for backend testing and debugging purposes.

## Overview

The test routes are designed to expose internal system state for comprehensive backend testing. These routes are only available when the server is running in debug mode (`debug: true` in config).

## Available Test Routes

### 1. Health Check
**Endpoint:** `GET /test/health`

Checks if the server is running and core managers are accessible.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00",
  "managers": {
    "user_state_manager": "available",
    "item_state_manager": "available"
  },
  "config": {
    "debug_mode": true,
    "annotation_task_name": "Test Task"
  }
}
```

### 2. System State
**Endpoint:** `GET /test/system_state`

Returns comprehensive system state including user and item statistics.

**Response:**
```json
{
  "system_state": {
    "total_users": 5,
    "total_items": 100,
    "total_annotations": 250,
    "items_with_annotations": 80,
    "items_by_annotator_count": {
      "1": 30,
      "2": 25,
      "3": 15
    }
  },
  "users": {
    "user1": {
      "phase": "ANNOTATION",
      "annotations_count": 50,
      "has_assignments": true,
      "remaining_assignments": false
    }
  },
  "config": {
    "debug_mode": true,
    "annotation_task_name": "Test Task",
    "max_annotations_per_user": 100
  }
}
```

### 3. User State
**Endpoint:** `GET /test/user_state/<username>`

Returns detailed state for a specific user.

**Response:**
```json
{
  "username": "test_user",
  "phase": "ANNOTATION",
  "current_instance": {
    "id": "item_123",
    "text": "Sample text to annotate",
    "displayed_text": "Sample text to annotate"
  },
  "assignments": {
    "total": 10,
    "annotated": 7,
    "remaining": 3
  },
  "annotations": {
    "total_count": 7,
    "by_instance": {
      "item_123": {"rating": 5},
      "item_124": {"rating": 3}
    }
  },
  "hints": {
    "cached_hints": ["item_123", "item_124"]
  }
}
```

### 4. Item State
**Endpoint:** `GET /test/item_state`

Returns state for all items in the system.

**Response:**
```json
{
  "total_items": 100,
  "items": [
    {
      "id": "item_123",
      "text": "Sample text",
      "displayed_text": "Sample text",
      "annotators": ["user1", "user2"],
      "annotation_count": 2
    }
  ],
  "summary": {
    "items_with_annotations": 80,
    "items_without_annotations": 20,
    "average_annotations_per_item": 2.5
  }
}
```

### 5. Item Detail State
**Endpoint:** `GET /test/item_state/<item_id>`

Returns detailed state for a specific item.

**Response:**
```json
{
  "item_id": "item_123",
  "text": "Sample text",
  "displayed_text": "Sample text",
  "annotators": ["user1", "user2"],
  "annotation_count": 2,
  "annotations": {
    "user1": {"rating": 5},
    "user2": {"rating": 3}
  }
}
```

### 6. System Reset
**Endpoint:** `POST /test/reset`

Resets all system state (users and items).

**Response:**
```json
{
  "status": "reset_complete",
  "message": "All user and item state has been cleared"
}
```

### 7. Create User
**Endpoint:** `POST /test/create_user`

Creates a new test user with optional configuration.

**Request Body:**
```json
{
  "username": "new_test_user",
  "initial_phase": "ANNOTATION",
  "assign_items": true
}
```

**Parameters:**
- `username` (required): The username for the new user
- `initial_phase` (optional): Initial phase for the user (LOGIN, CONSENT, PRESTUDY, INSTRUCTIONS, TRAINING, ANNOTATION, POSTSTUDY, DONE)
- `assign_items` (optional): Whether to assign items to the user (default: false)

**Response:**
```json
{
  "status": "created",
  "username": "new_test_user",
  "initial_phase": "ANNOTATION",
  "assign_items": true,
  "message": "User 'new_test_user' created successfully",
  "user_state": {
    "phase": "ANNOTATION",
    "has_assignments": true,
    "assignments_count": 5
  }
}
```

### 8. Create Multiple Users
**Endpoint:** `POST /test/create_users`

Creates multiple test users in a single request.

**Request Body:**
```json
{
  "users": [
    {
      "username": "user1",
      "initial_phase": "ANNOTATION",
      "assign_items": true
    },
    {
      "username": "user2",
      "initial_phase": "INSTRUCTIONS",
      "assign_items": false
    }
  ]
}
```

**Response:**
```json
{
  "status": "completed",
  "summary": {
    "total_requested": 2,
    "created": 2,
    "failed": 0,
    "already_exists": 0
  },
  "results": {
    "created": [
      {
        "username": "user1",
        "initial_phase": "ANNOTATION",
        "assign_items": true,
        "user_state": {
          "phase": "ANNOTATION",
          "has_assignments": true,
          "assignments_count": 5
        }
      },
      {
        "username": "user2",
        "initial_phase": "INSTRUCTIONS",
        "assign_items": false,
        "user_state": {
          "phase": "INSTRUCTIONS",
          "has_assignments": false,
          "assignments_count": 0
        }
      }
    ],
    "failed": [],
    "already_exists": []
  }
}
```

### 9. Advance User Phase
**Endpoint:** `POST /test/advance_user_phase/<username>`

Advances a user's phase.

**Response:**
```json
{
  "status": "advanced",
  "username": "test_user",
  "old_phase": "INSTRUCTIONS",
  "new_phase": "ANNOTATION"
}
```

## Usage Examples

### Basic Health Check
```bash
curl http://localhost:9001/test/health
```

### Create User and Check State
```bash
# Create user with basic configuration
curl -X POST http://localhost:9001/test/create_user \
  -H "Content-Type: application/json" \
  -d '{"username": "test_user"}'

# Create user with advanced configuration
curl -X POST http://localhost:9001/test/create_user \
  -H "Content-Type: application/json" \
  -d '{
    "username": "advanced_user",
    "initial_phase": "ANNOTATION",
    "assign_items": true
  }'

# Create multiple users
curl -X POST http://localhost:9001/test/create_users \
  -H "Content-Type: application/json" \
  -d '{
    "users": [
      {"username": "user1", "initial_phase": "ANNOTATION", "assign_items": true},
      {"username": "user2", "initial_phase": "INSTRUCTIONS", "assign_items": false}
    ]
  }'

# Check user state
curl http://localhost:9001/test/user_state/test_user
```

### Complete Workflow Test
```bash
# 1. Check initial state
curl http://localhost:9001/test/system_state

# 2. Create user
curl -X POST http://localhost:9001/test/create_user \
  -H "Content-Type: application/json" \
  -d '{"username": "workflow_user"}'

# 3. Advance to annotation phase
curl -X POST http://localhost:9001/test/advance_user_phase/workflow_user

# 4. Submit annotation
curl -X POST http://localhost:9001/submit_annotation \
  -d "instance_id=test_item&annotation_data={\"rating\": 5}"

# 5. Check final state
curl http://localhost:9001/test/user_state/workflow_user
```

## Testing with Python

The test routes can be used in Python tests as shown in `tests/test_backend_state.py`:

```python
import requests
import json

def test_user_workflow():
    base_url = "http://localhost:9001"

    # Create user
    response = requests.post(
        f"{base_url}/test/create_user",
        json={"username": "test_user"}
    )
    assert response.status_code == 200

    # Check user state
    response = requests.get(f"{base_url}/test/user_state/test_user")
    assert response.status_code == 200
    user_state = response.json()
    assert user_state["username"] == "test_user"

    # Submit annotation
    annotation_data = {
        "instance_id": "test_item",
        "annotation_data": json.dumps({"rating": 5})
    }
    response = requests.post(f"{base_url}/submit_annotation", data=annotation_data)
    assert response.status_code in [200, 302]
```

## Security Considerations

- All test routes are only available when `debug: true` is set in the configuration
- These routes expose internal system state and should not be used in production
- The routes are designed for testing and debugging purposes only

## Error Handling

All test routes return appropriate HTTP status codes:
- `200`: Success
- `302`: Redirect (when not authenticated)
- `400`: Bad request (missing required data)
- `403`: Forbidden (not in debug mode)
- `404`: Not found (user/item doesn't exist)
- `409`: Conflict (user already exists)
- `500`: Internal server error

## Integration with Existing Tests

These routes can be used to enhance existing tests by:
1. Setting up test scenarios programmatically
2. Verifying state changes after operations
3. Testing complete workflows
4. Debugging test failures by inspecting system state

The routes complement the existing test infrastructure and provide a more comprehensive way to test backend functionality.