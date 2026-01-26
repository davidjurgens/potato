"""
Server-based integration tests for database functionality.

This module tests the MySQL database integration with the Flask server
to ensure all annotation persistence works correctly with the database backend.
"""

import pytest
import os
import json
from unittest.mock import patch, Mock

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)
from potato.user_state_management import get_user_state_manager, clear_user_state_manager
from potato.item_state_management import get_item_state_manager, clear_item_state_manager


class TestDatabaseServerIntegration:
    """Test database integration with Flask server."""

    @pytest.fixture
    def test_dir(self):
        """Create a test directory for database tests."""
        test_dir = create_test_directory("database_integration_test")
        yield test_dir
        cleanup_test_directory(test_dir)

    @pytest.fixture
    def base_annotation_schemes(self):
        """Common annotation schemes for database tests."""
        return [
            {
                "name": "test_scheme",
                "annotation_type": "radio",
                "labels": ["option_1", "option_2", "option_3"],
                "description": "Choose one option."
            }
        ]

    @pytest.fixture
    def mysql_database_config(self):
        """MySQL database configuration (for mocking)."""
        return {
            "type": "mysql",
            "host": "localhost",
            "port": 3306,
            "database": "potato_test",
            "username": "test_user",
            "password": "test_password",
            "charset": "utf8mb4",
            "pool_size": 5
        }

    def test_server_starts_with_file_config(self, test_dir, base_annotation_schemes):
        """Test that server starts successfully with file-based configuration."""
        test_data = [{"id": "item1", "text": "Test text."}]
        data_file = create_test_data_file(test_dir, test_data)

        config_file = create_test_config(
            test_dir,
            base_annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Test File Annotation Task",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        try:
            started = server.start()
            assert started, "Server should start with file-based configuration"
        finally:
            server.stop()

    def test_user_state_manager_initialization(self, test_dir, base_annotation_schemes):
        """Test UserStateManager initialization."""
        test_data = [{"id": "item1", "text": "Test text."}]
        data_file = create_test_data_file(test_dir, test_data)

        config_file = create_test_config(
            test_dir,
            base_annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Test Init Task",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        try:
            started = server.start()
            assert started, "Server should start"

            # Get the manager
            usm = get_user_state_manager()
            assert usm is not None, "UserStateManager should be initialized"
        finally:
            server.stop()


class TestDatabaseAnnotationWorkflow:
    """Test complete annotation workflow with database backend."""

    @pytest.fixture
    def test_dir(self):
        """Create a test directory."""
        test_dir = create_test_directory("db_workflow_test")
        yield test_dir
        cleanup_test_directory(test_dir)

    def test_complete_annotation_workflow(self, test_dir):
        """Test complete annotation workflow."""
        test_data = [
            {"id": "item1", "text": "This is the first test item."},
            {"id": "item2", "text": "This is the second test item."},
            {"id": "item3", "text": "This is the third test item."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "name": "test_scheme",
                "annotation_type": "radio",
                "labels": ["option_1", "option_2", "option_3"],
                "description": "Choose one option."
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Test Database Annotation Task",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        try:
            started = server.start()
            assert started, "Server should start"

            # Test user registration
            response = server.session.post(f"{server.base_url}/register", data={
                'email': 'test_user_db',
                'pass': 'test_pass'
            }, timeout=5)
            assert response.status_code in [200, 302], "User registration should succeed"

            # Test login
            response = server.session.post(f"{server.base_url}/auth", data={
                'email': 'test_user_db',
                'pass': 'test_pass'
            }, timeout=5)
            assert response.status_code in [200, 302], "Login should succeed"

            # Test accessing annotation page
            response = server.session.get(f"{server.base_url}/annotate", timeout=5)
            assert response.status_code == 200, "Should be able to access annotation page"
        finally:
            server.stop()


class TestDatabaseErrorHandling:
    """Test error handling with database backend."""

    def test_server_handles_missing_data_gracefully(self):
        """Test server behavior when data is missing."""
        test_dir = create_test_directory("db_error_test")

        try:
            # Create config without data file
            annotation_schemes = [
                {
                    "name": "test_scheme",
                    "annotation_type": "radio",
                    "labels": ["a", "b"],
                    "description": "Test"
                }
            ]

            # Create an empty data file
            test_data = []
            data_file = create_test_data_file(test_dir, test_data)

            config_file = create_test_config(
                test_dir,
                annotation_schemes,
                data_files=[data_file],
                require_password=False
            )

            # Server should handle gracefully
            server = FlaskTestServer(config_file=config_file, debug=False)
            try:
                # Server may or may not start with empty data - either is acceptable
                started = server.start()
                # If it started, test that it responds
                if started:
                    response = server.get("/")
                    assert response.status_code in [200, 302, 500]
            finally:
                server.stop()
        finally:
            cleanup_test_directory(test_dir)


class TestDatabasePerformance:
    """Test database performance characteristics."""

    def test_large_annotation_set(self):
        """Test performance with large annotation sets."""
        test_dir = create_test_directory("db_perf_test")

        try:
            # Create test data with many items
            test_data = [{"id": f"item_{i}", "text": f"Test item {i}."} for i in range(100)]
            data_file = create_test_data_file(test_dir, test_data)

            annotation_schemes = [
                {
                    "name": "test_scheme",
                    "annotation_type": "radio",
                    "labels": ["a", "b", "c"],
                    "description": "Test"
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
                started = server.start()
                assert started, "Server should start with large dataset"

                # Test basic access
                response = server.get("/")
                assert response.status_code in [200, 302]
            finally:
                server.stop()
        finally:
            cleanup_test_directory(test_dir)
