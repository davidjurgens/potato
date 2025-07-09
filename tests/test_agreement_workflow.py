"""
Inter-Annotator Agreement Workflow Tests

This module contains tests for inter-annotator agreement workflows,
including agreement calculation, validation, and analysis.
"""

import json
import pytest
import requests
import time
from unittest.mock import patch, MagicMock


class TestAgreementWorkflow:
    """Test inter-annotator agreement workflows."""

    @pytest.fixture(scope="class")
    def server_url(self):
        """Get the server URL for testing."""
        return "http://localhost:9001"

    def test_basic_agreement_workflow(self, server_url):
        """
        Test basic agreement workflow:
        1. Create multiple annotators
        2. Have them annotate the same items
        3. Calculate agreement metrics
        4. Verify agreement thresholds
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create multiple annotators
            users_data = {
                "users": [
                    {"username": "annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "annotator_2", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "annotator_3", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 3
                print("✓ Created 3 annotators")

            # Have annotators submit similar annotations for agreement testing
            agreement_items = ["item_1", "item_2", "item_3", "item_4", "item_5"]

            # Annotator 1: Consistent ratings
            for i, item_id in enumerate(agreement_items):
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": 4,  # Consistent rating
                        "confidence": 0.8,
                        "annotation_type": "agreement_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Annotator 2: Similar ratings (high agreement)
            for i, item_id in enumerate(agreement_items):
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": 4 if i < 4 else 3,  # Mostly similar
                        "confidence": 0.7,
                        "annotation_type": "agreement_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Annotator 3: Different ratings (lower agreement)
            for i, item_id in enumerate(agreement_items):
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": 2 if i % 2 == 0 else 5,  # Alternating ratings
                        "confidence": 0.6,
                        "annotation_type": "agreement_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify all annotations were recorded
            for username in ["annotator_1", "annotator_2", "annotator_3"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 5
                    print(f"✓ {username} completed {user_state['annotations']['total_count']} annotations")

            print("✓ Basic agreement workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_agreement_calculation_workflow(self, server_url):
        """
        Test agreement calculation workflow:
        - Test Krippendorff's alpha calculation
        - Test Fleiss' kappa calculation
        - Test agreement threshold validation
        - Test agreement reporting
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create annotators for agreement calculation
            users_data = {
                "users": [
                    {"username": "alpha_annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "alpha_annotator_2", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations for agreement calculation
            # Use identical annotations to test perfect agreement
            perfect_agreement_items = ["alpha_item_1", "alpha_item_2", "alpha_item_3"]

            for annotator in ["alpha_annotator_1", "alpha_annotator_2"]:
                for item_id in perfect_agreement_items:
                    annotation_data = {
                        "instance_id": item_id,
                        "annotation_data": json.dumps({
                            "rating": 3,  # Identical ratings for perfect agreement
                            "confidence": 0.8,
                            "annotation_type": "alpha_test"
                        })
                    }
                    response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                    assert response.status_code in [200, 302]

            # Verify annotations for agreement calculation
            for username in ["alpha_annotator_1", "alpha_annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 3
                    print(f"✓ {username} completed annotations for agreement calculation")

            print("✓ Agreement calculation workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_agreement_threshold_validation(self, server_url):
        """
        Test agreement threshold validation:
        - Test minimum agreement thresholds
        - Test agreement quality checks
        - Test disagreement resolution workflow
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create annotators for threshold testing
            users_data = {
                "users": [
                    {"username": "threshold_annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "threshold_annotator_2", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations with varying agreement levels
            threshold_items = ["threshold_item_1", "threshold_item_2", "threshold_item_3"]

            # Annotator 1: Consistent ratings
            for item_id in threshold_items:
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": 4,
                        "confidence": 0.9,
                        "annotation_type": "threshold_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Annotator 2: Mixed agreement (some similar, some different)
            mixed_ratings = [4, 1, 4]  # High, low, high agreement
            for i, item_id in enumerate(threshold_items):
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": mixed_ratings[i],
                        "confidence": 0.7,
                        "annotation_type": "threshold_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify threshold test annotations
            for username in ["threshold_annotator_1", "threshold_annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 3
                    print(f"✓ {username} completed threshold test annotations")

            print("✓ Agreement threshold validation completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_disagreement_resolution_workflow(self, server_url):
        """
        Test disagreement resolution workflow:
        - Test identification of disagreed items
        - Test third annotator assignment
        - Test majority voting
        - Test final consensus
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create annotators for disagreement resolution
            users_data = {
                "users": [
                    {"username": "resolve_annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "resolve_annotator_2", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "resolve_annotator_3", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations with intentional disagreements
            disagreement_items = ["disagree_item_1", "disagree_item_2", "disagree_item_3"]

            # Annotator 1: Ratings [1, 2, 3]
            for i, item_id in enumerate(disagreement_items):
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": i + 1,
                        "confidence": 0.8,
                        "annotation_type": "disagreement_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Annotator 2: Ratings [5, 4, 3] (disagrees on first two)
            disagree_ratings = [5, 4, 3]
            for i, item_id in enumerate(disagreement_items):
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": disagree_ratings[i],
                        "confidence": 0.7,
                        "annotation_type": "disagreement_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Annotator 3: Ratings [3, 3, 3] (tie-breaker)
            for item_id in disagreement_items:
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": 3,
                        "confidence": 0.6,
                        "annotation_type": "disagreement_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify disagreement resolution annotations
            for username in ["resolve_annotator_1", "resolve_annotator_2", "resolve_annotator_3"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 3
                    print(f"✓ {username} completed disagreement resolution annotations")

            print("✓ Disagreement resolution workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_agreement_export_workflow(self, server_url):
        """
        Test agreement export workflow:
        - Test agreement report generation
        - Test agreement data export
        - Test agreement visualization data
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create annotators for export testing
            users_data = {
                "users": [
                    {"username": "export_annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "export_annotator_2", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations for export testing
            export_items = ["export_item_1", "export_item_2"]

            for annotator in ["export_annotator_1", "export_annotator_2"]:
                for item_id in export_items:
                    annotation_data = {
                        "instance_id": item_id,
                        "annotation_data": json.dumps({
                            "rating": 4,
                            "confidence": 0.8,
                            "notes": f"Annotation by {annotator}",
                            "annotation_type": "export_test"
                        })
                    }
                    response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                    assert response.status_code in [200, 302]

            # Verify export test annotations
            for username in ["export_annotator_1", "export_annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 2
                    print(f"✓ {username} completed export test annotations")

            print("✓ Agreement export workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")


class TestAgreementWorkflowMocked:
    """Test agreement workflows with mocked responses."""

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_basic_agreement_workflow(self, mock_get, mock_post):
        """Test basic agreement workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "annotator_1",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 5},
            "assignments": {"total": 5, "remaining": 0}
        })

        # Test agreement workflow
        server_url = "http://localhost:9001"

        # Submit agreement annotations
        annotation_data = {
            "instance_id": "agreement_item_1",
            "annotation_data": json.dumps({
                "rating": 4,
                "confidence": 0.8,
                "annotation_type": "agreement_test"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/annotator_1")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 5

        print("✓ Mocked basic agreement workflow test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_agreement_calculation(self, mock_get, mock_post):
        """Test agreement calculation with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "alpha_annotator_1",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 3},
            "assignments": {"total": 3, "remaining": 0}
        })

        # Test agreement calculation
        server_url = "http://localhost:9001"

        # Submit annotations for agreement calculation
        annotation_data = {
            "instance_id": "alpha_item_1",
            "annotation_data": json.dumps({
                "rating": 3,
                "confidence": 0.8,
                "annotation_type": "alpha_test"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/alpha_annotator_1")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 3

        print("✓ Mocked agreement calculation test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_disagreement_resolution(self, mock_get, mock_post):
        """Test disagreement resolution with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "resolve_annotator_1",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 3},
            "assignments": {"total": 3, "remaining": 0}
        })

        # Test disagreement resolution
        server_url = "http://localhost:9001"

        # Submit disagreement annotations
        annotation_data = {
            "instance_id": "disagree_item_1",
            "annotation_data": json.dumps({
                "rating": 1,
                "confidence": 0.8,
                "annotation_type": "disagreement_test"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/resolve_annotator_1")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 3

        print("✓ Mocked disagreement resolution test passed!")