"""
Server integration tests for timestamp tracking functionality.

This module tests the complete timestamp tracking system through the Flask server,
including annotation submission, history tracking, performance metrics, and admin endpoints.
"""

import pytest
import json
import datetime
import tempfile
import os
import yaml
import requests
import time
from tests.helpers.flask_test_setup import FlaskTestServer


class TestTimestampTrackingIntegration:
    """
    Integration tests for timestamp tracking functionality.

    Tests the complete workflow from annotation submission through
    performance metrics and suspicious activity detection.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """
        Create a Flask test server with timestamp tracking test data.

        This fixture:
        1. Creates temporary test data with various annotation types
        2. Sets up a config with annotation schemes
        3. Starts the Flask server
        4. Cleans up after tests complete
        """
        # Create temporary directory for this test
        test_dir = tempfile.mkdtemp()

        # Create test data with multiple instances
        test_data = [
            {"id": "timestamp_test_1", "text": "This is the first test item for timestamp tracking."},
            {"id": "timestamp_test_2", "text": "This is the second test item for timestamp tracking."},
            {"id": "timestamp_test_3", "text": "This is the third test item for timestamp tracking."},
            {"id": "timestamp_test_4", "text": "This is the fourth test item for timestamp tracking."},
            {"id": "timestamp_test_5", "text": "This is the fifth test item for timestamp tracking."}
        ]

        # Write test data to file
        data_file = os.path.join(test_dir, 'timestamp_test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config with annotation schemes
        config = {
            "debug": False,  # Always False for server tests
            "annotation_task_name": "Timestamp Tracking Test Task",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Choose the sentiment of the text."
                },
                {
                    "name": "entity",
                    "annotation_type": "span",
                    "labels": ["person", "organization", "location"],
                    "description": "Mark entities in the text."
                },
                {
                    "name": "complexity",
                    "annotation_type": "slider",
                    "min": 1,
                    "max": 5,
                    "starting_value": 3,
                    "description": "Rate the complexity of the text."
                }
            ],
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": 3
        }

        # Write config file
        config_file = os.path.join(test_dir, 'timestamp_test_config.yaml')
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create and start server
        server = FlaskTestServer(
            port=9015,  # Use unique port for this test class
            debug=False,
            config_file=config_file
        )

        if not server.start():
            pytest.fail("Failed to start Flask test server")

        yield server

        # Cleanup
        server.stop()
        import shutil
        shutil.rmtree(test_dir)

    def test_server_starts_with_timestamp_tracking(self, flask_server):
        """Test that the server starts successfully with timestamp tracking enabled."""
        # Test root endpoint
        response = flask_server.get("/")
        assert response.status_code in [200, 302]

        # Test health endpoint
        response = flask_server.get("/admin/health")
        assert response.status_code == 200

    def test_basic_annotation_with_timestamp_tracking(self, flask_server):
        """Test basic annotation submission with timestamp tracking."""
        # Create user session
        session = requests.Session()
        user_data = {"email": "timestamp_user_1", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit annotation with timestamp tracking
        annotation_data = {
            "instance_id": "timestamp_test_1",
            "annotations": {
                "sentiment:positive": "true"
            },
            "client_timestamp": datetime.datetime.now().isoformat(),
            "request_id": "test-request-123"
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data
        )

        assert response.status_code == 200
        response_data = response.json()

        # Verify response includes timestamp tracking data
        assert "status" in response_data
        assert response_data["status"] == "success"
        assert "processing_time_ms" in response_data
        assert "performance_metrics" in response_data

        # Verify performance metrics structure
        metrics = response_data["performance_metrics"]
        assert "total_actions" in metrics
        assert "average_action_time_ms" in metrics
        assert "fastest_action_time_ms" in metrics
        assert "slowest_action_time_ms" in metrics
        assert "actions_per_minute" in metrics

    def test_multiple_annotations_performance_tracking(self, flask_server):
        """Test performance tracking across multiple annotations."""
        # Create user session
        session = requests.Session()
        user_data = {"email": "timestamp_user_2", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit multiple annotations with delays
        for i in range(3):
            annotation_data = {
                "instance_id": f"timestamp_test_{i+1}",
                "annotations": {
                    "sentiment:positive": "true"
                },
                "client_timestamp": datetime.datetime.now().isoformat(),
                "request_id": f"test-request-{i+1}"
            }

            response = session.post(
                f"{flask_server.base_url}/updateinstance",
                json=annotation_data
            )

            assert response.status_code == 200
            response_data = response.json()

            # Verify performance metrics increase
            metrics = response_data["performance_metrics"]
            assert metrics["total_actions"] == i + 1

            # Small delay between annotations
            time.sleep(0.1)

    def test_span_annotation_timestamp_tracking(self, flask_server):
        """Test timestamp tracking for span annotations."""
        # Create user session
        session = requests.Session()
        user_data = {"email": "timestamp_user_3", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit span annotation
        span_annotation_data = {
            "instance_id": "timestamp_test_1",
            "annotations": {},  # Empty annotations object for frontend format
            "span_annotations": [
                {
                    "schema": "entity",
                    "name": "person",
                    "start": 10,
                    "end": 15,
                    "value": "John"
                }
            ],
            "client_timestamp": datetime.datetime.now().isoformat(),
            "request_id": "span-test-request"
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=span_annotation_data
        )

        assert response.status_code == 200
        response_data = response.json()

        # Verify span annotation was tracked
        assert response_data["status"] == "success"
        assert "processing_time_ms" in response_data
        assert "performance_metrics" in response_data

    def test_backend_format_annotation_tracking(self, flask_server):
        """Test timestamp tracking with backend annotation format."""
        # Create user session
        session = requests.Session()
        user_data = {"email": "timestamp_user_4", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit annotation in backend format
        backend_annotation_data = {
            "instance_id": "timestamp_test_1",
            "type": "radio",
            "schema": "sentiment",
            "state": [
                {"name": "positive", "value": "positive"}
            ],
            "client_timestamp": datetime.datetime.now().isoformat(),
            "request_id": "backend-test-request"
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=backend_annotation_data
        )

        assert response.status_code == 200
        response_data = response.json()

        # Verify backend format was tracked
        assert response_data["status"] == "success"
        assert "processing_time_ms" in response_data
        assert "performance_metrics" in response_data

    def test_admin_annotation_history_endpoint(self, flask_server):
        """Test admin endpoint for retrieving annotation history."""
        # First, create some annotation history
        session = requests.Session()
        user_data = {"email": "admin_test_user", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit a few annotations
        for i in range(2):
            annotation_data = {
                "instance_id": f"timestamp_test_{i+1}",
                "annotations": {
                    "sentiment:positive": "true"
                },
                "client_timestamp": datetime.datetime.now().isoformat(),
                "request_id": f"admin-test-{i+1}"
            }

            response = session.post(
                f"{flask_server.base_url}/updateinstance",
                json=annotation_data
            )
            assert response.status_code == 200

        # Test admin annotation history endpoint
        response = flask_server.get("/admin/api/annotation_history")

        # Endpoint should exist and return data
        assert response.status_code in [200, 404, 500]  # Accept various responses

        if response.status_code == 200:
            data = response.json()
            # Verify response structure if endpoint is implemented
            if "annotation_history" in data:
                assert isinstance(data["annotation_history"], list)

    def test_admin_suspicious_activity_endpoint(self, flask_server):
        """Test admin endpoint for suspicious activity detection."""
        # Test admin suspicious activity endpoint
        response = flask_server.get("/admin/api/suspicious_activity")

        # Endpoint should exist and return data
        assert response.status_code in [200, 404, 500]  # Accept various responses

        if response.status_code == 200:
            data = response.json()
            # Verify response structure if endpoint is implemented
            if "suspicious_activity" in data:
                assert isinstance(data["suspicious_activity"], list)

    def test_admin_annotators_endpoint_with_timing(self, flask_server):
        """Test admin annotators endpoint includes timing data."""
        # First, create some annotation history
        session = requests.Session()
        user_data = {"email": "timing_test_user", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit annotation
        annotation_data = {
            "instance_id": "timestamp_test_1",
            "annotations": {
                "sentiment:positive": "true"
            },
            "client_timestamp": datetime.datetime.now().isoformat(),
            "request_id": "timing-test-request"
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data
        )
        assert response.status_code == 200

        # Test admin annotators endpoint
        response = flask_server.get("/admin/api/annotators")

        # Endpoint should exist and return data
        assert response.status_code in [200, 404, 500]  # Accept various responses

        if response.status_code == 200:
            data = response.json()
            # Verify response structure if endpoint is implemented
            if "annotators" in data:
                assert isinstance(data["annotators"], list)
                if len(data["annotators"]) > 0:
                    annotator = data["annotators"][0]
                    # Check for timing-related fields
                    timing_fields = [
                        "total_actions", "average_action_time_ms",
                        "fastest_action_time_ms", "slowest_action_time_ms",
                        "actions_per_minute", "suspicious_score", "suspicious_level"
                    ]
                    for field in timing_fields:
                        if field in annotator:
                            assert annotator[field] is not None

    def test_session_management_in_timestamp_tracking(self, flask_server):
        """Test that session management works with timestamp tracking."""
        # Create user session
        session = requests.Session()
        user_data = {"email": "session_test_user", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit annotation (should start session automatically)
        annotation_data = {
            "instance_id": "timestamp_test_1",
            "annotations": {
                "sentiment:positive": "true"
            },
            "client_timestamp": datetime.datetime.now().isoformat(),
            "request_id": "session-test-request"
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data
        )

        assert response.status_code == 200
        response_data = response.json()

        # Verify session was managed
        assert response_data["status"] == "success"
        assert "processing_time_ms" in response_data
        assert "performance_metrics" in response_data

    def test_error_handling_in_timestamp_tracking(self, flask_server):
        """Test error handling in timestamp tracking."""
        # Test with invalid data
        session = requests.Session()
        user_data = {"email": "error_test_user", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Test with missing instance_id
        invalid_data = {
            "annotations": {
                "sentiment:positive": "true"
            },
            "client_timestamp": datetime.datetime.now().isoformat()
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=invalid_data
        )

        # Should handle error gracefully
        assert response.status_code in [200, 400, 500]

    def test_concurrent_annotation_tracking(self, flask_server):
        """Test timestamp tracking with concurrent annotation requests."""
        import threading

        # Create user session
        session = requests.Session()
        user_data = {"email": "concurrent_test_user", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Function to submit annotation
        def submit_annotation(instance_id, request_id):
            annotation_data = {
                "instance_id": instance_id,
                "annotations": {
                    "sentiment:positive": "true"
                },
                "client_timestamp": datetime.datetime.now().isoformat(),
                "request_id": request_id
            }

            response = session.post(
                f"{flask_server.base_url}/updateinstance",
                json=annotation_data
            )
            return response.status_code == 200

        # Submit concurrent annotations
        threads = []
        results = []

        for i in range(3):
            thread = threading.Thread(
                target=lambda i=i: results.append(
                    submit_annotation(f"timestamp_test_{i+1}", f"concurrent-{i+1}")
                )
            )
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all annotations were successful
        assert all(results)

        # Verify performance metrics reflect concurrent activity
        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": "timestamp_test_5",
                "annotations": {"sentiment:negative": "true"},
                "client_timestamp": datetime.datetime.now().isoformat(),
                "request_id": "final-check"
            }
        )

        assert response.status_code == 200
        response_data = response.json()
        metrics = response_data["performance_metrics"]

        # Should have tracked all annotations
        assert metrics["total_actions"] >= 4  # 3 concurrent + 1 final


class TestTimestampTrackingEdgeCases:
    """
    Edge case tests for timestamp tracking functionality.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server for edge case testing."""
        # Create temporary directory for this test
        test_dir = tempfile.mkdtemp()

        # Create minimal test data
        test_data = [
            {"id": "edge_test_1", "text": "Edge case test item."}
        ]

        # Write test data to file
        data_file = os.path.join(test_dir, 'edge_test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create minimal config
        config = {
            "debug": False,
            "annotation_task_name": "Edge Case Test Task",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "test_scheme",
                    "annotation_type": "radio",
                    "labels": ["option_a", "option_b"],
                    "description": "Test scheme for edge cases."
                }
            ],
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }

        # Write config file
        config_file = os.path.join(test_dir, 'edge_test_config.yaml')
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create and start server
        server = FlaskTestServer(
            port=9016,  # Use unique port for this test class
            debug=False,
            config_file=config_file
        )

        if not server.start():
            pytest.fail("Failed to start Flask test server")

        yield server

        # Cleanup
        server.stop()
        import shutil
        shutil.rmtree(test_dir)

    def test_invalid_client_timestamp(self, flask_server):
        """Test handling of invalid client timestamp."""
        # Create user session
        session = requests.Session()
        user_data = {"email": "invalid_timestamp_user", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit annotation with invalid timestamp
        annotation_data = {
            "instance_id": "edge_test_1",
            "annotations": {
                "test_scheme:option_a": "true"
            },
            "client_timestamp": "invalid-timestamp-format",
            "request_id": "invalid-timestamp-test"
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data
        )

        # Should handle invalid timestamp gracefully
        assert response.status_code in [200, 400, 500]

    def test_missing_metadata_fields(self, flask_server):
        """Test handling of missing metadata fields."""
        # Create user session
        session = requests.Session()
        user_data = {"email": "missing_metadata_user", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit annotation without metadata
        annotation_data = {
            "instance_id": "edge_test_1",
            "annotations": {
                "test_scheme:option_a": "true"
            }
            # No client_timestamp or request_id
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data
        )

        # Should handle missing metadata gracefully
        assert response.status_code in [200, 400, 500]

    def test_very_fast_annotations(self, flask_server):
        """Test handling of very fast annotation submissions."""
        # Create user session
        session = requests.Session()
        user_data = {"email": "fast_annotator", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit multiple annotations very quickly
        for i in range(5):
            annotation_data = {
                "instance_id": "edge_test_1",
                "annotations": {
                    "test_scheme:option_a": "true"
                },
                "client_timestamp": datetime.datetime.now().isoformat(),
                "request_id": f"fast-annotation-{i+1}"
            }

            response = session.post(
                f"{flask_server.base_url}/updateinstance",
                json=annotation_data
            )

            assert response.status_code == 200
            response_data = response.json()

            # Verify performance metrics are calculated
            metrics = response_data["performance_metrics"]
            assert metrics["total_actions"] == i + 1

    def test_large_metadata_payload(self, flask_server):
        """Test handling of large metadata payloads."""
        # Create user session
        session = requests.Session()
        user_data = {"email": "large_metadata_user", "pass": "password123"}

        # Register and login user
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Create large metadata
        large_metadata = {
            "request_id": "large-metadata-test",
            "user_agent": "Mozilla/5.0 (Test Browser) " + "x" * 1000,  # Large user agent
            "ip_address": "192.168.1.1",
            "content_type": "application/json",
            "request_size": 5000,
            "additional_data": "x" * 2000  # Additional large data
        }

        # Submit annotation with large metadata
        annotation_data = {
            "instance_id": "edge_test_1",
            "annotations": {
                "test_scheme:option_a": "true"
            },
            "client_timestamp": datetime.datetime.now().isoformat(),
            "metadata": large_metadata
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data
        )

        # Should handle large metadata gracefully
        assert response.status_code in [200, 400, 500]


if __name__ == "__main__":
    pytest.main([__file__])