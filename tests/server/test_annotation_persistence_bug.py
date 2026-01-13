"""
Test to reproduce the annotation persistence bug.

The bug is that the frontend sends data in a different format than what the
/updateinstance endpoint expects, causing annotations to not be saved.
"""

import json
import pytest

# Skip server integration tests for fast CI - run with pytest -m slow
pytestmark = pytest.mark.skip(reason="Server integration tests skipped for fast CI execution")
from tests.helpers.flask_test_setup import FlaskTestServer


class TestAnnotationPersistenceBug:
    """Test to reproduce and verify the annotation persistence bug."""

    def test_frontend_backend_format_mismatch(self):
        """Test that the frontend format doesn't match backend expectations."""

        # Test config with multiple annotation types
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

            # Simulate what the frontend sends (WRONG FORMAT)
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

            # The request should succeed (no error)
            assert response.status_code == 200
            result = json.loads(response.text)
            assert result["status"] == "success"

            # BUT the annotations should NOT be saved due to format mismatch
            user_state = server.get_user_state(username)
            all_annotations = user_state.get_all_annotations()

            # This is the bug: annotations are not saved because the backend
            # expects different field names
            assert len(all_annotations) == 0, "Annotations should not be saved due to format mismatch"

            # Now test with the CORRECT format that the backend expects
            correct_data = {
                "instance_id": "item_1",
                "schema": "sentiment",
                "state": [
                    {"name": "positive", "value": "true"},
                    {"name": "negative", "value": None},
                    {"name": "neutral", "value": None}
                ],
                "type": "label"
            }

            response = server.post(
                "/updateinstance",
                json=correct_data,
                headers={"Content-Type": "application/json"}
            )

            assert response.status_code == 200
            result = json.loads(response.text)
            assert result["status"] == "success"

            # Now the annotations SHOULD be saved
            user_state = server.get_user_state(username)
            all_annotations = user_state.get_all_annotations()

            # This should work with the correct format
            assert len(all_annotations) > 0, "Annotations should be saved with correct format"
            assert "item_1" in all_annotations

        finally:
            server.stop()

    def test_verify_backend_expectations(self):
        """Test to verify exactly what format the backend expects."""

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

            # Test the exact format the backend expects
            expected_format = {
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
                json=expected_format,
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