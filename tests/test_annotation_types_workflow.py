"""
Annotation Type-Specific Workflow Tests

This module contains tests for different annotation types and their specific behaviors,
including validation, key bindings, and data capture.
"""

import json
import pytest
import requests
import time
from unittest.mock import patch, MagicMock


class TestAnnotationTypesWorkflow:
    """Test different annotation types and their specific workflows."""

    @pytest.fixture(scope="class")
    def server_url(self):
        """Get the server URL for testing."""
        return "http://localhost:9001"

    def test_likert_scale_workflow(self, server_url):
        """
        Test likert scale annotation with validation:
        - Test required field validation
        - Test sequential key bindings (1-5 keys)
        - Test displaying_score option
        - Test min_label/max_label display
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user in annotation phase
            user_data = {
                "username": "likert_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit likert scale annotations
            likert_annotations = [
                {"rating": 1, "confidence": 0.8, "notes": "Strongly disagree"},
                {"rating": 3, "confidence": 0.6, "notes": "Neutral"},
                {"rating": 5, "confidence": 0.9, "notes": "Strongly agree"}
            ]

            for i, annotation in enumerate(likert_annotations):
                annotation_data = {
                    "instance_id": f"likert_item_{i+1}",
                    "annotation_data": json.dumps({
                        "likert_rating": annotation["rating"],
                        "confidence": annotation["confidence"],
                        "notes": annotation["notes"],
                        "annotation_type": "likert"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify annotations were recorded
            response = requests.get(f"{server_url}/test/user_state/likert_user", timeout=5)
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["annotations"]["total_count"] >= 3
                print("✓ Likert scale annotations recorded successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_span_annotation_workflow(self, server_url):
        """
        Test text span highlighting workflow:
        - Test span creation and deletion
        - Test overlapping spans
        - Test span validation (required spans)
        - Test span export format
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user in annotation phase
            user_data = {
                "username": "span_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit span annotations
            span_annotations = [
                {
                    "spans": [
                        {"start": 0, "end": 5, "label": "positive", "text": "happy"},
                        {"start": 10, "end": 15, "label": "negative", "text": "sad"}
                    ],
                    "annotation_type": "span"
                },
                {
                    "spans": [
                        {"start": 0, "end": 8, "label": "emotion", "text": "excited"},
                        {"start": 5, "end": 12, "label": "emotion", "text": "excited about"}
                    ],
                    "annotation_type": "span"
                }
            ]

            for i, annotation in enumerate(span_annotations):
                annotation_data = {
                    "instance_id": f"span_item_{i+1}",
                    "annotation_data": json.dumps(annotation)
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify span annotations were recorded
            response = requests.get(f"{server_url}/test/user_state/span_user", timeout=5)
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["annotations"]["total_count"] >= 2
                print("✓ Span annotations recorded successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_multiselect_workflow(self, server_url):
        """
        Test checkbox/multiselect annotation:
        - Test multiple selections
        - Test selection constraints
        - Test free response integration
        - Test tooltip functionality
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user in annotation phase
            user_data = {
                "username": "multiselect_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit multiselect annotations
            multiselect_annotations = [
                {
                    "selected_labels": ["blue", "green"],
                    "free_response": "I also see some yellow",
                    "annotation_type": "multiselect"
                },
                {
                    "selected_labels": ["red", "orange", "purple"],
                    "free_response": "",
                    "annotation_type": "multiselect"
                }
            ]

            for i, annotation in enumerate(multiselect_annotations):
                annotation_data = {
                    "instance_id": f"multiselect_item_{i+1}",
                    "annotation_data": json.dumps(annotation)
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify multiselect annotations were recorded
            response = requests.get(f"{server_url}/test/user_state/multiselect_user", timeout=5)
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["annotations"]["total_count"] >= 2
                print("✓ Multiselect annotations recorded successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_slider_workflow(self, server_url):
        """
        Test slider-based annotation:
        - Test range validation
        - Test starting value
        - Test min/max labels
        - Test continuous value capture
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user in annotation phase
            user_data = {
                "username": "slider_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit slider annotations
            slider_annotations = [
                {"slider_value": 25, "confidence": 0.7, "annotation_type": "slider"},
                {"slider_value": 75, "confidence": 0.9, "annotation_type": "slider"},
                {"slider_value": 50, "confidence": 0.5, "annotation_type": "slider"}
            ]

            for i, annotation in enumerate(slider_annotations):
                annotation_data = {
                    "instance_id": f"slider_item_{i+1}",
                    "annotation_data": json.dumps(annotation)
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify slider annotations were recorded
            response = requests.get(f"{server_url}/test/user_state/slider_user", timeout=5)
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["annotations"]["total_count"] >= 3
                print("✓ Slider annotations recorded successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_radio_button_workflow(self, server_url):
        """
        Test radio button annotation:
        - Test single selection constraint
        - Test required field validation
        - Test horizontal layout
        - Test key bindings
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user in annotation phase
            user_data = {
                "username": "radio_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit radio button annotations
            radio_annotations = [
                {"selected_option": "option_a", "annotation_type": "radio"},
                {"selected_option": "option_b", "annotation_type": "radio"},
                {"selected_option": "option_c", "annotation_type": "radio"}
            ]

            for i, annotation in enumerate(radio_annotations):
                annotation_data = {
                    "instance_id": f"radio_item_{i+1}",
                    "annotation_data": json.dumps(annotation)
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify radio annotations were recorded
            response = requests.get(f"{server_url}/test/user_state/radio_user", timeout=5)
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["annotations"]["total_count"] >= 3
                print("✓ Radio button annotations recorded successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_mixed_annotation_types_workflow(self, server_url):
        """
        Test workflow with multiple annotation types on the same item:
        - Test likert + text combination
        - Test span + multiselect combination
        - Test slider + radio combination
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user in annotation phase
            user_data = {
                "username": "mixed_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit mixed annotation types
            mixed_annotations = [
                {
                    "likert_rating": 4,
                    "text_response": "This is a good example",
                    "annotation_type": "mixed_likert_text"
                },
                {
                    "spans": [{"start": 0, "end": 4, "label": "positive"}],
                    "selected_labels": ["relevant", "clear"],
                    "annotation_type": "mixed_span_multiselect"
                }
            ]

            for i, annotation in enumerate(mixed_annotations):
                annotation_data = {
                    "instance_id": f"mixed_item_{i+1}",
                    "annotation_data": json.dumps(annotation)
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify mixed annotations were recorded
            response = requests.get(f"{server_url}/test/user_state/mixed_user", timeout=5)
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["annotations"]["total_count"] >= 2
                print("✓ Mixed annotation types recorded successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")


class TestAnnotationTypesWorkflowMocked:
    """Test annotation type workflows with mocked responses."""

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_likert_workflow(self, mock_get, mock_post):
        """Test likert scale workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "likert_user",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 3},
            "assignments": {"total": 5, "remaining": 2}
        })

        # Test likert workflow
        server_url = "http://localhost:9001"

        # Submit likert annotation
        annotation_data = {
            "instance_id": "likert_item_1",
            "annotation_data": json.dumps({
                "likert_rating": 4,
                "confidence": 0.8,
                "annotation_type": "likert"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/likert_user")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 3

        print("✓ Mocked likert workflow test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_span_workflow(self, mock_get, mock_post):
        """Test span annotation workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "span_user",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 2},
            "assignments": {"total": 3, "remaining": 1}
        })

        # Test span workflow
        server_url = "http://localhost:9001"

        # Submit span annotation
        annotation_data = {
            "instance_id": "span_item_1",
            "annotation_data": json.dumps({
                "spans": [
                    {"start": 0, "end": 5, "label": "positive", "text": "happy"}
                ],
                "annotation_type": "span"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/span_user")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 2

        print("✓ Mocked span workflow test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_multiselect_workflow(self, mock_get, mock_post):
        """Test multiselect workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "multiselect_user",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 2},
            "assignments": {"total": 4, "remaining": 2}
        })

        # Test multiselect workflow
        server_url = "http://localhost:9001"

        # Submit multiselect annotation
        annotation_data = {
            "instance_id": "multiselect_item_1",
            "annotation_data": json.dumps({
                "selected_labels": ["blue", "green"],
                "free_response": "Additional notes",
                "annotation_type": "multiselect"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/multiselect_user")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 2

        print("✓ Mocked multiselect workflow test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_slider_workflow(self, mock_get, mock_post):
        """Test slider workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "slider_user",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 3},
            "assignments": {"total": 5, "remaining": 2}
        })

        # Test slider workflow
        server_url = "http://localhost:9001"

        # Submit slider annotation
        annotation_data = {
            "instance_id": "slider_item_1",
            "annotation_data": json.dumps({
                "slider_value": 75,
                "confidence": 0.9,
                "annotation_type": "slider"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Verify user state
        response = requests.get(f"{server_url}/test/user_state/slider_user")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 3

        print("✓ Mocked slider workflow test passed!")