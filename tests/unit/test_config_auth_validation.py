"""
Unit tests for authentication config validation.
"""

import pytest
from potato.server_utils.config_module import (
    validate_authentication_config,
    ConfigValidationError,
)


class TestDatabaseAuthValidation:
    """Test database auth config validation."""

    def test_database_with_user_config_path_raises(self):
        config_data = {
            "authentication": {
                "method": "database",
                "database_url": "sqlite:///test.db",
                "user_config_path": "/some/path/user_config.json",
            }
        }
        with pytest.raises(ConfigValidationError, match="cannot be used with method 'database'"):
            validate_authentication_config(config_data)

    def test_database_with_invalid_url_raises(self):
        config_data = {
            "authentication": {
                "method": "database",
                "database_url": "mysql://localhost/db",
            }
        }
        with pytest.raises(ConfigValidationError, match="sqlite:///.*postgresql://"):
            validate_authentication_config(config_data)

    def test_database_with_sqlite_url_passes(self):
        config_data = {
            "authentication": {
                "method": "database",
                "database_url": "sqlite:///data/auth.db",
            }
        }
        # Should not raise
        validate_authentication_config(config_data)

    def test_database_with_postgresql_url_passes(self):
        config_data = {
            "authentication": {
                "method": "database",
                "database_url": "postgresql://user:pass@host/dbname",
            }
        }
        # Should not raise
        validate_authentication_config(config_data)

    def test_database_without_url_passes(self):
        """When no database_url is given, defaults are used."""
        config_data = {
            "authentication": {
                "method": "database",
            }
        }
        # Should not raise (will use POTATO_DB_CONNECTION env or default)
        validate_authentication_config(config_data)

    def test_in_memory_passes(self):
        config_data = {
            "authentication": {
                "method": "in_memory",
            }
        }
        validate_authentication_config(config_data)

    def test_in_memory_with_user_config_path_passes(self):
        config_data = {
            "authentication": {
                "method": "in_memory",
                "user_config_path": "/some/path/user_config.json",
            }
        }
        validate_authentication_config(config_data)

    def test_no_authentication_section_passes(self):
        config_data = {}
        validate_authentication_config(config_data)

    def test_invalid_method_raises(self):
        config_data = {
            "authentication": {
                "method": "invalid_method",
            }
        }
        with pytest.raises(ConfigValidationError, match="must be one of"):
            validate_authentication_config(config_data)
