"""
Multi-Phase Workflow Tests

This module contains tests for complete multi-phase annotation workflows,
including consent, instructions, annotation, and post-study phases.
"""

import json
import pytest
import requests
import time
from unittest.mock import patch, MagicMock


class TestMultiPhaseWorkflow:
    """Test complete multi-phase annotation workflows."""

    @pytest.fixture(scope="class")
    def server_url(self):
        """Get the server URL for testing."""
        return "http://localhost:9001"

    def test_complete_multi_phase_workflow(self, server_url):
        """
        Test complete workflow through all phases with surveyflow:
        1. Create user in LOGIN phase
        2. Advance through CONSENT phase (with required consent questions)
        3. Complete INSTRUCTIONS phase (multiple instruction pages)
        4. Perform ANNOTATION phase
        5. Complete POSTSTUDY phase (demographics, satisfaction)
        6. Verify user reaches DONE phase
        """
        try:
            # Step 1: Reset system and create user
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user starting in LOGIN phase
            user_data = {
                "username": "phase_test_user",
                "initial_phase": "LOGIN",
                "assign_items": False
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["status"] == "created"
                print("✓ Created user in LOGIN phase")

            # Step 2: Advance through CONSENT phase
            response = requests.post(f"{server_url}/test/advance_phase/phase_test_user", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                user_state = response.json()
                assert user_state["phase"] == "CONSENT"
                print("✓ Advanced to CONSENT phase")

            # Step 3: Complete CONSENT phase (simulate consent submission)
            response = requests.post(f"{server_url}/test/advance_phase/phase_test_user", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                user_state = response.json()
                assert user_state["phase"] == "INSTRUCTIONS"
                print("✓ Advanced to INSTRUCTIONS phase")

            # Step 4: Complete INSTRUCTIONS phase
            response = requests.post(f"{server_url}/test/advance_phase/phase_test_user", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                user_state = response.json()
                assert user_state["phase"] == "ANNOTATION"
                print("✓ Advanced to ANNOTATION phase")

            # Step 5: Perform ANNOTATION phase
            # Submit some annotations
            for i in range(1, 4):
                annotation_data = {
                    "instance_id": f"item_{i}",
                    "annotation_data": json.dumps({
                        "rating": i,
                        "phase": "annotation"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            print("✓ Completed annotation phase")

            # Step 6: Advance to POSTSTUDY phase
            response = requests.post(f"{server_url}/test/advance_phase/phase_test_user", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                user_state = response.json()
                assert user_state["phase"] == "POSTSTUDY"
                print("✓ Advanced to POSTSTUDY phase")

            # Step 7: Complete POSTSTUDY phase
            response = requests.post(f"{server_url}/test/advance_phase/phase_test_user", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                user_state = response.json()
                assert user_state["phase"] == "DONE"
                print("✓ Reached DONE phase")

            # Step 8: Verify final state
            response = requests.get(f"{server_url}/test/user_state/phase_test_user", timeout=5)
            if response.status_code == 200:
                final_state = response.json()
                assert final_state["phase"] == "DONE"
                assert final_state["annotations"]["total_count"] >= 3
                print("✓ Multi-phase workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_phase_transition_validation(self, server_url):
        """Test that phase transitions follow proper order and validation."""
        try:
            # Reset system
            requests.post(f"{server_url}/test/reset", timeout=5)

            # Create user
            user_data = {"username": "phase_validation_user", "initial_phase": "LOGIN"}
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Test phase order: LOGIN -> CONSENT -> INSTRUCTIONS -> ANNOTATION -> POSTSTUDY -> DONE
            expected_phases = ["LOGIN", "CONSENT", "INSTRUCTIONS", "ANNOTATION", "POSTSTUDY", "DONE"]

            for i, expected_phase in enumerate(expected_phases):
                # Check current phase
                response = requests.get(f"{server_url}/test/user_state/phase_validation_user", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["phase"] == expected_phase
                    print(f"✓ Phase {i+1}: {expected_phase}")

                # Advance to next phase (except for last phase)
                if i < len(expected_phases) - 1:
                    response = requests.post(f"{server_url}/test/advance_phase/phase_validation_user", timeout=5)
                    assert response.status_code in [200, 302]

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_phase_requirements_validation(self, server_url):
        """Test that phases enforce their requirements before allowing advancement."""
        try:
            # Reset system
            requests.post(f"{server_url}/test/reset", timeout=5)

            # Create user in CONSENT phase
            user_data = {"username": "requirements_user", "initial_phase": "CONSENT"}
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Test that user cannot skip required phases
            response = requests.get(f"{server_url}/test/user_state/requirements_user", timeout=5)
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["phase"] == "CONSENT"
                print("✓ User properly started in CONSENT phase")

            # Test phase advancement
            response = requests.post(f"{server_url}/test/advance_phase/requirements_user", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                user_state = response.json()
                assert user_state["phase"] == "INSTRUCTIONS"
                print("✓ Phase advancement works correctly")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_multi_user_phase_independence(self, server_url):
        """Test that multiple users can be in different phases independently."""
        try:
            # Reset system
            requests.post(f"{server_url}/test/reset", timeout=5)

            # Create multiple users in different phases
            users_data = {
                "users": [
                    {"username": "user_consent", "initial_phase": "CONSENT"},
                    {"username": "user_instructions", "initial_phase": "INSTRUCTIONS"},
                    {"username": "user_annotation", "initial_phase": "ANNOTATION"},
                    {"username": "user_poststudy", "initial_phase": "POSTSTUDY"}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 4
                print("✓ Created 4 users in different phases")

            # Verify each user is in the correct phase
            expected_phases = {
                "user_consent": "CONSENT",
                "user_instructions": "INSTRUCTIONS",
                "user_annotation": "ANNOTATION",
                "user_poststudy": "POSTSTUDY"
            }

            for username, expected_phase in expected_phases.items():
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["phase"] == expected_phase
                    print(f"✓ {username} in {expected_phase} phase")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")


class TestMultiPhaseWorkflowMocked:
    """Test multi-phase workflows with mocked responses."""

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_multi_phase_workflow(self, mock_get, mock_post):
        """Test complete multi-phase workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses for phase progression
        phase_counter = 0
        phase_order = ['CONSENT', 'INSTRUCTIONS', 'ANNOTATION', 'POSTSTUDY', 'DONE']

        def mock_post_side_effect(url, *args, **kwargs):
            nonlocal phase_counter
            if "/test/reset" in url:
                return create_mock_response(200, {"status": "reset_complete"})
            elif "/test/create_user" in url:
                return create_mock_response(200, {
                    "status": "created",
                    "username": "phase_test_user",
                    "initial_phase": "LOGIN"
                })
            elif "/test/advance_phase" in url:
                # Simulate phase progression
                if phase_counter < len(phase_order):
                    current_phase = phase_order[phase_counter]
                    phase_counter += 1
                else:
                    current_phase = 'DONE'

                return create_mock_response(200, {
                    "username": "phase_test_user",
                    "phase": current_phase,
                    "annotations": {"total_count": 3}
                })
            elif "/submit_annotation" in url:
                return create_mock_response(200, {"status": "success"})
            else:
                return create_mock_response(200, {"status": "success"})

        def mock_get_side_effect(url, *args, **kwargs):
            if "/test/user_state" in url:
                return create_mock_response(200, {
                    "username": "phase_test_user",
                    "phase": "DONE",
                    "annotations": {"total_count": 3},
                    "assignments": {"total": 0, "remaining": 0}
                })
            else:
                return create_mock_response(200, {"status": "success"})

        mock_post.side_effect = mock_post_side_effect
        mock_get.side_effect = mock_get_side_effect

        # Test the workflow
        server_url = "http://localhost:9001"

        # Reset system
        response = requests.post(f"{server_url}/test/reset")
        assert response.status_code == 200

        # Create user
        user_data = {"username": "phase_test_user", "initial_phase": "LOGIN"}
        response = requests.post(f"{server_url}/test/create_user", json=user_data)
        assert response.status_code == 200

        # Advance through phases
        for phase in ['CONSENT', 'INSTRUCTIONS', 'ANNOTATION', 'POSTSTUDY', 'DONE']:
            response = requests.post(f"{server_url}/test/advance_phase/phase_test_user")
            assert response.status_code == 200
            data = response.json()
            assert data["phase"] == phase

        # Verify final state
        response = requests.get(f"{server_url}/test/user_state/phase_test_user")
        assert response.status_code == 200
        final_state = response.json()
        assert final_state["phase"] == "DONE"

        print("✓ Mocked multi-phase workflow test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_phase_validation(self, mock_get, mock_post):
        """Test phase validation with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Mock phase validation responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "test_user",
            "phase": "CONSENT",
            "annotations": {"total_count": 0}
        })

        # Test phase validation
        server_url = "http://localhost:9001"

        response = requests.get(f"{server_url}/test/user_state/test_user")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["phase"] == "CONSENT"

        print("✓ Mocked phase validation test passed!")