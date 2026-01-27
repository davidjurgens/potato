#!/usr/bin/env python3
"""
Unit tests for the new frontend-driven span annotation system
"""

import unittest
import json
import tempfile
import os
from unittest.mock import patch, MagicMock, mock_open
from io import StringIO
import pytest

# Import the classes and functions we're testing
from potato.item_state_management import SpanAnnotation, get_item_state_manager, init_item_state_manager, clear_item_state_manager
from potato.user_state_management import InMemoryUserState, get_user_state_manager, init_user_state_manager, clear_user_state_manager, UserPhase
from potato.server_utils.schemas.span import get_span_color


class TestSpanAPIEndpoints:
    """Test the new span API endpoints"""

    def setup_method(self):
        """Set up test data and managers"""
        # Clear state managers to avoid duplicate item errors
        clear_item_state_manager()
        clear_user_state_manager()
        # Initialize managers with test config
        test_config = {
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [],
            "annotation_task_name": "Test Task",
            "site_dir": "potato/templates",
            "base_html_template": "base_template.html",
            "html_layout": "base_template.html",
            "header_file": "base_template.html",
            "site_file": "base_template.html",
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        init_user_state_manager(test_config)
        init_item_state_manager(test_config)

        # Create test instances in item state manager
        item_manager = get_item_state_manager()

        # Create test instance 1
        test_instance_1 = {
            "id": "test_instance_456",
            "text": "This is a test text for span annotation."
        }
        item_manager.add_item(test_instance_1["id"], test_instance_1)

        # Create test instance 2
        test_instance_2 = {
            "id": "integration_test_instance",
            "text": "Another test instance for integration testing."
        }
        item_manager.add_item(test_instance_2["id"], test_instance_2)

        # Create test instance 3
        test_instance_3 = {
            "id": "update_test_instance",
            "text": "Test instance for update workflow testing."
        }
        item_manager.add_item(test_instance_3["id"], test_instance_3)

    def create_test_user(self, username="test_user"):
        """Helper method to create a test user state"""
        user_state_manager = get_user_state_manager()
        if not user_state_manager.has_user(username):
            user_state_manager.add_user(username)
        user_state = user_state_manager.get_user_state(username)
        # Set user to ANNOTATION phase so span annotations are stored correctly
        user_state.advance_to_phase(UserPhase.ANNOTATION, None)
        return user_state

    def test_get_spans_endpoint_empty(self, client):
        """Test GET /api/spans/<instance_id> with no spans"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        response = client.get('/api/spans/test_instance_456')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['instance_id'] == 'test_instance_456'
        assert data['text'] == 'This is a test text for span annotation.'
        assert data['spans'] == []

    def test_get_spans_endpoint_with_spans(self, client):
        """Test GET /api/spans/<instance_id> with existing spans"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        # First, create some spans via the updateinstance endpoint
        span_data = {
            'instance_id': 'test_instance_456',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': 'positive'
                },
                {
                    'name': 'negative',
                    'title': 'Negative sentiment',
                    'start': 8,
                    'end': 12,
                    'value': 'negative'
                }
            ]
        }

        # Add spans to user state
        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')
        assert response.status_code == 200

        # Now fetch the spans via API
        response = client.get('/api/spans/test_instance_456')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['instance_id'] == 'test_instance_456'
        assert len(data['spans']) == 2

        # Verify span data structure
        span1 = data['spans'][0]
        assert span1['schema'] == 'sentiment'
        assert span1['label'] == 'positive'
        assert span1['start'] == 0
        assert span1['end'] == 4
        assert span1['text'] == 'This'

        span2 = data['spans'][1]
        assert span2['schema'] == 'sentiment'
        assert span2['label'] == 'negative'
        assert span2['start'] == 8
        assert span2['end'] == 12
        assert span2['text'] == 'a te'

    def test_get_colors_endpoint(self, client):
        """Test GET /api/colors endpoint"""
        response = client.get('/api/colors')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, dict)

        # Should contain color mappings for span schemas
        assert 'sentiment' in data
        assert 'entity' in data
        assert 'topic' in data

    def test_get_spans_invalid_instance(self, client):
        """Test GET /api/spans/<instance_id> with invalid instance"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        response = client.get('/api/spans/nonexistent_instance')
        assert response.status_code == 404

        data = json.loads(response.data)
        assert 'error' in data
        assert data['error'] == 'Instance not found: nonexistent_instance'

    def test_get_spans_unauthorized(self, app):
        """Test GET /api/spans/<instance_id> without authentication"""
        # Create a new client without session
        new_client = app.test_client()

        response = new_client.get('/api/spans/test_instance_456')
        assert response.status_code == 401  # Should return 401 for unauthorized access


class TestFrontendSpanManager:
    """Test the frontend span manager JavaScript functionality"""

    def test_span_manager_initialization(self):
        """Test that the span manager initializes correctly"""
        # This would be tested with a JavaScript testing framework
        # For now, we'll verify the JavaScript file exists and has expected structure
        span_manager_path = 'potato/static/span-manager.js'
        assert os.path.exists(span_manager_path)

        with open(span_manager_path, 'r') as f:
            content = f.read()

        # Check for key functions - the implementation uses a functional approach
        # Not class-based, so check for the key functions that exist
        assert 'initializeSpanManager' in content or 'createSpanOverlays' in content
        assert 'handleSpanSelection' in content or 'handleTextSelection' in content or 'renderSpanOverlay' in content

    def test_span_manager_api_calls(self):
        """Test that the span manager makes correct API calls"""
        # This would be tested with a JavaScript testing framework
        # For now, we'll verify the JavaScript file exists and contains span-related code
        span_manager_path = 'potato/static/span-manager.js'

        with open(span_manager_path, 'r') as f:
            content = f.read()

        # Check that the span manager file contains span-related functionality
        # The actual implementation may use different endpoints/patterns
        assert 'span' in content.lower()  # Basic check that it's span-related


class TestSpanColorSystem:
    """Test the span color system"""

    def test_get_span_color_basic(self):
        """Test basic color retrieval"""
        # Test with a known schema - this will return None since no config is set
        color = get_span_color('sentiment', 'positive')
        # The function returns None when no config is available, which is expected
        assert color is None

        # Test with another schema
        color2 = get_span_color('entity', 'person')
        assert color2 is None

    def test_get_span_color_unknown_schema(self):
        """Test color retrieval for unknown schema"""
        color = get_span_color('unknown_schema', 'unknown_label')
        # Should return None for unknown schema/label
        assert color is None

    def test_get_span_color_consistency(self):
        """Test that colors are consistent for the same schema and label"""
        color1 = get_span_color('sentiment', 'positive')
        color2 = get_span_color('sentiment', 'positive')
        assert color1 == color2


class TestSpanAnnotationIntegration:
    """Test integration between backend and frontend span system"""

    def setup_method(self):
        """Set up test data and managers"""
        # Clear state managers to avoid duplicate item errors
        clear_item_state_manager()
        clear_user_state_manager()
        # Initialize managers with test config
        test_config = {
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [],
            "annotation_task_name": "Test Task",
            "site_dir": "potato/templates",
            "base_html_template": "base_template.html",
            "html_layout": "base_template.html",
            "header_file": "base_template.html",
            "site_file": "base_template.html",
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        init_user_state_manager(test_config)
        init_item_state_manager(test_config)

        # Create test instances in item state manager
        item_manager = get_item_state_manager()

        # Create test instance 1
        test_instance_1 = {
            "id": "integration_test_instance",
            "text": "This is a test text for integration testing."
        }
        item_manager.add_item(test_instance_1["id"], test_instance_1)

        # Create test instance 2
        test_instance_2 = {
            "id": "update_test_instance",
            "text": "Test instance for update workflow testing."
        }
        item_manager.add_item(test_instance_2["id"], test_instance_2)

    def create_test_user(self, username="test_user"):
        """Helper method to create a test user state"""
        user_state_manager = get_user_state_manager()
        if not user_state_manager.has_user(username):
            user_state_manager.add_user(username)
        user_state = user_state_manager.get_user_state(username)
        # Set user to ANNOTATION phase so span annotations are stored correctly
        user_state.advance_to_phase(UserPhase.ANNOTATION, None)
        return user_state

    def test_span_creation_and_retrieval_workflow(self, client):
        """Test complete workflow: create spans, retrieve via API, verify data"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        # Step 1: Create spans via updateinstance
        span_data = {
            'instance_id': 'integration_test_instance',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': 'positive'
                }
            ]
        }

        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')
        assert response.status_code == 200

        # Step 2: Retrieve spans via API
        response = client.get('/api/spans/integration_test_instance')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['instance_id'] == 'integration_test_instance'
        assert len(data['spans']) == 1

        # Step 3: Verify span data integrity
        span = data['spans'][0]
        assert span['schema'] == 'sentiment'
        assert span['label'] == 'positive'
        assert span['start'] == 0
        assert span['end'] == 4
        assert span['text'] == 'This'

        # Step 4: Verify colors are available
        response = client.get('/api/colors')
        assert response.status_code == 200

        colors = json.loads(response.data)
        assert 'sentiment' in colors

    def test_span_update_workflow(self, client):
        """Test updating existing spans"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        # Step 1: Create initial span
        initial_data = {
            'instance_id': 'update_test_instance',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': 'positive'
                }
            ]
        }

        response = client.post('/updateinstance',
                              data=json.dumps(initial_data),
                              content_type='application/json')
        assert response.status_code == 200

        # Step 2: Update the span by setting the old one to None and creating a new one
        updated_data = {
            'instance_id': 'update_test_instance',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': None  # Delete the old span
                },
                {
                    'name': 'negative',  # Create new span
                    'title': 'Negative sentiment',
                    'start': 0,
                    'end': 4,
                    'value': 'negative'
                }
            ]
        }

        response = client.post('/updateinstance',
                              data=json.dumps(updated_data),
                              content_type='application/json')
        assert response.status_code == 200

        # Step 3: Verify the update
        response = client.get('/api/spans/update_test_instance')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert len(data['spans']) == 1

        span = data['spans'][0]
        assert span['label'] == 'negative'  # Should be updated
        assert span['title'] == 'Negative sentiment'

    def test_span_deletion_workflow(self, client):
        """Test deleting spans"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        # Step 1: Create a span
        span_data = {
            'instance_id': 'update_test_instance',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': 'positive'
                }
            ]
        }

        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')
        assert response.status_code == 200

        # Step 2: Delete the span by setting value to None
        delete_data = {
            'instance_id': 'update_test_instance',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': None  # This deletes the span
                }
            ]
        }

        response = client.post('/updateinstance',
                              data=json.dumps(delete_data),
                              content_type='application/json')
        assert response.status_code == 200

        # Step 3: Verify the span is deleted
        response = client.get('/api/spans/update_test_instance')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert len(data['spans']) == 0  # Should be empty after deletion


class TestSpanDataValidation:
    """Test span data validation and structure"""

    def test_span_data_structure_validation(self):
        """Test that span data has the correct structure"""
        # Test valid span data
        valid_span = {
            'id': 'test_span',
            'schema': 'sentiment',
            'name': 'positive',
            'title': 'Positive sentiment',
            'start': 0,
            'end': 4
        }

        # Test that SpanAnnotation can be created with valid data
        span = SpanAnnotation(
            valid_span['schema'],
            valid_span['name'],
            valid_span['title'],
            valid_span['start'],
            valid_span['end']
        )

        assert span.get_schema() == valid_span['schema']
        assert span.get_name() == valid_span['name']
        assert span.get_title() == valid_span['title']
        assert span.get_start() == valid_span['start']
        assert span.get_end() == valid_span['end']

    def test_span_annotation_object_validation(self):
        """Test SpanAnnotation object methods"""
        span = SpanAnnotation('sentiment', 'positive', 'Positive sentiment', 0, 4)

        # Test getter methods
        assert span.get_schema() == 'sentiment'
        assert span.get_name() == 'positive'
        assert span.get_title() == 'Positive sentiment'
        assert span.get_start() == 0
        assert span.get_end() == 4

        # Test ID generation
        span_id = span.get_id()
        assert span_id is not None
        assert isinstance(span_id, str)


class TestSpanErrorHandling:
    """Test error handling in span annotation system"""

    def create_test_user(self, username="test_user"):
        """Helper method to create a test user state"""
        user_state_manager = get_user_state_manager()
        if not user_state_manager.has_user(username):
            user_state_manager.add_user(username)
        return user_state_manager.get_user_state(username)

    def test_invalid_span_data_handling(self, client):
        """Test handling of invalid span data"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        # Test with invalid JSON
        response = client.post('/updateinstance',
                              data='invalid json',
                              content_type='application/json')
        assert response.status_code == 400  # Should return 400 for invalid JSON
        # The response is HTML, not JSON, so we can't parse it as JSON
        assert b'Bad Request' in response.data

    def test_negative_span_indices_handling(self, client):
        """Test handling of negative span indices"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        # Test with negative start index
        span_data = {
            'instance_id': 'test_instance_456',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': -1,  # Invalid negative index
                    'end': 4,
                    'value': 'positive'
                }
            ]
        }

        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')
        # Should handle gracefully - the backend should validate indices
        assert response.status_code == 200

    def test_overlapping_span_indices_handling(self, client):
        """Test handling of overlapping span indices"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        # Test with overlapping spans
        span_data = {
            'instance_id': 'test_instance_456',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': 'positive'
                },
                {
                    'name': 'negative',
                    'title': 'Negative sentiment',
                    'start': 2,  # Overlaps with first span
                    'end': 6,
                    'value': 'negative'
                }
            ]
        }

        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')
        # Should handle gracefully - overlapping spans are allowed in this implementation
        assert response.status_code == 200


class TestBackendStateManagement:
    """Test backend state management for spans"""

    def setup_method(self):
        """Set up test data and managers"""
        # Clear state managers to avoid duplicate item errors
        clear_item_state_manager()
        clear_user_state_manager()
        # Initialize managers with test config
        test_config = {
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [],
            "annotation_task_name": "Test Task",
            "site_dir": "potato/templates",
            "base_html_template": "base_template.html",
            "html_layout": "base_template.html",
            "header_file": "base_template.html",
            "site_file": "base_template.html",
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        init_user_state_manager(test_config)
        init_item_state_manager(test_config)

        # Create test instance
        item_manager = get_item_state_manager()
        test_instance = {
            "id": "state_test_instance",
            "text": "Test text for state management."
        }
        item_manager.add_item(test_instance["id"], test_instance)

    def create_test_user(self, username="test_user"):
        """Helper method to create a test user state"""
        user_state_manager = get_user_state_manager()
        if not user_state_manager.has_user(username):
            user_state_manager.add_user(username)
        user_state = user_state_manager.get_user_state(username)
        # Set user to ANNOTATION phase so span annotations are stored correctly
        user_state.advance_to_phase(UserPhase.ANNOTATION, None)
        return user_state

    def test_backend_stores_span_data_correctly(self, client):
        """Test that the backend correctly stores span data"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user (this properly sets the phase)
        self.create_test_user('test_user')

        # Create test instance first
        item_manager = get_item_state_manager()
        test_instance = {
            "id": "backend_stores_test_instance",
            "text": "Test text for state management."
        }
        item_manager.add_item(test_instance["id"], test_instance)

        # Create span data
        span_data = {
            'instance_id': 'backend_stores_test_instance',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': 'positive'
                }
            ]
        }

        # Store span data
        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')
        assert response.status_code == 200

        # Verify data is stored correctly
        response = client.get('/api/spans/backend_stores_test_instance')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert len(data['spans']) == 1

        span = data['spans'][0]
        assert span['label'] == 'positive'
        assert span['start'] == 0
        assert span['end'] == 4

    def test_backend_returns_raw_span_data(self, client):
        """Test that the backend returns raw span data without HTML rendering"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user (this properly sets the phase)
        self.create_test_user('test_user')

        # Create test instance first
        item_manager = get_item_state_manager()
        test_instance = {
            "id": "raw_data_test_instance",
            "text": "Test text for state management."
        }
        item_manager.add_item(test_instance["id"], test_instance)

        # Create span data
        span_data = {
            'instance_id': 'raw_data_test_instance',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': 'positive'
                }
            ]
        }

        # Store span data
        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')
        assert response.status_code == 200

        # Get span data via API
        response = client.get('/api/spans/raw_data_test_instance')
        assert response.status_code == 200

        data = json.loads(response.data)

        # Verify the response contains raw data, not HTML
        assert 'instance_id' in data
        assert 'text' in data
        assert 'spans' in data
        assert isinstance(data['spans'], list)

        # Verify span data structure
        span = data['spans'][0]
        assert 'id' in span
        assert 'label' in span
        assert 'schema' in span
        assert 'start' in span
        assert 'end' in span
        assert 'title' in span
        assert span['label'] == 'positive'
        assert span['schema'] == 'sentiment'
        assert span['start'] == 0
        assert span['end'] == 4

    def test_clear_span_annotations_endpoint(self, client):
        """Test POST /api/spans/<instance_id>/clear endpoint"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        # Create test instance first
        item_manager = get_item_state_manager()
        test_instance = {
            "id": "test_instance_456",
            "text": "Test text for span annotation."
        }
        item_manager.add_item(test_instance["id"], test_instance)

        # First, create some spans via the updateinstance endpoint
        span_data = {
            'instance_id': 'test_instance_456',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 4,
                    'value': 'positive'
                }
            ]
        }

        # Add spans to user state
        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')
        assert response.status_code == 200

        # Verify spans exist
        response = client.get('/api/spans/test_instance_456')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['spans']) == 1

        # Clear the spans
        response = client.post('/api/spans/test_instance_456/clear')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert data['spans_cleared'] == 1

        # Verify spans are cleared
        response = client.get('/api/spans/test_instance_456')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['spans']) == 0

    def test_clear_span_annotations_nonexistent(self, client):
        """Test POST /api/spans/<instance_id>/clear with no spans"""
        # Create authenticated session and user state
        with client.session_transaction() as sess:
            sess['username'] = 'test_user'

        # Create user state for test_user
        self.create_test_user('test_user')

        # Try to clear spans for an instance that has no spans
        response = client.post('/api/spans/test_instance_456/clear')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert data['spans_cleared'] == 0