"""
Annotation Workflow Integration Tests

This module contains comprehensive tests that demonstrate complete annotation workflows
using the new test routes. These tests verify the entire system from data creation
to annotation completion.
"""

import json
import pytest
import time
import tempfile
import os
from tests.flask_test_setup import FlaskTestServer
import requests

class TestAnnotationWorkflowIntegration:
    """Test complete annotation workflow integration."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(port=9001, debug=True)
        assert server.start_server()
        yield server
        server.stop_server()

    @pytest.fixture
    def test_dataset(self):
        """Create a test dataset for annotation."""
        return [
            {
                "id": "item_1",
                "text": "This is a positive statement about the product.",
                "metadata": {"source": "test"}
            },
            {
                "id": "item_2",
                "text": "This is a negative statement about the product.",
                "metadata": {"source": "test"}
            },
            {
                "id": "item_3",
                "text": "This is a neutral statement about the product.",
                "metadata": {"source": "test"}
            }
        ]

    def test_complete_annotation_workflow(self, flask_server, test_dataset):
        """Test a complete annotation workflow from start to finish."""

        # Step 1: Reset the system
        response = flask_server.post("/test/reset", timeout=5)
        assert response.status_code == 200

        # Step 2: Create multiple users
        users_data = {
            "users": [
                {"user_id": "user_1", "initial_phase": "ANNOTATION"},
                {"user_id": "user_2", "initial_phase": "ANNOTATION"},
                {"user_id": "user_3", "initial_phase": "ANNOTATION"}
            ]
        }

        response = flask_server.post(
            f"/test/create_users",
            json=users_data,
            timeout=5
        )
        assert response.status_code == 200

        # Step 3: Check system state
        response = flask_server.get("/test/system_state", timeout=5)
        assert response.status_code == 200

        data = response.json()
        assert "users" in data
        assert len(data["users"]) == 3

        # Step 4: Submit annotations for each user
        for i, user_id in enumerate(["user_1", "user_2", "user_3"]):
            # Set session to the correct user
            response = flask_server.post(
                "/test/set_debug_session",
                json={"user_id": user_id},
                timeout=5
            )
            assert response.status_code == 200

            annotation_data = {
                "label": f"label_{i+1}",
                "confidence": 0.8
            }

            response = flask_server.post(
                "/submit_annotation",
                data={
                    "instance_id": f"item_{i+1}",
                    "annotation_data": json.dumps(annotation_data)
                },
                timeout=5
            )
            assert response.status_code == 200

            # Check user state after annotation
            response = flask_server.get(f"/test/user_state/{user_id}", timeout=5)
            assert response.status_code == 200

            user_state = response.json()
            assert user_state["user_id"] == user_id
            assert "annotations" in user_state
            assert "by_instance" in user_state["annotations"]
            assert len(user_state["annotations"]["by_instance"]) > 0

        # Step 5: Check final system state
        response = flask_server.get("/test/system_state", timeout=5)
        assert response.status_code == 200

        final_state = response.json()
        assert "total_annotations" in final_state
        assert final_state["total_annotations"] >= 3

    def test_user_phase_transitions(self, flask_server):
        """Test user phase transitions during annotation workflow."""

        # Reset system
        response = flask_server.post("/test/reset", timeout=5)
        assert response.status_code == 200

        # Create user in consent phase
        user_data = {"user_id": "phase_test_user", "initial_phase": "consent"}
        response = flask_server.post("/test/create_user", json=user_data, timeout=5)
        assert response.status_code == 200

        # Check initial phase
        response = flask_server.get("/test/user_state/phase_test_user", timeout=5)
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["phase"] == "consent", f"Expected 'consent', got '{user_state.get('phase')}'"

        # Advance to instructions phase
        response = flask_server.post("/test/advance_user_phase/phase_test_user", timeout=5)
        assert response.status_code == 200

        # Check instructions phase
        response = flask_server.get("/test/user_state/phase_test_user", timeout=5)
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["phase"] == "instructions", f"Expected 'instructions', got '{user_state.get('phase')}'"

        # Advance to done phase (since config only has consent and instructions)
        response = flask_server.post("/test/advance_user_phase/phase_test_user", timeout=5)
        assert response.status_code == 200

        # Check done phase
        response = flask_server.get("/test/user_state/phase_test_user", timeout=5)
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["phase"] == "done", f"Expected 'done', got '{user_state.get('phase')}'"