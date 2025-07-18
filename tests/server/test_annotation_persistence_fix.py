"""
Test to verify the annotation persistence fix.

This test verifies that the /updateinstance endpoint now correctly handles
both frontend and backend data formats.
"""

import json
import pytest
from tests.helpers.flask_test_setup import FlaskTestServer


class TestAnnotationPersistenceFix:
    """Test to verify the annotation persistence fix works correctly."""

    def test_frontend_format_now_works(self):
        """Test that the frontend format now correctly saves annotations."""

        config = {
            "annotation_task_name": "Test Annotation Task",
            "annotation_schemas": {
                "sentiment": {
                    "type": "radio",
                    "options": ["positive", "negative", "neutral"]
                },
                "confidence": {
                    "type": "likert",
                    "options": ["1", "2", "3", "4", "5"]
                }
            },
            "data": [
                {"id": "item_1", "text": "This is a test item."},
                {"id": "item_2", "text": "This is another test item."}
            ]
        }

        server = FlaskTestServer(config=config)
        try:
            server.start()

            # Register a test user
            username = "test_user"
            server.register_user(username)

            # Get user state to verify it's empty initially
            user_state = server.get_user_state(username)
            assert len(user_state.get_all_annotations()) == 0

            # Test the frontend format (which should now work)
            frontend_data = {
                "instance_id": "item_1",
                "annotations": {
                    "sentiment:positive": "true",
                    "confidence:3": "true"
                },
                "span_annotations": []
            }

            # Send the frontend format to /updateinstance
            response = server.post(
                "/updateinstance",
                json=frontend_data,
                headers={"Content-Type": "application/json"}
            )

            # The request should succeed
            assert response.status_code == 200
            result = json.loads(response.text)
            assert result["status"] == "success"

            # The annotations should NOW be saved with the fix
            user_state = server.get_user_state(username)
            all_annotations = user_state.get_all_annotations()

            # This should now work with the fix
            assert len(all_annotations) > 0, "Annotations should now be saved with frontend format"
            assert "item_1" in all_annotations

            # Verify the specific annotations were saved
            item_annotations = all_annotations["item_1"]
            assert len(item_annotations) > 0

        finally:
            server.stop()

    def test_backend_format_still_works(self):
        """Test that the backend format still works correctly."""

        config = {
            "annotation_task_name": "Test Task",
            "annotation_schemas": {
                "test_schema": {
                    "type": "radio",
                    "options": ["option1", "option2"]
                }
            },
            "data": [{"id": "item_1", "text": "Test"}]
        }

        server = FlaskTestServer(config=config)
        try:
            server.start()
            username = "test_user"
            server.register_user(username)

            # Test the backend format (should still work)
            backend_data = {
                "instance_id": "item_1",
                "schema": "test_schema",
                "state": [
                    {"name": "option1", "value": "true"},
                    {"name": "option2", "value": None}
                ],
                "type": "label"
            }

            response = server.post(
                "/updateinstance",
                json=backend_data,
                headers={"Content-Type": "application/json"}
            )

            assert response.status_code == 200
            result = json.loads(response.text)
            assert result["status"] == "success"

            # Verify annotation was saved
            user_state = server.get_user_state(username)
            all_annotations = user_state.get_all_annotations()
            assert "item_1" in all_annotations

        finally:
            server.stop()

    def test_span_annotations_frontend_format(self):
        """Test that span annotations work with the frontend format."""

        config = {
            "annotation_task_name": "Test Task",
            "annotation_schemas": {
                "spans": {
                    "type": "span",
                    "options": ["positive", "negative"]
                }
            },
            "data": [{"id": "item_1", "text": "This is a test sentence."}]
        }

        server = FlaskTestServer(config=config)
        try:
            server.start()
            username = "test_user"
            server.register_user(username)

            # Test span annotations with frontend format
            frontend_span_data = {
                "instance_id": "item_1",
                "annotations": {},
                "span_annotations": [
                    {
                        "schema": "spans",
                        "name": "positive",
                        "title": "positive",
                        "start": 0,
                        "end": 4,
                        "value": "positive"
                    }
                ]
            }

            response = server.post(
                "/updateinstance",
                json=frontend_span_data,
                headers={"Content-Type": "application/json"}
            )

            assert response.status_code == 200
            result = json.loads(response.text)
            assert result["status"] == "success"

            # Verify span annotation was saved
            user_state = server.get_user_state(username)
            span_annotations = user_state.get_span_annotations("item_1")
            assert len(span_annotations) > 0

        finally:
            server.stop()

    def test_mixed_annotations_frontend_format(self):
        """Test that both label and span annotations work together in frontend format."""

        config = {
            "annotation_task_name": "Test Task",
            "annotation_schemas": {
                "sentiment": {
                    "type": "radio",
                    "options": ["positive", "negative"]
                },
                "spans": {
                    "type": "span",
                    "options": ["highlight", "underline"]
                }
            },
            "data": [{"id": "item_1", "text": "This is a test sentence."}]
        }

        server = FlaskTestServer(config=config)
        try:
            server.start()
            username = "test_user"
            server.register_user(username)

            # Test mixed annotations with frontend format
            mixed_data = {
                "instance_id": "item_1",
                "annotations": {
                    "sentiment:positive": "true"
                },
                "span_annotations": [
                    {
                        "schema": "spans",
                        "name": "highlight",
                        "title": "highlight",
                        "start": 0,
                        "end": 4,
                        "value": "highlight"
                    }
                ]
            }

            response = server.post(
                "/updateinstance",
                json=mixed_data,
                headers={"Content-Type": "application/json"}
            )

            assert response.status_code == 200
            result = json.loads(response.text)
            assert result["status"] == "success"

            # Verify both types of annotations were saved
            user_state = server.get_user_state(username)
            all_annotations = user_state.get_all_annotations()
            span_annotations = user_state.get_span_annotations("item_1")

            assert "item_1" in all_annotations
            assert len(span_annotations) > 0

        finally:
            server.stop()