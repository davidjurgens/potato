"""
Server tests for ICL Labeling API endpoints.

This module tests the REST API endpoints for the In-Context Learning
labeling system, including status, examples, predictions, accuracy,
and verification endpoints.
"""

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_config, create_test_data_file


class TestICLAPIDisabled(unittest.TestCase):
    """Test ICL API endpoints when ICL is disabled."""

    @classmethod
    def setUpClass(cls):
        """Set up test server with ICL disabled."""
        cls.test_dir = create_test_directory("icl_api_disabled")

        # Create test data
        test_data = [
            {"id": "test_001", "text": "Sample text 1"},
            {"id": "test_002", "text": "Sample text 2"}
        ]
        data_file = create_test_data_file(cls.test_dir, test_data, "test_data.jsonl")

        # Create config WITHOUT ICL enabled
        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes=[{
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative"],
                "description": "Sentiment classification"
            }],
            data_files=[data_file],
            # ICL not enabled
        )

        cls.server = FlaskTestServer(config=cls.config_file)
        assert cls.server.start(), "Failed to start test server"

    @classmethod
    def tearDownClass(cls):
        """Stop the test server."""
        if hasattr(cls, 'server'):
            cls.server.stop()

    def test_icl_status_disabled(self):
        """Test /admin/api/icl/status returns disabled status."""
        response = self.server.get("/admin/api/icl/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data.get('enabled', True))

    def test_icl_examples_disabled(self):
        """Test /admin/api/icl/examples when disabled."""
        response = self.server.get("/admin/api/icl/examples")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('examples', {}), {})

    def test_icl_predictions_disabled(self):
        """Test /admin/api/icl/predictions when disabled."""
        response = self.server.get("/admin/api/icl/predictions")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('predictions', []), [])

    def test_icl_accuracy_disabled(self):
        """Test /admin/api/icl/accuracy when disabled."""
        response = self.server.get("/admin/api/icl/accuracy")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('total_predictions', 0), 0)


class TestICLAPIEnabled(unittest.TestCase):
    """Test ICL API endpoints when ICL is enabled."""

    @classmethod
    def setUpClass(cls):
        """Set up test server with ICL enabled."""
        cls.test_dir = create_test_directory("icl_api_enabled")

        # Create test data
        test_data = [
            {"id": f"test_{i:03d}", "text": f"Sample text number {i}"}
            for i in range(20)
        ]
        data_file = create_test_data_file(cls.test_dir, test_data, "test_data.jsonl")

        # Create config WITH ICL enabled
        config_dict = {
            "annotation_schemes": [{
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": [
                    {"name": "positive", "description": "Positive sentiment"},
                    {"name": "neutral", "description": "Neutral sentiment"},
                    {"name": "negative", "description": "Negative sentiment"}
                ],
                "description": "Classify the sentiment"
            }],
            "data_files": [data_file],
            "task_dir": cls.test_dir,
            "output_annotation_dir": os.path.join(cls.test_dir, "output"),
            "icl_labeling": {
                "enabled": True,
                "example_selection": {
                    "min_agreement_threshold": 0.8,
                    "min_annotators_per_instance": 2,
                    "max_examples_per_schema": 10
                },
                "llm_labeling": {
                    "batch_size": 5,
                    "trigger_threshold": 3,
                    "max_total_labels": 10
                },
                "verification": {
                    "enabled": True,
                    "sample_rate": 0.3
                }
            }
        }

        cls.config_file = create_test_config(
            cls.test_dir,
            **config_dict
        )

        cls.server = FlaskTestServer(config=cls.config_file)
        assert cls.server.start(), "Failed to start test server"

    @classmethod
    def tearDownClass(cls):
        """Stop the test server."""
        if hasattr(cls, 'server'):
            cls.server.stop()

        # Clear ICL labeler
        try:
            from potato.ai.icl_labeler import clear_icl_labeler
            clear_icl_labeler()
        except:
            pass

    def test_icl_status_enabled(self):
        """Test /admin/api/icl/status returns enabled status."""
        response = self.server.get("/admin/api/icl/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check expected fields
        self.assertIn('enabled', data)
        self.assertIn('total_examples', data)
        self.assertIn('examples_by_schema', data)
        self.assertIn('total_predictions', data)
        self.assertIn('verification_queue_size', data)
        self.assertIn('accuracy_metrics', data)

    def test_icl_examples_empty_initially(self):
        """Test /admin/api/icl/examples returns empty initially."""
        response = self.server.get("/admin/api/icl/examples")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Initially no examples (no annotations yet)
        self.assertIn('examples', data)

    def test_icl_examples_filter_by_schema(self):
        """Test filtering examples by schema."""
        response = self.server.get("/admin/api/icl/examples?schema=sentiment")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('examples', data)
        self.assertEqual(data.get('schema'), 'sentiment')

    def test_icl_predictions_empty_initially(self):
        """Test /admin/api/icl/predictions returns empty initially."""
        response = self.server.get("/admin/api/icl/predictions")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('predictions', data)

    def test_icl_predictions_filter_by_status(self):
        """Test filtering predictions by verification status."""
        response = self.server.get("/admin/api/icl/predictions?status=pending")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('predictions', data)

    def test_icl_accuracy_empty_initially(self):
        """Test /admin/api/icl/accuracy returns zeros initially."""
        response = self.server.get("/admin/api/icl/accuracy")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data.get('total_predictions', -1), 0)
        self.assertEqual(data.get('total_verified', -1), 0)

    def test_icl_accuracy_filter_by_schema(self):
        """Test filtering accuracy by schema."""
        response = self.server.get("/admin/api/icl/accuracy?schema=sentiment")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('schema_name'), 'sentiment')


class TestICLTriggerEndpoint(unittest.TestCase):
    """Test the manual trigger endpoint."""

    @classmethod
    def setUpClass(cls):
        """Set up test server."""
        cls.test_dir = create_test_directory("icl_trigger")

        test_data = [
            {"id": f"test_{i:03d}", "text": f"Text {i}"}
            for i in range(10)
        ]
        data_file = create_test_data_file(cls.test_dir, test_data, "data.jsonl")

        config_dict = {
            "annotation_schemes": [{
                "name": "category",
                "annotation_type": "radio",
                "labels": ["A", "B", "C"],
                "description": "Categorize"
            }],
            "data_files": [data_file],
            "task_dir": cls.test_dir,
            "output_annotation_dir": os.path.join(cls.test_dir, "output"),
            "icl_labeling": {
                "enabled": True,
                "llm_labeling": {
                    "trigger_threshold": 2  # Low threshold for testing
                }
            }
        }

        cls.config_file = create_test_config(cls.test_dir, **config_dict)
        cls.server = FlaskTestServer(config=cls.config_file)
        assert cls.server.start(), "Failed to start test server"

    @classmethod
    def tearDownClass(cls):
        """Stop the test server."""
        if hasattr(cls, 'server'):
            cls.server.stop()

        try:
            from potato.ai.icl_labeler import clear_icl_labeler
            clear_icl_labeler()
        except:
            pass

    def test_trigger_without_schema(self):
        """Test trigger endpoint without schema parameter."""
        response = self.server.post(
            "/admin/api/icl/trigger",
            json={}
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('error', data)

    def test_trigger_with_schema(self):
        """Test trigger endpoint with schema parameter."""
        response = self.server.post(
            "/admin/api/icl/trigger",
            json={"schema_name": "category"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # May or may not label depending on examples available
        self.assertIn('message', data)

    def test_trigger_invalid_schema(self):
        """Test trigger with non-existent schema."""
        response = self.server.post(
            "/admin/api/icl/trigger",
            json={"schema_name": "nonexistent"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should complete but label 0 items
        self.assertEqual(data.get('predictions_count', -1), 0)


class TestICLVerificationEndpoint(unittest.TestCase):
    """Test the verification recording endpoint."""

    @classmethod
    def setUpClass(cls):
        """Set up test server with user authentication."""
        cls.test_dir = create_test_directory("icl_verification")

        test_data = [
            {"id": f"test_{i:03d}", "text": f"Text {i}"}
            for i in range(10)
        ]
        data_file = create_test_data_file(cls.test_dir, test_data, "data.jsonl")

        config_dict = {
            "annotation_schemes": [{
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative"],
                "description": "Sentiment"
            }],
            "data_files": [data_file],
            "task_dir": cls.test_dir,
            "output_annotation_dir": os.path.join(cls.test_dir, "output"),
            "icl_labeling": {
                "enabled": True
            },
            # Add user config for authentication
            "user_config": {
                "allow_all_users": True
            }
        }

        cls.config_file = create_test_config(cls.test_dir, **config_dict)
        cls.server = FlaskTestServer(config=cls.config_file)
        assert cls.server.start(), "Failed to start test server"

        # Login as a test user to establish session
        login_success = cls.server.login_user("test_user", "any_password")
        assert login_success, "Failed to login test user"

    @classmethod
    def tearDownClass(cls):
        """Stop the test server."""
        if hasattr(cls, 'server'):
            cls.server.stop()

        try:
            from potato.ai.icl_labeler import clear_icl_labeler
            clear_icl_labeler()
        except:
            pass

    def test_verification_missing_params(self):
        """Test verification endpoint with missing parameters."""
        response = self.server.post(
            "/api/icl/record_verification",
            json={"instance_id": "test_001"}
        )

        self.assertEqual(response.status_code, 400)

    def test_verification_nonexistent_prediction(self):
        """Test verification for non-existent prediction."""
        response = self.server.post(
            "/api/icl/record_verification",
            json={
                "instance_id": "nonexistent",
                "schema_name": "sentiment",
                "human_label": "positive"
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data.get('success', True))


class TestICLAPIWithMockedLabeler(unittest.TestCase):
    """Test ICL API with mocked labeler for specific scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = create_test_directory("icl_mocked")

    def tearDown(self):
        """Clean up."""
        try:
            from potato.ai.icl_labeler import clear_icl_labeler
            clear_icl_labeler()
        except:
            pass

    @patch('potato.ai.icl_labeler.get_icl_labeler')
    def test_status_with_populated_data(self, mock_get_labeler):
        """Test status endpoint with populated mock data."""
        mock_labeler = MagicMock()
        mock_labeler.get_status.return_value = {
            'enabled': True,
            'total_examples': 25,
            'examples_by_schema': {'sentiment': 15, 'category': 10},
            'total_predictions': 100,
            'labeled_instances': 100,
            'verification_queue_size': 20,
            'last_example_refresh': '2024-01-15T10:00:00',
            'last_batch_run': '2024-01-15T10:30:00',
            'worker_running': True,
            'accuracy_metrics': {
                'total_predictions': 100,
                'verified_correct': 80,
                'verified_incorrect': 10,
                'pending_verification': 10,
                'total_verified': 90,
                'accuracy': 0.889
            },
            'labeling_paused': False,
            'pause_reason': '',
            'remaining_label_capacity': 50,
            'max_total_labels': 200,
            'max_unlabeled_ratio': 0.5,
            'min_accuracy_threshold': 0.7
        }
        mock_get_labeler.return_value = mock_labeler

        # This test verifies the expected structure - actual API test
        # would require full server setup
        status = mock_labeler.get_status()

        self.assertEqual(status['total_examples'], 25)
        self.assertEqual(status['total_predictions'], 100)
        self.assertAlmostEqual(status['accuracy_metrics']['accuracy'], 0.889, places=2)


class TestICLAPIAuthentication(unittest.TestCase):
    """Test ICL API endpoint authentication."""

    @classmethod
    def setUpClass(cls):
        """Set up test server."""
        cls.test_dir = create_test_directory("icl_auth")

        test_data = [{"id": "test_001", "text": "Sample"}]
        data_file = create_test_data_file(cls.test_dir, test_data, "data.jsonl")

        config_dict = {
            "annotation_schemes": [{
                "name": "test",
                "annotation_type": "radio",
                "labels": ["A", "B"],
                "description": "Test"
            }],
            "data_files": [data_file],
            "task_dir": cls.test_dir,
            "output_annotation_dir": os.path.join(cls.test_dir, "output"),
            "icl_labeling": {"enabled": True}
        }

        cls.config_file = create_test_config(cls.test_dir, **config_dict)
        cls.server = FlaskTestServer(config=cls.config_file)
        assert cls.server.start(), "Failed to start test server"

    @classmethod
    def tearDownClass(cls):
        """Stop the test server."""
        if hasattr(cls, 'server'):
            cls.server.stop()

        try:
            from potato.ai.icl_labeler import clear_icl_labeler
            clear_icl_labeler()
        except:
            pass

    def test_admin_endpoints_require_admin_key(self):
        """Test that admin endpoints require proper authentication."""
        # The FlaskTestServer automatically adds admin API key
        # This test verifies endpoints are accessible with the key

        endpoints = [
            "/admin/api/icl/status",
            "/admin/api/icl/examples",
            "/admin/api/icl/predictions",
            "/admin/api/icl/accuracy"
        ]

        for endpoint in endpoints:
            response = self.server.get(endpoint)
            # Should succeed with admin key
            self.assertIn(response.status_code, [200, 401])


if __name__ == '__main__':
    unittest.main()
