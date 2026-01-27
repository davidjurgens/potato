# Potato API Reference

This document describes the HTTP API endpoints provided by Potato, enabling integration with custom frontends, automation scripts, or external systems.

---

## Overview

### Base URL
```
http://localhost:8000
```

### Authentication
Most endpoints require an active session. Sessions are established via the login endpoints and maintained via cookies.

For programmatic access, you can:
1. Use session cookies from a browser
2. Use the debug mode with automatic user creation
3. Implement the login flow programmatically

### Response Format
All API endpoints return JSON responses. Error responses include an `error` field with a description.

---

## Session Management

### Login
```http
POST /auth
Content-Type: application/x-www-form-urlencoded
```

**Request Body:**
```
username=your_username&password=your_password
```

**Response:** Redirects to annotation page on success, or returns error.

### Check Session
```http
GET /api/current_instance
```

**Response (authenticated):**
```json
{
  "instance_id": "item_001",
  "current_index": 0,
  "total_instances": 100
}
```

**Response (not authenticated):**
```json
{
  "error": "No active session"
}
```
Status: 401

### Logout
```http
POST /logout
```

**Response:** Redirects to home page.

---

## Annotation Endpoints

### Get Current Instance
```http
GET /api/current_instance
```

Returns information about the user's current annotation instance.

**Response:**
```json
{
  "instance_id": "item_001",
  "current_index": 5,
  "total_instances": 100
}
```

### Get Instance Content
```http
GET /api/spans/{instance_id}
```

Returns the text content and existing span annotations for an instance.

**Response:**
```json
{
  "instance_id": "item_001",
  "text": "The quick brown fox jumps over the lazy dog.",
  "spans": [
    {
      "id": "span_123",
      "schema": "entities",
      "label": "ANIMAL",
      "title": "ANIMAL",
      "start": 16,
      "end": 19,
      "text": "fox",
      "color": "#ff6b6b"
    }
  ]
}
```

### Get Annotations
```http
GET /get_annotations?instance_id={instance_id}
```

Returns all annotations (labels and spans) for a specific instance.

**Response:**
```json
{
  "label_annotations": {
    "sentiment": {
      "positive": "1"
    }
  },
  "span_annotations": {
    "entities:ANIMAL:16:19": "true"
  }
}
```

### Submit Annotation
```http
POST /updateinstance
Content-Type: application/json
```

Submit or update annotations for an instance.

**Request Body (Frontend Format):**
```json
{
  "instance_id": "item_001",
  "annotations": {
    "sentiment:positive": "1",
    "sentiment:negative": "0"
  },
  "span_annotations": [
    {
      "schema": "entities",
      "name": "PERSON",
      "title": "PERSON",
      "start": 0,
      "end": 5,
      "value": "true"
    }
  ],
  "client_timestamp": "2024-01-15T10:30:00Z"
}
```

**Request Body (Backend Format):**
```json
{
  "instance_id": "item_001",
  "schema": "sentiment",
  "type": "label",
  "state": [
    {"name": "positive", "value": "1"},
    {"name": "negative", "value": "0"}
  ]
}
```

**Response (Success):**
```json
{
  "status": "success",
  "processing_time_ms": 15,
  "performance_metrics": {
    "total_annotations": 50,
    "session_duration": 1800
  }
}
```

**Response (With Quality Control Feedback):**
```json
{
  "status": "success",
  "processing_time_ms": 12,
  "qc_result": {
    "type": "gold_standard",
    "correct": false,
    "gold_label": {"sentiment": "positive"},
    "explanation": "Strong positive language indicates positive sentiment."
  }
}
```

**Response (Attention Check Warning):**
```json
{
  "status": "success",
  "warning": true,
  "warning_message": "Please read items carefully before answering.",
  "qc_result": {
    "type": "attention_check",
    "passed": false,
    "warning": true
  }
}
```

**Response (Blocked):**
```json
{
  "status": "blocked",
  "message": "You have been blocked due to too many incorrect responses."
}
```

### Clear Span Annotations
```http
POST /api/spans/{instance_id}/clear
```

Clears all span annotations for an instance.

**Response:**
```json
{
  "status": "success",
  "cleared_count": 3
}
```

### Navigate to Instance
```http
POST /go_to
Content-Type: application/json
```

Navigate to a specific instance by ID or index.

**Request Body:**
```json
{
  "go_to": "item_005"
}
```

Or by action:
```json
{
  "action": "next_instance"
}
```

---

## Schema Information

### Get Annotation Schemas
```http
GET /api/schemas
```

Returns information about configured annotation schemas (primarily for span annotations).

**Response:**
```json
{
  "entities": {
    "name": "entities",
    "description": "Named entity recognition",
    "labels": ["PERSON", "ORGANIZATION", "LOCATION"],
    "type": "span"
  },
  "sentiment_spans": {
    "name": "sentiment_spans",
    "description": "Sentiment-bearing phrases",
    "labels": ["positive", "negative"],
    "type": "span"
  }
}
```

### Get Label Colors
```http
GET /api/colors
```

Returns the color mapping for annotation labels.

**Response:**
```json
{
  "entities": {
    "PERSON": "#ff6b6b",
    "ORGANIZATION": "#4ecdc4",
    "LOCATION": "#45b7d1"
  }
}
```

### Get Keyword Highlights
```http
GET /api/keyword_highlights/{instance_id}
```

Returns keyword highlighting patterns for an instance (if configured).

**Response:**
```json
{
  "patterns": [
    {
      "text": "excellent",
      "color": "#90EE90",
      "schema": "sentiment",
      "label": "positive"
    }
  ]
}
```

---

## Admin API Endpoints

Admin endpoints require admin privileges or API key authentication.

### Health Check
```http
GET /admin/health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "version": "2.0.0"
}
```

### Dashboard Overview
```http
GET /admin/api/overview
```

**Response:**
```json
{
  "total_items": 1000,
  "total_annotations": 5000,
  "total_users": 25,
  "active_users": 10,
  "completion_rate": 0.45,
  "items_by_status": {
    "completed": 450,
    "in_progress": 150,
    "unassigned": 400
  }
}
```

### Get Annotators
```http
GET /admin/api/annotators
```

**Response:**
```json
{
  "annotators": [
    {
      "user_id": "user1",
      "annotations_count": 200,
      "current_phase": "annotation",
      "last_active": "2024-01-15T10:30:00Z",
      "assigned_items": 250,
      "completed_items": 200
    }
  ],
  "total_count": 25
}
```

### Get Instances
```http
GET /admin/api/instances
```

**Query Parameters:**
- `status` - Filter by status (completed, in_progress, unassigned)
- `limit` - Maximum number of results (default: 100)
- `offset` - Pagination offset

**Response:**
```json
{
  "instances": [
    {
      "id": "item_001",
      "text_preview": "The quick brown fox...",
      "annotations_count": 3,
      "status": "completed"
    }
  ],
  "total_count": 1000
}
```

### Get Configuration
```http
GET /admin/api/config
```

**Response:**
```json
{
  "annotation_task_name": "Sentiment Analysis",
  "annotation_schemes": [...],
  "total_items": 1000,
  "output_format": "json"
}
```

### Update Configuration
```http
POST /admin/api/config
Content-Type: application/json
```

**Request Body:**
```json
{
  "setting_name": "value"
}
```

### Get Annotation History
```http
GET /admin/api/annotation_history
```

**Query Parameters:**
- `user_id` - Filter by user
- `instance_id` - Filter by instance
- `limit` - Maximum results

**Response:**
```json
{
  "history": [
    {
      "user_id": "user1",
      "instance_id": "item_001",
      "action_type": "add_label",
      "schema_name": "sentiment",
      "label_name": "positive",
      "timestamp": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### Get Suspicious Activity
```http
GET /admin/api/suspicious_activity
```

**Response:**
```json
{
  "suspicious_users": [
    {
      "user_id": "user5",
      "flags": ["rapid_submissions", "low_time_per_item"],
      "avg_time_per_item": 2.5,
      "annotations_count": 500
    }
  ]
}
```

### Get Crowdsourcing Data
```http
GET /admin/api/crowdsourcing
```

**Response:**
```json
{
  "summary": {
    "total_workers": 50,
    "prolific_workers": 30,
    "mturk_workers": 15,
    "other_workers": 5
  },
  "prolific": {
    "workers": [...],
    "completion_codes_issued": 28
  },
  "mturk": {
    "workers": [...],
    "hits_completed": 15
  }
}
```

---

## Quality Control API

### Get Quality Control Metrics
```http
GET /admin/api/quality_control
```

**Response:**
```json
{
  "enabled": true,
  "attention_checks": {
    "enabled": true,
    "total_items": 5,
    "total_checks": 150,
    "total_passed": 140,
    "total_failed": 10,
    "by_user": {
      "user1": {
        "passed": 10,
        "failed": 0,
        "pass_rate": 1.0
      },
      "user2": {
        "passed": 8,
        "failed": 2,
        "pass_rate": 0.8
      }
    }
  },
  "gold_standards": {
    "enabled": true,
    "total_items": 10,
    "total_evaluations": 200,
    "total_correct": 170,
    "total_incorrect": 30,
    "by_user": {
      "user1": {
        "correct": 9,
        "total": 10,
        "accuracy": 0.9
      }
    },
    "by_item": {
      "gold_001": {
        "correct": 18,
        "total": 20,
        "accuracy": 0.9
      }
    }
  },
  "auto_promotion": {
    "enabled": true,
    "min_annotators": 3,
    "agreement_threshold": 1.0,
    "promoted_count": 5,
    "promoted_items": [
      {
        "item_id": "item_042",
        "consensus_label": {"sentiment": "positive"},
        "annotator_count": 3,
        "promoted_at": "2024-01-15T10:30:00Z"
      }
    ],
    "candidates": [
      {
        "item_id": "item_055",
        "annotator_count": 2,
        "needed_annotators": 3,
        "schema_agreement": {
          "sentiment": {
            "value": "negative",
            "count": 2,
            "total": 2,
            "agreement": 1.0
          }
        }
      }
    ]
  },
  "pre_annotation": {
    "enabled": true,
    "items_with_predictions": 1000
  }
}
```

### Get Agreement Metrics
```http
GET /admin/api/agreement
```

**Response:**
```json
{
  "enabled": true,
  "overall": {
    "average_krippendorff_alpha": 0.78,
    "schemas_evaluated": 2,
    "interpretation": "Tentative agreement"
  },
  "by_schema": {
    "sentiment": {
      "krippendorff_alpha": 0.82,
      "metric_type": "nominal",
      "items_evaluated": 100,
      "total_annotations": 300,
      "interpretation": "Good agreement"
    },
    "intensity": {
      "krippendorff_alpha": 0.74,
      "metric_type": "interval",
      "items_evaluated": 100,
      "total_annotations": 300,
      "interpretation": "Tentative agreement"
    }
  },
  "warnings": []
}
```

---

## AI Assistant API

### Get AI Suggestion
```http
GET /get_ai_suggestion?instance_id={instance_id}
```

**Response:**
```json
{
  "suggestion": "Based on the text, this appears to be positive sentiment.",
  "confidence": 0.85,
  "labels": {
    "sentiment": "positive"
  }
}
```

### Get AI Assistant Help
```http
GET /api/ai_assistant?instance_id={instance_id}&schema={schema_name}
```

**Response:**
```json
{
  "html": "<div class='ai-hint'>This text expresses positive sentiment...</div>",
  "suggestions": [
    {
      "schema": "sentiment",
      "label": "positive",
      "confidence": 0.9
    }
  ]
}
```

---

## User State Endpoints (Admin)

### Get User State
```http
GET /admin/user_state/{user_id}
```

**Response:**
```json
{
  "user_id": "user1",
  "current_phase": "annotation",
  "current_instance_index": 45,
  "instance_id_ordering": ["item_001", "item_002", ...],
  "assigned_count": 100,
  "completed_count": 45,
  "annotation_history": [...]
}
```

### Get All Users
```http
GET /admin/system_state
```

**Response:**
```json
{
  "users": {
    "user1": {
      "phase": "annotation",
      "annotations": 200,
      "last_active": "2024-01-15T10:30:00Z"
    }
  },
  "items": {
    "total": 1000,
    "assigned": 800,
    "completed": 500
  }
}
```

---

## Item State Endpoints (Admin)

### Get All Items
```http
GET /admin/all_instances
```

**Response:**
```json
{
  "instances": [
    {
      "id": "item_001",
      "text": "The quick brown fox...",
      "assigned_to": ["user1", "user2"],
      "annotations_count": 2
    }
  ]
}
```

### Get Item State
```http
GET /admin/item_state/{item_id}
```

**Response:**
```json
{
  "id": "item_001",
  "text": "The quick brown fox jumps over the lazy dog.",
  "data": {
    "id": "item_001",
    "text": "The quick brown fox jumps over the lazy dog.",
    "metadata": {...}
  },
  "assigned_to": ["user1", "user2"],
  "annotations": {
    "user1": {
      "sentiment": {"positive": "1"}
    },
    "user2": {
      "sentiment": {"positive": "1"}
    }
  }
}
```

---

## Media Endpoints

### Get Audio Waveform
```http
GET /api/waveform/{cache_key}
```

Returns cached waveform data for audio annotation.

### Generate Audio Waveform
```http
POST /api/waveform/generate
Content-Type: application/json
```

**Request Body:**
```json
{
  "audio_url": "https://example.com/audio.mp3"
}
```

**Response:**
```json
{
  "cache_key": "abc123",
  "waveform_url": "/api/waveform/abc123"
}
```

### Proxy Audio
```http
GET /api/audio/proxy?url={encoded_audio_url}
```

Proxies external audio files to handle CORS issues.

### Get Video Metadata
```http
POST /api/video/metadata
Content-Type: application/json
```

**Request Body:**
```json
{
  "video_url": "https://example.com/video.mp4"
}
```

**Response:**
```json
{
  "duration": 120.5,
  "width": 1920,
  "height": 1080,
  "fps": 30
}
```

---

## Error Responses

All endpoints may return error responses in the following format:

```json
{
  "error": "Description of the error"
}
```

Common HTTP status codes:
- `400` - Bad Request (invalid parameters)
- `401` - Unauthorized (no session or invalid credentials)
- `403` - Forbidden (insufficient permissions)
- `404` - Not Found (resource doesn't exist)
- `500` - Internal Server Error

---

## Example: Complete Annotation Flow

Here's an example of a complete annotation flow using the API:

```python
import requests

BASE_URL = "http://localhost:8000"
session = requests.Session()

# 1. Login
session.post(f"{BASE_URL}/auth", data={
    "username": "annotator1",
    "password": "password123"
})

# 2. Get current instance
response = session.get(f"{BASE_URL}/api/current_instance")
instance_info = response.json()
instance_id = instance_info["instance_id"]

# 3. Get instance content
response = session.get(f"{BASE_URL}/api/spans/{instance_id}")
content = response.json()
print(f"Text: {content['text']}")

# 4. Submit annotation
response = session.post(f"{BASE_URL}/updateinstance", json={
    "instance_id": instance_id,
    "annotations": {
        "sentiment:positive": "1"
    }
})
result = response.json()
print(f"Status: {result['status']}")

# 5. Navigate to next instance
session.post(f"{BASE_URL}/go_to", json={
    "action": "next_instance"
})

# 6. Repeat steps 2-5 until done
```

---

## Example: Admin Monitoring

```python
import requests

BASE_URL = "http://localhost:8000"

# Get overview
overview = requests.get(f"{BASE_URL}/admin/api/overview").json()
print(f"Progress: {overview['completion_rate']*100:.1f}%")

# Get annotator stats
annotators = requests.get(f"{BASE_URL}/admin/api/annotators").json()
for a in annotators["annotators"]:
    print(f"{a['user_id']}: {a['completed_items']}/{a['assigned_items']}")

# Get agreement metrics
agreement = requests.get(f"{BASE_URL}/admin/api/agreement").json()
print(f"Agreement: α = {agreement['overall']['average_krippendorff_alpha']:.3f}")

# Get quality control metrics
qc = requests.get(f"{BASE_URL}/admin/api/quality_control").json()
if qc["attention_checks"]["enabled"]:
    pass_rate = qc["attention_checks"]["total_passed"] / qc["attention_checks"]["total_checks"]
    print(f"Attention check pass rate: {pass_rate*100:.1f}%")
```

---

## WebSocket Events (Future)

Currently, Potato uses polling for real-time updates. WebSocket support may be added in future versions for:
- Real-time annotation updates
- Live progress notifications
- Collaborative annotation features
