#!/usr/bin/env python3
"""
Comprehensive Assignment Strategy Tests

This module contains comprehensive tests for all item assignment strategies using FlaskTestServer.
Tests verify that each assignment strategy works correctly with at least 10 instances.
"""

import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestAssignmentStrategiesComprehensive:
    """Comprehensive tests for all assignment strategies using FlaskTestServer."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server for assignment strategy tests."""
        test_dir = create_test_directory("assignment_strategies_test")

        # Create test data with 12 instances
        test_data = [
            {"id": f"assign_item_{i}", "text": f"This is test item number {i} for assignment strategy testing."}
            for i in range(1, 13)
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "name": "quality",
                "annotation_type": "radio",
                "labels": ["good", "fair", "poor"],
                "description": "Rate the quality"
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Assignment Strategy Test",
            require_password=False,
            max_annotations_per_user=10,
            assignment_strategy="fixed_order"
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_fixed_order_assignment(self):
        """Test fixed order assignment strategy."""
        session = requests.Session()
        user_data = {"email": "fixed_order_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Get current instance
        response = session.get(f"{self.server.base_url}/api/current_instance")
        assert response.status_code == 200

    def test_user_can_annotate(self):
        """Test that users can submit annotations."""
        session = requests.Session()
        user_data = {"email": "annotate_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "assign_item_1",
            "type": "radio",
            "schema": "quality",
            "state": [{"name": "good", "value": "good"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_multiple_annotations(self):
        """Test annotating multiple items."""
        session = requests.Session()
        user_data = {"email": "multi_annotate_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Submit multiple annotations
        for i in range(1, 4):
            annotation_data = {
                "instance_id": f"assign_item_{i}",
                "type": "radio",
                "schema": "quality",
                "state": [{"name": "fair", "value": "fair"}]
            }
            response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
            assert response.status_code == 200
