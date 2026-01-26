#!/usr/bin/env python3
"""
Integration tests using the FlaskTestServer.
Demonstrates how to use the FlaskTestServer for testing Flask endpoints.
"""

import pytest
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestFlaskIntegration:
    """Test Flask server integration using the FlaskTestServer."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a test server fixture with proper configuration."""
        test_dir = create_test_directory("flask_integration_test")

        test_data = [
            {"id": "test_1", "text": "This is test item 1."},
            {"id": "test_2", "text": "This is test item 2."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "Select sentiment",
                "labels": ["positive", "negative", "neutral"]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Test Annotation Task",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_server_starts_and_responds(self):
        """Test that the server starts and responds to basic requests."""
        # Server should be started by fixture
        assert self.server.is_server_running()

        # Test root endpoint (should redirect to auth or show login)
        response = self.server.get("/")
        assert response.status_code in [200, 302]  # 302 is redirect, 200 is success

    def test_login_endpoint(self):
        """Test the login endpoint is accessible."""
        response = self.server.get("/login")
        assert response.status_code == 200

    def test_server_configuration(self):
        """Test that the server is configured with test data."""
        response = self.server.get("/login")
        assert response.status_code == 200

        # Check that the response contains expected content
        content = response.text
        assert "Test Annotation Task" in content or "annotation" in content.lower() or "login" in content.lower()

    def test_multiple_requests(self):
        """Test that the server can handle multiple requests."""
        # Make several requests to ensure server stability
        for i in range(3):
            response = self.server.get("/")
            assert response.status_code in [200, 302]


def test_flask_server_factory():
    """Test the FlaskTestServer factory function."""
    test_dir = create_test_directory("factory_test")

    try:
        test_data = [{"id": "test_1", "text": "Test item."}]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "test",
                "description": "Test",
                "labels": ["a", "b"]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        try:
            # Test server startup
            assert server.start()
            assert server.is_server_running()

            # Test basic request
            response = server.get("/")
            assert response.status_code in [200, 302]
        finally:
            server.stop()
    finally:
        cleanup_test_directory(test_dir)


def test_server_context_manager():
    """Test the server context manager."""
    test_dir = create_test_directory("context_test")

    try:
        test_data = [{"id": "test_1", "text": "Test item."}]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "test",
                "description": "Test",
                "labels": ["a", "b"]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        with server.server_context():
            assert server.is_server_running()
            response = server.get("/")
            assert response.status_code in [200, 302]
    finally:
        cleanup_test_directory(test_dir)
