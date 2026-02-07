"""Tests for data_sources config validation."""

import pytest
from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_data_sources_config,
    _validate_data_source_by_type,
    _validate_partial_loading_config,
    _validate_data_cache_config,
)


class TestValidateDataSourcesConfig:
    """Tests for validate_data_sources_config function."""

    def test_no_data_sources_passes(self):
        """Test that missing data_sources is valid."""
        config = {"data_files": ["test.json"]}
        validate_data_sources_config(config)  # Should not raise

    def test_empty_data_sources_skipped(self):
        """Test that empty data_sources is skipped (allows using data_files)."""
        config = {"data_sources": []}
        # Empty list should be allowed - data_files can be used instead
        validate_data_sources_config(config)  # Should not raise

    def test_data_sources_must_be_list(self):
        """Test that data_sources must be a list."""
        config = {"data_sources": {"type": "file"}}
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_data_sources_config(config)
        assert "list" in str(exc_info.value).lower()

    def test_source_must_be_dict(self):
        """Test that each source must be a dict."""
        config = {"data_sources": ["not a dict"]}
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_data_sources_config(config)
        assert "dictionary" in str(exc_info.value).lower()

    def test_source_requires_type(self):
        """Test that each source requires a type."""
        config = {"data_sources": [{"path": "test.json"}]}
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_data_sources_config(config)
        assert "type" in str(exc_info.value).lower()

    def test_invalid_source_type(self):
        """Test that invalid source type raises error."""
        config = {"data_sources": [{"type": "invalid_type"}]}
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_data_sources_config(config)
        assert "invalid" in str(exc_info.value).lower()
        assert "type" in str(exc_info.value).lower()

    def test_valid_file_source(self):
        """Test valid file source config."""
        config = {
            "data_sources": [{
                "type": "file",
                "path": "data/test.json"
            }]
        }
        validate_data_sources_config(config)  # Should not raise

    def test_valid_url_source(self):
        """Test valid URL source config."""
        config = {
            "data_sources": [{
                "type": "url",
                "url": "https://example.com/data.json"
            }]
        }
        validate_data_sources_config(config)  # Should not raise


class TestValidateDataSourceByType:
    """Tests for type-specific validation."""

    def test_file_requires_path(self):
        """Test file source requires path."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type({"type": "file"}, "file", 0)
        assert "path" in str(exc_info.value).lower()

    def test_url_requires_url(self):
        """Test URL source requires url."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type({"type": "url"}, "url", 0)
        assert "url" in str(exc_info.value).lower()

    def test_url_must_start_with_http(self):
        """Test URL must start with http:// or https://."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type(
                {"type": "url", "url": "ftp://example.com/file"},
                "url", 0
            )
        assert "http" in str(exc_info.value).lower()

    def test_google_drive_requires_url_or_file_id(self):
        """Test Google Drive requires url or file_id."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type({"type": "google_drive"}, "google_drive", 0)
        assert "url" in str(exc_info.value).lower() or "file_id" in str(exc_info.value).lower()

    def test_dropbox_requires_url_or_path(self):
        """Test Dropbox requires url or path."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type({"type": "dropbox"}, "dropbox", 0)
        assert "url" in str(exc_info.value).lower() or "path" in str(exc_info.value).lower()

    def test_dropbox_path_requires_token(self):
        """Test Dropbox with path requires access_token."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type(
                {"type": "dropbox", "path": "/data/file.json"},
                "dropbox", 0
            )
        assert "access_token" in str(exc_info.value).lower()

    def test_s3_requires_bucket_and_key(self):
        """Test S3 requires bucket and key."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type({"type": "s3"}, "s3", 0)
        assert "bucket" in str(exc_info.value).lower()

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type({"type": "s3", "bucket": "test"}, "s3", 0)
        assert "key" in str(exc_info.value).lower()

    def test_huggingface_requires_dataset(self):
        """Test HuggingFace requires dataset."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type({"type": "huggingface"}, "huggingface", 0)
        assert "dataset" in str(exc_info.value).lower()

    def test_google_sheets_requires_id_and_credentials(self):
        """Test Google Sheets requires spreadsheet_id and credentials."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type({"type": "google_sheets"}, "google_sheets", 0)
        assert "spreadsheet_id" in str(exc_info.value).lower()

    def test_database_requires_connection_or_dialect(self):
        """Test database requires connection_string or dialect."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type({"type": "database"}, "database", 0)
        assert "connection_string" in str(exc_info.value).lower() or "dialect" in str(exc_info.value).lower()

    def test_database_requires_query_or_table(self):
        """Test database requires query or table."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_source_by_type(
                {"type": "database", "dialect": "sqlite", "database": "test.db"},
                "database", 0
            )
        assert "query" in str(exc_info.value).lower() or "table" in str(exc_info.value).lower()


class TestValidatePartialLoadingConfig:
    """Tests for partial_loading config validation."""

    def test_no_partial_loading_passes(self):
        """Test that missing partial_loading is valid."""
        _validate_partial_loading_config({})  # Should not raise

    def test_partial_loading_must_be_dict(self):
        """Test that partial_loading must be a dict."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_partial_loading_config({"partial_loading": "not a dict"})
        assert "dictionary" in str(exc_info.value).lower()

    def test_enabled_must_be_bool(self):
        """Test that enabled must be boolean."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_partial_loading_config({
                "partial_loading": {"enabled": "yes"}
            })
        assert "boolean" in str(exc_info.value).lower()

    def test_initial_count_must_be_positive(self):
        """Test that initial_count must be positive."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_partial_loading_config({
                "partial_loading": {"initial_count": 0}
            })
        assert "initial_count" in str(exc_info.value).lower()

    def test_batch_size_must_be_positive(self):
        """Test that batch_size must be positive."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_partial_loading_config({
                "partial_loading": {"batch_size": 0}
            })
        assert "batch_size" in str(exc_info.value).lower()

    def test_threshold_must_be_valid(self):
        """Test that auto_load_threshold must be between 0 and 1."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_partial_loading_config({
                "partial_loading": {"auto_load_threshold": 1.5}
            })
        assert "threshold" in str(exc_info.value).lower()


class TestValidateDataCacheConfig:
    """Tests for data_cache config validation."""

    def test_no_data_cache_passes(self):
        """Test that missing data_cache is valid."""
        _validate_data_cache_config({})  # Should not raise

    def test_data_cache_must_be_dict(self):
        """Test that data_cache must be a dict."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_cache_config({"data_cache": "not a dict"})
        assert "dictionary" in str(exc_info.value).lower()

    def test_ttl_must_be_non_negative(self):
        """Test that ttl_seconds must be non-negative."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_cache_config({
                "data_cache": {"ttl_seconds": -1}
            })
        assert "ttl_seconds" in str(exc_info.value).lower()

    def test_max_size_must_be_positive(self):
        """Test that max_size_mb must be positive."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_data_cache_config({
                "data_cache": {"max_size_mb": 0}
            })
        assert "max_size_mb" in str(exc_info.value).lower()
