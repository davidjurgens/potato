#!/usr/bin/env python3
"""
Example test demonstrating secure patterns for server tests.

This test shows how to use the test utilities to create secure test configurations
that comply with path security requirements.
"""

import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    create_span_annotation_config,
    create_comprehensive_annotation_config,
    TestConfigManager
)


class TestSecurePatterns:
    """Example test class demonstrating secure test patterns."""

    def test_basic_secure_pattern(self):
        """Example of basic secure test pattern using TestConfigManager."""
        # Define annotation schemes
        annotation_schemes = [
            {
                "name": "likert_rating",
                "annotation_type": "likert",
                "min_label": "1",
                "max_label": "5",
                "size": 5,
                "description": "Rate on a scale of 1-5"
            }
        ]

        # Use TestConfigManager for automatic cleanup
        with TestConfigManager("basic_test", annotation_schemes) as test_config:
            # Create server with secure config
            server = FlaskTestServer(
                port=find_free_port(),
                debug=False,
                config_file=test_config.config_path
            )

            try:
                # Start server
                assert server.start(), "Failed to start Flask server"

                # Test the server
                session = requests.Session()

                # Register and login user
                user_data = {"email": "test_user", "pass": "test_password"}
                session.post(f"{server.base_url}/register", data=user_data)
                session.post(f"{server.base_url}/auth", data=user_data)

                # Test endpoint
                response = session.get(f"{server.base_url}/annotate")
                assert response.status_code == 200

            finally:
                server.stop()
                # TestConfigManager handles directory cleanup automatically

    def test_span_annotation_secure_pattern(self):
        """Example of span annotation test using secure patterns."""
        # Use the span annotation utility
        test_dir = create_test_directory("span_test")

        try:
            config_file, data_file = create_span_annotation_config(
                test_dir,
                annotation_task_name="Secure Span Test",
                require_password=False
            )

            # Create server
            server = FlaskTestServer(
                port=find_free_port(),
                debug=False,
                config_file=config_file
            )

            try:
                # Start server
                assert server.start(), "Failed to start Flask server"

                # Test span annotation functionality
                session = requests.Session()

                # Register and login user
                user_data = {"email": "span_user", "pass": "test_password"}
                session.post(f"{server.base_url}/register", data=user_data)
                session.post(f"{server.base_url}/auth", data=user_data)

                # Test span annotation endpoint
                response = session.get(f"{server.base_url}/api/schemas")
                assert response.status_code == 200

                # Test span data endpoint
                response = session.get(f"{server.base_url}/api/spans/1")
                assert response.status_code in [200, 404]  # 404 is expected if no spans exist

            finally:
                server.stop()

        finally:
            # Clean up manually since we didn't use TestConfigManager
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(test_dir)

    def test_comprehensive_annotation_secure_pattern(self):
        """Example of comprehensive annotation test using secure patterns."""
        # Use the comprehensive annotation utility
        test_dir = create_test_directory("comprehensive_test")

        try:
            config_file, data_file = create_comprehensive_annotation_config(
                test_dir,
                annotation_task_name="Comprehensive Test",
                require_password=False
            )

            # Create server
            server = FlaskTestServer(
                port=find_free_port(),
                debug=False,
                config_file=config_file
            )

            try:
                # Start server
                assert server.start(), "Failed to start Flask server"

                # Test multiple annotation types
                session = requests.Session()

                # Register and login user
                user_data = {"email": "comp_user", "pass": "test_password"}
                session.post(f"{server.base_url}/register", data=user_data)
                session.post(f"{server.base_url}/auth", data=user_data)

                # Test annotation submission
                annotation_data = {
                    "instance_id": "1",
                    "type": "likert",
                    "schema": "likert_rating",
                    "state": [{"name": "likert_rating", "value": "3"}]
                }

                response = session.post(
                    f"{server.base_url}/updateinstance",
                    json=annotation_data
                )
                assert response.status_code == 200

            finally:
                server.stop()

        finally:
            # Clean up manually
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(test_dir)

    def test_custom_config_secure_pattern(self):
        """Example of creating custom test configuration securely."""
        # Create test directory
        test_dir = create_test_directory("custom_test")

        try:
            # Create custom test data
            test_data = [
                {"id": "custom_1", "text": "Custom test item 1"},
                {"id": "custom_2", "text": "Custom test item 2"}
            ]
            data_file = create_test_data_file(test_dir, test_data, "custom_data.jsonl")

            # Create custom annotation schemes
            annotation_schemes = [
                {
                    "name": "custom_radio",
                    "annotation_type": "radio",
                    "labels": ["option_a", "option_b"],
                    "description": "Custom radio choice"
                },
                {
                    "name": "custom_text",
                    "annotation_type": "text",
                    "description": "Custom text input"
                }
            ]

            # Create config using test utilities
            config_file = create_test_config(
                test_dir,
                annotation_schemes,
                data_files=[data_file],
                annotation_task_name="Custom Test",
                require_password=False,
                debug=False
            )

            # Create server
            server = FlaskTestServer(
                port=find_free_port(),
                debug=False,
                config_file=config_file
            )

            try:
                # Start server
                assert server.start(), "Failed to start Flask server"

                # Test custom functionality
                session = requests.Session()

                # Register and login user
                user_data = {"email": "custom_user", "pass": "test_password"}
                session.post(f"{server.base_url}/register", data=user_data)
                session.post(f"{server.base_url}/auth", data=user_data)

                # Test custom annotation
                annotation_data = {
                    "instance_id": "custom_1",
                    "type": "radio",
                    "schema": "custom_radio",
                    "state": [{"name": "custom_radio", "value": "option_a"}]
                }

                response = session.post(
                    f"{server.base_url}/updateinstance",
                    json=annotation_data
                )
                assert response.status_code == 200

            finally:
                server.stop()

        finally:
            # Clean up manually
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(test_dir)


class TestSecurePatternsWithFixtures:
    """Example test class using pytest fixtures with secure patterns."""

    @pytest.fixture(scope="class")
    def secure_server(self):
        """Create a secure test server using TestConfigManager."""
        annotation_schemes = [
            {
                "name": "fixture_test",
                "annotation_type": "radio",
                "labels": ["yes", "no"],
                "description": "Test fixture annotation"
            }
        ]

        with TestConfigManager("fixture_test", annotation_schemes) as test_config:
            server = FlaskTestServer(
                port=find_free_port(),
                debug=False,
                config_file=test_config.config_path
            )

            if not server.start():
                pytest.fail("Failed to start Flask server")

            yield server

            server.stop()
            # TestConfigManager handles cleanup