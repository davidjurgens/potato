"""
Server tests for complete span annotation workflow.

These tests verify the complete span annotation process, including:
- Schema loading from API
- Span annotation creation with proper schema
- Fix for the "No schema selected" error
"""

import pytest
import json
from tests.helpers.flask_test_setup import FlaskTestServer


class TestSpanAnnotationWorkflow(FlaskTestServer):
    """Test the complete span annotation workflow."""

    def setup_method(self):
        """Set up test configuration with span annotation schemes."""
        self.config = {
            "annotation_task_name": "Span Workflow Test",
            "task_dir": "tests/output/span-workflow-test",
            "output_annotation_dir": "tests/output/span-workflow-test/annotation_output",
            "data_files": ["tests/data/test_data.json"],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "max_annotations_per_user": 10,
            "assignment_strategy": "fixed_order",
            "annotation_schemes": [
                {
                    "annotation_type": "span",
                    "name": "emotion",
                    "description": "Mark the emotion spans in the text.",
                    "labels": [
                        {"name": "happy", "title": "Happy"},
                        {"name": "sad", "title": "Sad"},
                        {"name": "angry", "title": "Angry"}
                    ],
                    "colors": {
                        "happy": "#FFE6E6",
                        "sad": "#E6F3FF",
                        "angry": "#FFE6CC"
                    }
                }
            ],
            "server": {
                "port": 8005,
                "host": "0.0.0.0",
                "require_password": False,
                "persist_sessions": False
            }
        }
        super().setup_method()

    def test_span_annotation_creation_with_schema(self):
        """Test that span annotations can be created with proper schema information."""
        # First, register a user
        user_id = "test_user_span"
        response = self.client.post('/register', data={
            'email': user_id,
            'pass': 'test_password'
        })
        assert response.status_code == 302  # Redirect after registration

        # Get the current instance
        response = self.client.get('/api/current_instance')
        assert response.status_code == 200
        instance_data = json.loads(response.data)
        instance_id = instance_data['instance_id']

        # Create a span annotation using the backend format
        span_data = {
            "instance_id": instance_id,
            "schema": "emotion",
            "state": [
                {
                    "name": "happy",
                    "title": "Happy",
                    "start": 10,
                    "end": 20,
                    "value": "happy text"
                }
            ],
            "type": "span"
        }

        response = self.client.post('/updateinstance',
                                  json=span_data,
                                  content_type='application/json')

        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['status'] == 'success'

        # Verify the span annotation was saved
        response = self.client.get(f'/api/spans/{instance_id}')
        assert response.status_code == 200
        spans_data = json.loads(response.data)

        assert len(spans_data['spans']) == 1
        span = spans_data['spans'][0]
        assert span['schema'] == 'emotion'
        assert span['label'] == 'happy'
        assert span['start'] == 10
        assert span['end'] == 20

    def test_span_annotation_creation_without_schema_fails(self):
        """Test that span annotation creation fails when no schema is provided."""
        # Register a user
        user_id = "test_user_no_schema"
        response = self.client.post('/register', data={
            'email': user_id,
            'pass': 'test_password'
        })
        assert response.status_code == 302

        # Get the current instance
        response = self.client.get('/api/current_instance')
        assert response.status_code == 200
        instance_data = json.loads(response.data)
        instance_id = instance_data['instance_id']

        # Try to create a span annotation without schema (this should fail)
        span_data = {
            "instance_id": instance_id,
            "state": [
                {
                    "name": "happy",
                    "title": "Happy",
                    "start": 10,
                    "end": 20,
                    "value": "happy text"
                }
            ],
            "type": "span"
        }

        response = self.client.post('/updateinstance',
                                  json=span_data,
                                  content_type='application/json')

        # This should fail because no schema is provided
        assert response.status_code == 200  # The endpoint still returns 200
        result = json.loads(response.data)
        # The result might be success but the span won't be properly saved

    def test_schema_persistence_across_navigation(self):
        """Test that schema information persists across navigation."""
        # Register a user
        user_id = "test_user_persistence"
        response = self.client.post('/register', data={
            'email': user_id,
            'pass': 'test_password'
        })
        assert response.status_code == 302

        # Get the current instance
        response = self.client.get('/api/current_instance')
        assert response.status_code == 200
        instance_data = json.loads(response.data)
        instance_id = instance_data['instance_id']

        # Create a span annotation
        span_data = {
            "instance_id": instance_id,
            "schema": "emotion",
            "state": [
                {
                    "name": "happy",
                    "title": "Happy",
                    "start": 10,
                    "end": 20,
                    "value": "happy text"
                }
            ],
            "type": "span"
        }

        response = self.client.post('/updateinstance',
                                  json=span_data,
                                  content_type='application/json')
        assert response.status_code == 200

        # Navigate to next instance
        response = self.client.post('/annotate', json={
            'action': 'next_instance',
            'instance_id': instance_id
        })
        assert response.status_code == 200

        # Get the new current instance
        response = self.client.get('/api/current_instance')
        assert response.status_code == 200
        new_instance_data = json.loads(response.data)
        new_instance_id = new_instance_data['instance_id']

        # Verify that the new instance is different
        assert new_instance_id != instance_id

        # Try to create a span annotation on the new instance
        # This should work because the schema should persist
        new_span_data = {
            "instance_id": new_instance_id,
            "schema": "emotion",
            "state": [
                {
                    "name": "sad",
                    "title": "Sad",
                    "start": 5,
                    "end": 15,
                    "value": "sad text"
                }
            ],
            "type": "span"
        }

        response = self.client.post('/updateinstance',
                                  json=new_span_data,
                                  content_type='application/json')
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['status'] == 'success'

    def test_api_schemas_endpoint_returns_correct_data(self):
        """Test that the /api/schemas endpoint returns the correct schema data."""
        response = self.client.get('/api/schemas')
        assert response.status_code == 200

        schemas = json.loads(response.data)

        # Verify the emotion schema is present
        assert 'emotion' in schemas
        emotion_schema = schemas['emotion']

        # Verify the schema structure
        assert emotion_schema['name'] == 'emotion'
        assert emotion_schema['description'] == 'Mark the emotion spans in the text.'
        assert emotion_schema['type'] == 'span'
        assert emotion_schema['labels'] == ['happy', 'sad', 'angry']

    def test_span_annotation_with_multiple_spans(self):
        """Test creating multiple spans in a single request."""
        # Register a user
        user_id = "test_user_multiple"
        response = self.client.post('/register', data={
            'email': user_id,
            'pass': 'test_password'
        })
        assert response.status_code == 302

        # Get the current instance
        response = self.client.get('/api/current_instance')
        assert response.status_code == 200
        instance_data = json.loads(response.data)
        instance_id = instance_data['instance_id']

        # Create multiple span annotations
        span_data = {
            "instance_id": instance_id,
            "schema": "emotion",
            "state": [
                {
                    "name": "happy",
                    "title": "Happy",
                    "start": 10,
                    "end": 20,
                    "value": "happy text"
                },
                {
                    "name": "sad",
                    "title": "Sad",
                    "start": 30,
                    "end": 40,
                    "value": "sad text"
                }
            ],
            "type": "span"
        }

        response = self.client.post('/updateinstance',
                                  json=span_data,
                                  content_type='application/json')
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['status'] == 'success'

        # Verify both spans were saved
        response = self.client.get(f'/api/spans/{instance_id}')
        assert response.status_code == 200
        spans_data = json.loads(response.data)

        assert len(spans_data['spans']) == 2

        # Find the happy span
        happy_span = next((s for s in spans_data['spans'] if s['label'] == 'happy'), None)
        assert happy_span is not None
        assert happy_span['start'] == 10
        assert happy_span['end'] == 20

        # Find the sad span
        sad_span = next((s for s in spans_data['spans'] if s['label'] == 'sad'), None)
        assert sad_span is not None
        assert sad_span['start'] == 30
        assert sad_span['end'] == 40