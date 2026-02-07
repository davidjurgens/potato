"""Tests for data_sources base classes."""

import pytest
from potato.data_sources.base import (
    DataSource,
    SourceConfig,
    SourceType,
)


class TestSourceType:
    """Tests for the SourceType enum."""

    def test_all_types_defined(self):
        """Verify all expected source types are defined."""
        expected_types = [
            "file", "url", "google_drive", "dropbox",
            "s3", "huggingface", "google_sheets", "database"
        ]
        actual_types = [t.value for t in SourceType]
        assert sorted(actual_types) == sorted(expected_types)

    def test_type_values_are_lowercase(self):
        """Ensure all type values are lowercase for consistency."""
        for source_type in SourceType:
            assert source_type.value == source_type.value.lower()


class TestSourceConfig:
    """Tests for SourceConfig dataclass."""

    def test_from_dict_with_file_type(self):
        """Test creating config from file source dict."""
        config_dict = {
            "type": "file",
            "path": "data/test.jsonl",
        }
        config = SourceConfig.from_dict(config_dict, index=0)

        assert config.source_type == SourceType.FILE
        assert "file_0" in config.source_id
        assert config.enabled is True
        assert config.config == config_dict

    def test_from_dict_with_url_type(self):
        """Test creating config from URL source dict."""
        config_dict = {
            "type": "url",
            "url": "https://example.com/data.json",
        }
        config = SourceConfig.from_dict(config_dict, index=1)

        assert config.source_type == SourceType.URL
        assert "url_1" in config.source_id

    def test_from_dict_with_custom_id(self):
        """Test that custom source_id is respected."""
        config_dict = {
            "type": "file",
            "path": "data/test.jsonl",
            "id": "my_custom_source",
        }
        config = SourceConfig.from_dict(config_dict)

        assert config.source_id == "my_custom_source"

    def test_from_dict_with_source_id_key(self):
        """Test that source_id key also works."""
        config_dict = {
            "type": "file",
            "path": "data/test.jsonl",
            "source_id": "my_source",
        }
        config = SourceConfig.from_dict(config_dict)

        assert config.source_id == "my_source"

    def test_from_dict_disabled_source(self):
        """Test creating a disabled source."""
        config_dict = {
            "type": "file",
            "path": "data/test.jsonl",
            "enabled": False,
        }
        config = SourceConfig.from_dict(config_dict)

        assert config.enabled is False

    def test_from_dict_missing_type_raises(self):
        """Test that missing type raises ValueError."""
        config_dict = {"path": "data/test.jsonl"}

        with pytest.raises(ValueError) as exc_info:
            SourceConfig.from_dict(config_dict)

        assert "type" in str(exc_info.value).lower()

    def test_from_dict_invalid_type_raises(self):
        """Test that invalid type raises ValueError."""
        config_dict = {
            "type": "invalid_type",
            "path": "data/test.jsonl",
        }

        with pytest.raises(ValueError) as exc_info:
            SourceConfig.from_dict(config_dict)

        assert "invalid" in str(exc_info.value).lower()
        # Should list valid types in error message
        assert "file" in str(exc_info.value).lower()

    def test_all_source_types_can_be_created(self):
        """Test that all source types can create configs."""
        type_configs = {
            "file": {"path": "test.json"},
            "url": {"url": "https://example.com/data.json"},
            "google_drive": {"file_id": "abc123"},
            "dropbox": {"url": "https://dropbox.com/file"},
            "s3": {"bucket": "test", "key": "data.json"},
            "huggingface": {"dataset": "squad"},
            "google_sheets": {"spreadsheet_id": "abc123"},
            "database": {"dialect": "sqlite", "database": "test.db", "table": "items"},
        }

        for type_name, extra_config in type_configs.items():
            config_dict = {"type": type_name, **extra_config}
            config = SourceConfig.from_dict(config_dict)
            assert config.source_type == SourceType(type_name)
