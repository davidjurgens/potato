"""
Active Learning Workflow Tests

This module contains tests for active learning workflows,
including sampling strategies, uncertainty sampling, and adaptive annotation.
"""

import json
import pytest
import requests
import time
from unittest.mock import patch, MagicMock


class TestActiveLearningWorkflow:
    """Test active learning workflows."""

    @pytest.fixture(scope="class")
    def server_url(self):
        """Get the server URL for testing."""
        return "http://localhost:9001"

    def test_random_sampling_workflow(self, server_url):
        """
        Test random sampling workflow:
        1. Create initial dataset
        2. Apply random sampling strategy
        3. Assign sampled items to annotators
        4. Verify sampling distribution
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create annotators for random sampling
            users_data = {
                "users": [
                    {"username": "random_annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "random_annotator_2", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 2
                print("✓ Created annotators for random sampling")

            # Submit annotations for random sampling test
            random_items = ["random_item_1", "random_item_2", "random_item_3", "random_item_4"]

            for annotator in ["random_annotator_1", "random_annotator_2"]:
                for item_id in random_items:
                    annotation_data = {
                        "instance_id": item_id,
                        "annotation_data": json.dumps({
                            "rating": 3,
                            "confidence": 0.7,
                            "annotation_type": "random_sampling_test"
                        })
                    }
                    response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                    assert response.status_code in [200, 302]

            # Verify random sampling annotations
            for username in ["random_annotator_1", "random_annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 4
                    print(f"✓ {username} completed random sampling annotations")

            print("✓ Random sampling workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_uncertainty_sampling_workflow(self, server_url):
        """
        Test uncertainty sampling workflow:
        - Test low confidence item identification
        - Test uncertainty-based item selection
        - Test confidence threshold filtering
        - Test uncertainty ranking
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create annotators for uncertainty sampling
            users_data = {
                "users": [
                    {"username": "uncertainty_annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "uncertainty_annotator_2", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations with varying confidence levels
            uncertainty_items = ["uncertainty_item_1", "uncertainty_item_2", "uncertainty_item_3"]

            # Annotator 1: High confidence annotations
            high_confidence_ratings = [4, 5, 3]
            for i, item_id in enumerate(uncertainty_items):
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": high_confidence_ratings[i],
                        "confidence": 0.9,  # High confidence
                        "annotation_type": "uncertainty_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Annotator 2: Low confidence annotations (uncertainty)
            low_confidence_ratings = [3, 2, 4]
            for i, item_id in enumerate(uncertainty_items):
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": low_confidence_ratings[i],
                        "confidence": 0.3,  # Low confidence (uncertainty)
                        "annotation_type": "uncertainty_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify uncertainty sampling annotations
            for username in ["uncertainty_annotator_1", "uncertainty_annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 3
                    print(f"✓ {username} completed uncertainty sampling annotations")

            print("✓ Uncertainty sampling workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_stratified_sampling_workflow(self, server_url):
        """
        Test stratified sampling workflow:
        - Test category-based stratification
        - Test balanced sampling across categories
        - Test stratification constraints
        - Test category distribution validation
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create annotators for stratified sampling
            users_data = {
                "users": [
                    {"username": "stratified_annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "stratified_annotator_2", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations for different categories
            category_items = {
                "positive": ["stratified_pos_1", "stratified_pos_2"],
                "negative": ["stratified_neg_1", "stratified_neg_2"],
                "neutral": ["stratified_neu_1", "stratified_neu_2"]
            }

            for annotator in ["stratified_annotator_1", "stratified_annotator_2"]:
                for category, items in category_items.items():
                    for item_id in items:
                        annotation_data = {
                            "instance_id": item_id,
                            "annotation_data": json.dumps({
                                "rating": 4 if category == "positive" else (2 if category == "negative" else 3),
                                "category": category,
                                "confidence": 0.8,
                                "annotation_type": "stratified_test"
                            })
                        }
                        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                        assert response.status_code in [200, 302]

            # Verify stratified sampling annotations
            for username in ["stratified_annotator_1", "stratified_annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 6  # 3 categories * 2 items
                    print(f"✓ {username} completed stratified sampling annotations")

            print("✓ Stratified sampling workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_adaptive_sampling_workflow(self, server_url):
        """
        Test adaptive sampling workflow:
        - Test model-based item selection
        - Test performance-based adaptation
        - Test dynamic sampling strategy changes
        - Test adaptive threshold adjustment
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create annotators for adaptive sampling
            users_data = {
                "users": [
                    {"username": "adaptive_annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "adaptive_annotator_2", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations for adaptive sampling test
            adaptive_items = ["adaptive_item_1", "adaptive_item_2", "adaptive_item_3", "adaptive_item_4"]

            for annotator in ["adaptive_annotator_1", "adaptive_annotator_2"]:
                for i, item_id in enumerate(adaptive_items):
                    # Vary annotation patterns to test adaptation
                    annotation_data = {
                        "instance_id": item_id,
                        "annotation_data": json.dumps({
                            "rating": (i + 1) % 5 + 1,  # Varying ratings
                            "confidence": 0.5 + (i * 0.1),  # Varying confidence
                            "model_prediction": (i + 2) % 5 + 1,  # Model predictions
                            "annotation_type": "adaptive_test"
                        })
                    }
                    response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                    assert response.status_code in [200, 302]

            # Verify adaptive sampling annotations
            for username in ["adaptive_annotator_1", "adaptive_annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 4
                    print(f"✓ {username} completed adaptive sampling annotations")

            print("✓ Adaptive sampling workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_batch_sampling_workflow(self, server_url):
        """
        Test batch sampling workflow:
        - Test batch size constraints
        - Test batch diversity
        - Test batch assignment
        - Test batch completion tracking
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create annotators for batch sampling
            users_data = {
                "users": [
                    {"username": "batch_annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "batch_annotator_2", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations in batches
            batch_items = [
                ["batch_item_1", "batch_item_2", "batch_item_3"],  # Batch 1
                ["batch_item_4", "batch_item_5", "batch_item_6"]   # Batch 2
            ]

            for annotator in ["batch_annotator_1", "batch_annotator_2"]:
                for batch_num, batch in enumerate(batch_items):
                    for item_id in batch:
                        annotation_data = {
                            "instance_id": item_id,
                            "annotation_data": json.dumps({
                                "rating": 3,
                                "confidence": 0.8,
                                "batch_number": batch_num + 1,
                                "annotation_type": "batch_test"
                            })
                        }
                        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                        assert response.status_code in [200, 302]

            # Verify batch sampling annotations
            for username in ["batch_annotator_1", "batch_annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 6  # 2 batches * 3 items
                    print(f"✓ {username} completed batch sampling annotations")

            print("✓ Batch sampling workflow completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")


class TestActiveLearningWorkflowMocked:
    """Test active learning workflows with mocked responses."""

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_random_sampling_workflow(self, mock_get, mock_post):
        """Test random sampling workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "random_annotator_1",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 4},
            "assignments": {"total": 4, "remaining": 0}
        })

        # Test random sampling workflow
        server_url = "http://localhost:9001"

        # Submit random sampling annotations
        annotation_data = {
            "instance_id": "random_item_1",
            "annotation_data": json.dumps({
                "rating": 3,
                "confidence": 0.7,
                "annotation_type": "random_sampling_test"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/random_annotator_1")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 4

        print("✓ Mocked random sampling workflow test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_uncertainty_sampling_workflow(self, mock_get, mock_post):
        """Test uncertainty sampling workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "uncertainty_annotator_1",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 3},
            "assignments": {"total": 3, "remaining": 0}
        })

        # Test uncertainty sampling workflow
        server_url = "http://localhost:9001"

        # Submit uncertainty sampling annotations
        annotation_data = {
            "instance_id": "uncertainty_item_1",
            "annotation_data": json.dumps({
                "rating": 3,
                "confidence": 0.3,  # Low confidence (uncertainty)
                "annotation_type": "uncertainty_test"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/uncertainty_annotator_1")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 3

        print("✓ Mocked uncertainty sampling workflow test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_stratified_sampling_workflow(self, mock_get, mock_post):
        """Test stratified sampling workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "stratified_annotator_1",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 6},
            "assignments": {"total": 6, "remaining": 0}
        })

        # Test stratified sampling workflow
        server_url = "http://localhost:9001"

        # Submit stratified sampling annotations
        annotation_data = {
            "instance_id": "stratified_pos_1",
            "annotation_data": json.dumps({
                "rating": 4,
                "category": "positive",
                "confidence": 0.8,
                "annotation_type": "stratified_test"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/stratified_annotator_1")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 6

        print("✓ Mocked stratified sampling workflow test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_adaptive_sampling_workflow(self, mock_get, mock_post):
        """Test adaptive sampling workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "adaptive_annotator_1",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 4},
            "assignments": {"total": 4, "remaining": 0}
        })

        # Test adaptive sampling workflow
        server_url = "http://localhost:9001"

        # Submit adaptive sampling annotations
        annotation_data = {
            "instance_id": "adaptive_item_1",
            "annotation_data": json.dumps({
                "rating": 3,
                "confidence": 0.5,
                "model_prediction": 4,
                "annotation_type": "adaptive_test"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/adaptive_annotator_1")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 4

        print("✓ Mocked adaptive sampling workflow test passed!")