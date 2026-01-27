"""
Server tests for span schema API endpoint.

These tests verify that the /api/schemas endpoint returns the correct
schema information for span annotations.
"""

import pytest
import json
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestSpanSchemaAPI:
    """Test the /api/schemas endpoint for span annotation schemas."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with span annotation schemas."""
        test_dir = create_test_directory("span_schema_api_test")

        # Create test data
        test_data = [
            {"id": "span_test_item_01", "text": "This is a happy text with some sad moments."},
            {"id": "span_test_item_02", "text": "This text shows angry emotions and high intensity."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create annotation schemes with multiple span types
        annotation_schemes = [
            {
                "annotation_type": "span",
                "name": "emotion",
                "description": "Mark the emotion spans in the text.",
                "labels": ["happy", "sad", "angry"],
                "color_scheme": {
                    "happy": "#FFE6E6",
                    "sad": "#E6F3FF",
                    "angry": "#FFE6CC"
                }
            },
            {
                "annotation_type": "span",
                "name": "intensity",
                "description": "Mark the intensity of emotions.",
                "labels": ["low", "medium", "high"]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Span Schema Test",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_api_schemas_endpoint(self):
        """Test that /api/schemas returns the correct schema information."""
        response = self.server.get('/api/schemas')
        assert response.status_code == 200

        schemas = response.json()

        # Verify that both schemas are present
        assert 'emotion' in schemas
        assert 'intensity' in schemas

        # Verify the emotion schema structure
        emotion_schema = schemas['emotion']
        assert emotion_schema['name'] == 'emotion'
        assert emotion_schema['description'] == 'Mark the emotion spans in the text.'
        assert emotion_schema['type'] == 'span'
        assert emotion_schema['labels'] == ['happy', 'sad', 'angry']

        # Verify the intensity schema structure
        intensity_schema = schemas['intensity']
        assert intensity_schema['name'] == 'intensity'
        assert intensity_schema['description'] == 'Mark the intensity of emotions.'
        assert intensity_schema['type'] == 'span'
        assert intensity_schema['labels'] == ['low', 'medium', 'high']


class TestSpanSchemaAPINoSpan:
    """Test /api/schemas when no span schemas exist."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with no span schemas."""
        test_dir = create_test_directory("no_span_schema_test")

        test_data = [{"id": "no_span_test_01", "text": "Test text for no span config."}]
        data_file = create_test_data_file(test_dir, test_data)

        # Create annotation schemes with only radio type (no spans)
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment?",
                "labels": ["positive", "negative", "neutral"]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="No Span Test",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_api_schemas_no_span_schemas(self):
        """Test that /api/schemas returns schemas even when no span schemas exist."""
        response = self.server.get('/api/schemas')
        assert response.status_code == 200

        schemas = response.json()
        # API returns all schema types, including non-span
        assert 'sentiment' in schemas
        assert schemas['sentiment']['type'] == 'radio'


class TestSpanSchemaAPIMixed:
    """Test /api/schemas with mixed annotation types."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with mixed annotation types."""
        test_dir = create_test_directory("mixed_schema_test")

        test_data = [{"id": "mixed_test_01", "text": "Test text for mixed config."}]
        data_file = create_test_data_file(test_dir, test_data)

        # Create annotation schemes with both span and non-span types
        annotation_schemes = [
            {
                "annotation_type": "span",
                "name": "emotion",
                "description": "Mark the emotion spans in the text.",
                "labels": ["happy", "sad"]
            },
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment?",
                "labels": ["positive", "negative", "neutral"]
            },
            {
                "annotation_type": "span",
                "name": "intensity",
                "description": "Mark the intensity.",
                "labels": ["low", "high"]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Mixed Types Test",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_api_schemas_with_mixed_annotation_types(self):
        """Test that /api/schemas returns all schema types when mixed types exist."""
        response = self.server.get('/api/schemas')
        assert response.status_code == 200

        schemas = response.json()

        # All schema types should be present
        assert 'emotion' in schemas
        assert 'intensity' in schemas
        assert 'sentiment' in schemas

        # Verify schema types are correct
        assert schemas['emotion']['type'] == 'span'
        assert schemas['intensity']['type'] == 'span'
        assert schemas['sentiment']['type'] == 'radio'
