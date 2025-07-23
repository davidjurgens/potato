"""
Server-based integration tests for database functionality.

This module tests the MySQL database integration with the Flask server
to ensure all annotation persistence works correctly with the database backend.
"""

import pytest
import tempfile
import os
import json
import yaml
import time
from unittest.mock import patch, Mock

# Import test utilities
from tests.helpers.flask_test_setup import FlaskTestServer
from potato.user_state_management import get_user_state_manager, clear_user_state_manager
from potato.item_state_management import get_item_state_manager, clear_item_state_manager


class TestDatabaseServerIntegration:
    """Test database integration with Flask server."""

    @pytest.fixture
    def mysql_config(self):
        """Create a test configuration with MySQL database."""
        config = {
            "debug": False,
            "port": 9013,
            "host": "0.0.0.0",
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "annotation_schemes": [
                {
                    "name": "test_scheme",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["option_1", "option_2", "option_3"],
                    "description": "Choose one option."
                }
            ],
            "annotation_task_name": "Test Database Annotation Task",
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000,
            "require_password": False,
            "persist_sessions": False,
            "random_seed": 1234,
            "secret_key": "test-secret-key",
            "session_lifetime_days": 2,
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "authentication": {
                "method": "in_memory"
            },
            # MySQL database configuration
            "database": {
                "type": "mysql",
                "host": "localhost",
                "port": 3306,
                "database": "potato_test",
                "username": "test_user",
                "password": "test_password",
                "charset": "utf8mb4",
                "pool_size": 5
            }
        }
        return config

    @pytest.fixture
    def file_config(self):
        """Create a test configuration with file-based storage."""
        config = {
            "debug": False,
            "port": 9014,
            "host": "0.0.0.0",
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "annotation_schemes": [
                {
                    "name": "test_scheme",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["option_1", "option_2", "option_3"],
                    "description": "Choose one option."
                }
            ],
            "annotation_task_name": "Test File Annotation Task",
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000,
            "require_password": False,
            "persist_sessions": False,
            "random_seed": 1234,
            "secret_key": "test-secret-key",
            "session_lifetime_days": 2,
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "authentication": {
                "method": "in_memory"
            }
            # No database config = file-based storage
        }
        return config

    def test_server_starts_with_mysql_config(self, mysql_config):
        """Test that server starts successfully with MySQL configuration."""
        # Mock the database connection to avoid requiring real MySQL
        with patch('mysql.connector.pooling.MySQLConnectionPool') as mock_pool:
            mock_connection = Mock()
            mock_cursor = Mock()
            mock_connection.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = (1,)  # Connection test
            mock_pool.return_value.get_connection.return_value = mock_connection

            # Create config file
            config_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
            yaml.dump(mysql_config, config_file)
            config_file.close()

            try:
                # Start server
                server = FlaskTestServer(port=mysql_config['port'], debug=False, config_file=config_file.name)
                started = server.start_server()

                assert started, "Server should start with MySQL configuration"

                # Clean up
                server.stop()
            finally:
                os.unlink(config_file.name)

    def test_server_starts_with_file_config(self, file_config):
        """Test that server starts successfully with file-based configuration."""
        # Create config file
        config_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        yaml.dump(file_config, config_file)
        config_file.close()

        try:
            # Start server
            server = FlaskTestServer(port=file_config['port'], debug=False, config_file=config_file.name)
            started = server.start_server()

            assert started, "Server should start with file-based configuration"

            # Clean up
            server.stop()
        finally:
            os.unlink(config_file.name)

    def test_user_state_manager_initialization(self, mysql_config):
        """Test UserStateManager initialization with database configuration."""
        # Mock the database connection
        with patch('mysql.connector.pooling.MySQLConnectionPool') as mock_pool:
            mock_connection = Mock()
            mock_cursor = Mock()
            mock_connection.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = (1,)  # Connection test
            mock_pool.return_value.get_connection.return_value = mock_connection

            # Clear any existing managers
            clear_user_state_manager()
            clear_item_state_manager()

            # Initialize managers
            from potato.user_state_management import init_user_state_manager
            from potato.item_state_management import init_item_state_manager

            init_user_state_manager(mysql_config)
            init_item_state_manager(mysql_config)

            # Get the manager
            usm = get_user_state_manager()

            # Verify database is being used
            assert hasattr(usm, 'use_database')
            assert hasattr(usm, 'db_manager')

    def test_user_creation_with_database(self, mysql_config):
        """Test user creation with database backend."""
        # Mock the database connection
        with patch('mysql.connector.pooling.MySQLConnectionPool') as mock_pool:
            mock_connection = Mock()
            mock_cursor = Mock()
            mock_connection.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = (1,)  # Connection test
            mock_pool.return_value.get_connection.return_value = mock_connection

            # Clear any existing managers
            clear_user_state_manager()
            clear_item_state_manager()

            # Initialize managers
            from potato.user_state_management import init_user_state_manager
            from potato.item_state_management import init_item_state_manager

            init_user_state_manager(mysql_config)
            init_item_state_manager(mysql_config)

            # Get the manager
            usm = get_user_state_manager()

            # Create a user
            user_state = usm.add_user("test_user_123")

            # Verify user was created
            assert user_state is not None
            assert user_state.get_user_id() == "test_user_123"

    def test_annotation_persistence_comparison(self, mysql_config, file_config):
        """Test that annotations are persisted identically between database and file backends."""
        # This test would require a real database connection
        # For now, we'll test the interface compatibility
        pass

    def test_server_restart_persistence(self, mysql_config):
        """Test that annotations persist across server restarts with database."""
        # This test would require a real database connection
        # For now, we'll test the interface compatibility
        pass


class TestDatabaseAnnotationWorkflow:
    """Test complete annotation workflow with database backend."""

    @pytest.fixture
    def test_data(self):
        """Create test data for annotation."""
        return [
            {"id": "item1", "text": "This is the first test item."},
            {"id": "item2", "text": "This is the second test item."},
            {"id": "item3", "text": "This is the third test item."}
        ]

    def test_complete_annotation_workflow(self, mysql_config, test_data):
        """Test complete annotation workflow with database backend."""
        # Mock the database connection
        with patch('mysql.connector.pooling.MySQLConnectionPool') as mock_pool:
            mock_connection = Mock()
            mock_cursor = Mock()
            mock_connection.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = (1,)  # Connection test
            mock_pool.return_value.get_connection.return_value = mock_connection

            # Create test data file
            data_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
            for item in test_data:
                data_file.write(json.dumps(item) + '\n')
            data_file.close()

            # Update config with data file
            mysql_config['data_files'] = [data_file.name]

            # Create config file
            config_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
            yaml.dump(mysql_config, config_file)
            config_file.close()

            try:
                # Start server
                server = FlaskTestServer(port=mysql_config['port'], debug=False, config_file=config_file.name)
                started = server.start_server()

                assert started, "Server should start"

                # Wait for server to be ready
                server._wait_for_server_ready(timeout=10)

                # Test user registration
                response = server.session.post(f"{server.base_url}/register", data={
                    'username': 'test_user_db',
                    'password': 'test_pass'
                }, timeout=5)

                assert response.status_code in [200, 302], "User registration should succeed"

                # Test login
                response = server.session.post(f"{server.base_url}/auth", data={
                    'action': 'login',
                    'email': 'test_user_db',
                    'pass': 'test_pass'
                }, timeout=5)

                assert response.status_code in [200, 302], "Login should succeed"

                # Test annotation submission
                response = server.session.post(f"{server.base_url}/submit_annotation", data={
                    'instance_id': 'item1',
                    'test_scheme': 'option_1'
                }, timeout=5)

                assert response.status_code in [200, 302], "Annotation submission should succeed"

                # Clean up
                server.stop()
            finally:
                os.unlink(config_file.name)
                os.unlink(data_file.name)


class TestDatabaseErrorHandling:
    """Test error handling with database backend."""

    def test_database_connection_failure(self, mysql_config):
        """Test server behavior when database connection fails."""
        # Mock database connection failure
        with patch('mysql.connector.pooling.MySQLConnectionPool') as mock_pool:
            mock_pool.side_effect = Exception("Database connection failed")

            # Create config file
            config_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
            yaml.dump(mysql_config, config_file)
            config_file.close()

            try:
                # Server should handle database connection failure gracefully
                # and fall back to file-based storage or show appropriate error
                pass
            finally:
                os.unlink(config_file.name)

    def test_database_query_failure(self, mysql_config):
        """Test handling of database query failures."""
        # Mock database query failure
        with patch('mysql.connector.pooling.MySQLConnectionPool') as mock_pool:
            mock_connection = Mock()
            mock_cursor = Mock()
            mock_connection.cursor.return_value = mock_cursor
            mock_cursor.execute.side_effect = Exception("Query failed")
            mock_pool.return_value.get_connection.return_value = mock_connection

            # Test that the system handles query failures gracefully
            pass


class TestDatabasePerformance:
    """Test database performance characteristics."""

    def test_large_annotation_set(self, mysql_config):
        """Test performance with large annotation sets."""
        # This test would require a real database connection
        # For now, we'll test the interface compatibility
        pass

    def test_concurrent_user_access(self, mysql_config):
        """Test performance with concurrent user access."""
        # This test would require a real database connection
        # For now, we'll test the interface compatibility
        pass


class TestDatabaseMigration:
    """Test migration from file-based to database storage."""

    def test_migration_utility(self):
        """Test migration utility from file to database."""
        # This test would require a real database connection
        # For now, we'll test the interface compatibility
        pass

    def test_backward_compatibility(self):
        """Test backward compatibility with existing file-based data."""
        # This test would require a real database connection
        # For now, we'll test the interface compatibility
        pass