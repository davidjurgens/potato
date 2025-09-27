"""
Server tests for span schema API endpoint.

These tests verify that the /api/schemas endpoint returns the correct
schema information for span annotations.
"""

import pytest
import json
import os
import yaml
import time
from tests.helpers.flask_test_setup import FlaskTestServer


class TestSpanSchemaAPI:
    """Test the /api/schemas endpoint for span annotation schemas."""

    def test_api_schemas_endpoint(self):
        """Test that /api/schemas returns the correct schema information."""
        # Create a temporary directory for this test within the tests directory
        test_dir = os.path.join(os.path.dirname(__file__), 'output', 'span_schema_test')
        os.makedirs(test_dir, exist_ok=True)

        # Create test data file
        test_data = [
            {
                "id": "span_test_item_01",
                "text": "This is a happy text with some sad moments.",
                "displayed_text": "Span Test Item 1"
            },
            {
                "id": "span_test_item_02",
                "text": "This text shows angry emotions and high intensity.",
                "displayed_text": "Span Test Item 2"
            }
        ]

        data_file = os.path.join(test_dir, 'span_test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config with span annotation schemes
        config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": 3,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Span Schema Test",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": [os.path.basename(data_file)],
            "item_properties": {
                "text_key": "text",
                "id_key": "id"
            },
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
                },
                {
                    "annotation_type": "span",
                    "name": "intensity",
                    "description": "Mark the intensity of emotions.",
                    "labels": [
                        {"name": "low", "title": "Low"},
                        {"name": "medium", "title": "Medium"},
                        {"name": "high", "title": "High"}
                    ]
                }
            ],
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": test_dir,
            "site_dir": os.path.join(test_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Write config file
        config_file = os.path.join(test_dir, 'span_schema_test_config.yaml')
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create FlaskTestServer with the config file
        server = FlaskTestServer(
            port=8001,
            debug=False,
            config_file=config_file,
            test_data_file=data_file
        )

        # Start server
        if not server.start_server(test_dir):
            pytest.fail("Failed to start Flask test server")

        try:
            # Make a request to the /api/schemas endpoint
            response = server.get('/api/schemas')

            # Verify the response
            assert response.status_code == 200

            # Parse the JSON response
            schemas = json.loads(response.text)

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
        finally:
            # Cleanup
            server.stop_server()
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_api_schemas_with_legacy_config_format(self):
        """Test that /api/schemas works with legacy config format."""
        # Create a temporary directory for legacy test within the tests directory
        test_dir = os.path.join(os.path.dirname(__file__), 'output', 'legacy_schema_test')
        os.makedirs(test_dir, exist_ok=True)

        # Create test data file
        test_data = [
            {
                "id": "legacy_test_item_01",
                "text": "This is a test text for legacy config.",
                "displayed_text": "Legacy Test Item 1"
            }
        ]

        data_file = os.path.join(test_dir, 'legacy_test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config with legacy annotation_scheme format
        legacy_config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": 3,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Legacy Schema Test",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": [os.path.basename(data_file)],
            "item_properties": {
                "text_key": "text",
                "id_key": "id"
            },
            "annotation_scheme": {
                "emotion": {
                    "type": "span",
                    "name": "emotion",
                    "description": "Mark the emotion spans in the text.",
                    "labels": [
                        {"name": "happy", "title": "Happy"},
                        {"name": "sad", "title": "Sad"}
                    ]
                }
            },
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": test_dir,
            "site_dir": os.path.join(test_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Write config file
        config_file = os.path.join(test_dir, 'legacy_schema_test_config.yaml')
        with open(config_file, 'w') as f:
            yaml.dump(legacy_config, f)

        # Create a new server with legacy config
        legacy_server = FlaskTestServer(
            port=8002,
            debug=False,
            config_file=config_file,
            test_data_file=data_file
        )

        # Start server and wait for it to be ready
        if not legacy_server.start_server(test_dir):
            pytest.fail("Failed to start Flask test server")

        # Wait a moment for server to be ready
        time.sleep(2)

        try:
            response = legacy_server.get('/api/schemas')
            assert response.status_code == 200

            schemas = json.loads(response.text)
            assert 'emotion' in schemas
            assert schemas['emotion']['labels'] == ['happy', 'sad']
        finally:
            legacy_server.stop_server()
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_api_schemas_no_span_schemas(self):
        """Test that /api/schemas returns empty when no span schemas exist."""
        # Create a temporary directory for no-span test within the tests directory
        test_dir = os.path.join(os.path.dirname(__file__), 'output', 'no_span_test')
        os.makedirs(test_dir, exist_ok=True)

        # Create test data file
        test_data = [
            {
                "id": "no_span_test_item_01",
                "text": "This is a test text for no span config.",
                "displayed_text": "No Span Test Item 1"
            }
        ]

        data_file = os.path.join(test_dir, 'no_span_test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create a config with no span annotation schemes
        no_span_config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": 3,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "No Span Test",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": [os.path.basename(data_file)],
            "item_properties": {
                "text_key": "text",
                "id_key": "id"
            },
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "What is the sentiment?",
                    "labels": ["positive", "negative", "neutral"]
                }
            ],
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": test_dir,
            "site_dir": os.path.join(test_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Write config file
        config_file = os.path.join(test_dir, 'no_span_test_config.yaml')
        with open(config_file, 'w') as f:
            yaml.dump(no_span_config, f)

        # Create a new server with no span config
        no_span_server = FlaskTestServer(
            port=8003,
            debug=False,
            config_file=config_file,
            test_data_file=data_file
        )

        # Start server and wait for it to be ready
        if not no_span_server.start_server(test_dir):
            pytest.fail("Failed to start Flask test server")

        # Wait a moment for server to be ready
        time.sleep(2)

        try:
            response = no_span_server.get('/api/schemas')
            assert response.status_code == 200

            schemas = json.loads(response.text)
            assert schemas == {}  # Should be empty when no span schemas exist
        finally:
            no_span_server.stop_server()
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_api_schemas_with_mixed_annotation_types(self):
        """Test that /api/schemas only returns span schemas when mixed types exist."""
        # Create a temporary directory for mixed test within the tests directory
        test_dir = os.path.join(os.path.dirname(__file__), 'output', 'mixed_types_test')
        os.makedirs(test_dir, exist_ok=True)

        # Create test data file
        test_data = [
            {
                "id": "mixed_test_item_01",
                "text": "This is a test text for mixed config.",
                "displayed_text": "Mixed Test Item 1"
            }
        ]

        data_file = os.path.join(test_dir, 'mixed_test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create a config with both span and non-span annotation schemes
        mixed_config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": 3,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Mixed Types Test",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": [os.path.basename(data_file)],
            "item_properties": {
                "text_key": "text",
                "id_key": "id"
            },
            "annotation_schemes": [
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
            ],
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": test_dir,
            "site_dir": os.path.join(test_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Write config file
        config_file = os.path.join(test_dir, 'mixed_types_test_config.yaml')
        with open(config_file, 'w') as f:
            yaml.dump(mixed_config, f)

        # Create a new server with mixed config
        mixed_server = FlaskTestServer(
            port=8004,
            debug=False,
            config_file=config_file,
            test_data_file=data_file
        )

        # Start server and wait for it to be ready
        if not mixed_server.start_server(test_dir):
            pytest.fail("Failed to start Flask test server")

        # Wait a moment for server to be ready
        time.sleep(2)

        try:
            response = mixed_server.get('/api/schemas')
            assert response.status_code == 200

            schemas = json.loads(response.text)

            # Should only contain span schemas
            assert 'emotion' in schemas
            assert 'intensity' in schemas
            assert 'sentiment' not in schemas  # Radio button schema should not be included

            # Verify span schemas have correct structure
            assert schemas['emotion']['type'] == 'span'
            assert schemas['intensity']['type'] == 'span'
        finally:
            mixed_server.stop_server()
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)