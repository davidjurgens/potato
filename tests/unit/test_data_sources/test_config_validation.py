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


class TestValidateLiveIngestion:
    """Validation of the live_ingestion block on a database source."""

    BASE_QUERY = "SELECT id, text, created_at FROM instances"

    def _config(self, live_block, query=None, source_type="database", **extra):
        source = {
            "type": source_type,
            "id": "live_instances",
            "connection_string": "postgresql://localhost/db",
            "query": self.BASE_QUERY if query is None else query,
            **extra,
        }
        if live_block is not None:
            source["live_ingestion"] = live_block
        return {"data_sources": [source]}

    # -- happy path --------------------------------------------------------

    def test_issue_example_config_passes(self):
        """The exact YAML from issue #166 must validate."""
        config = self._config(
            {
                "enabled": True,
                "poll_interval_seconds": 5,
                "cursor_column": "created_at",
                "initial_cursor": "1970-01-01T00:00:00",
            },
            query=(
                "SELECT id, text, metadata, created_at FROM instances "
                "WHERE created_at > :cursor ORDER BY created_at, id"
            ),
        )
        validate_data_sources_config(config)  # must not raise

    def test_managed_mode_config_passes(self):
        config = self._config({
            "enabled": True,
            "poll_interval_seconds": 5,
            "cursor_column": "created_at",
            "tiebreaker_column": "id",
        })
        validate_data_sources_config(config)  # must not raise

    def test_absent_block_passes(self):
        validate_data_sources_config(self._config(None))

    def test_disabled_block_skips_deeper_checks(self):
        """A disabled block should not be held to enabled-only requirements."""
        validate_data_sources_config(self._config({"enabled": False}))

    # -- structure ---------------------------------------------------------

    def test_block_must_be_a_dictionary(self):
        with pytest.raises(ConfigValidationError, match="must be a dictionary"):
            validate_data_sources_config(self._config("yes please"))

    def test_enabled_must_be_boolean(self):
        with pytest.raises(ConfigValidationError, match="enabled must be a boolean"):
            validate_data_sources_config(self._config({"enabled": "true"}))

    def test_unknown_key_is_rejected(self):
        """A typo must not silently do nothing."""
        with pytest.raises(ConfigValidationError, match="unrecognized key 'poll_interval'"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at", "poll_interval": 5,
            }))

    def test_live_ingestion_rejected_on_non_database_source(self):
        config = {"data_sources": [{
            "type": "url",
            "url": "https://example.com/data.json",
            "live_ingestion": {"enabled": True, "cursor_column": "created_at"},
        }]}
        with pytest.raises(ConfigValidationError, match="does not support 'live_ingestion'"):
            validate_data_sources_config(config)

    # -- field values ------------------------------------------------------

    def test_poll_interval_must_be_a_number(self):
        with pytest.raises(ConfigValidationError, match="poll_interval_seconds must be a number"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at",
                "poll_interval_seconds": "five",
            }))

    def test_poll_interval_has_a_floor(self):
        with pytest.raises(ConfigValidationError, match="at least 0.5 seconds"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at",
                "poll_interval_seconds": 0.1,
            }))

    def test_poll_interval_has_a_ceiling(self):
        with pytest.raises(ConfigValidationError, match="3600"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at",
                "poll_interval_seconds": 99999,
            }))

    def test_batch_size_must_be_an_integer(self):
        with pytest.raises(ConfigValidationError, match="batch_size must be an integer"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at", "batch_size": 1.5,
            }))

    def test_batch_size_must_be_positive(self):
        with pytest.raises(ConfigValidationError, match="batch_size must be a positive integer"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at", "batch_size": 0,
            }))

    def test_overlap_seconds_must_be_non_negative(self):
        with pytest.raises(ConfigValidationError, match="overlap_seconds must be a non-negative"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at", "overlap_seconds": -1,
            }))

    def test_backoff_max_must_not_be_below_initial(self):
        with pytest.raises(ConfigValidationError, match="backoff_initial_seconds"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at",
                "backoff_initial_seconds": 10, "backoff_max_seconds": 1,
            }))

    def test_max_consecutive_failures_must_be_non_negative(self):
        with pytest.raises(ConfigValidationError, match="non-negative"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at",
                "max_consecutive_failures": -1,
            }))

    # -- cursor requirements -----------------------------------------------

    def test_cursor_column_is_required_in_managed_mode(self):
        with pytest.raises(ConfigValidationError, match="requires 'cursor_column'"):
            validate_data_sources_config(self._config({"enabled": True}))

    def test_explicit_cursor_query_requires_initial_cursor(self):
        """'col > NULL' matches nothing, forever, without a word of warning."""
        with pytest.raises(ConfigValidationError, match="initial_cursor is required"):
            validate_data_sources_config(self._config(
                {"enabled": True, "cursor_column": "created_at"},
                query="SELECT id, text, created_at FROM instances WHERE created_at > :cursor",
            ))

    def test_explicit_cursor_query_with_initial_cursor_passes(self):
        validate_data_sources_config(self._config(
            {"enabled": True, "cursor_column": "created_at", "initial_cursor": 0},
            query="SELECT id, text, created_at FROM instances WHERE created_at > :cursor",
        ))

    @pytest.mark.parametrize("column", [
        "created_at; DROP TABLE instances",
        "created_at)",
        "created at",
        "1=1 OR",
    ])
    def test_cursor_column_must_be_a_safe_identifier(self, column):
        """Identifiers are interpolated into SQL, so they must be guarded."""
        with pytest.raises(ConfigValidationError, match="not a valid SQL identifier"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": column,
            }))

    def test_tiebreaker_column_must_be_a_safe_identifier(self):
        with pytest.raises(ConfigValidationError, match="not a valid SQL identifier"):
            validate_data_sources_config(self._config({
                "enabled": True, "cursor_column": "created_at",
                "tiebreaker_column": "id; DROP TABLE x",
            }))

    def test_schema_qualified_column_is_accepted(self):
        validate_data_sources_config(self._config({
            "enabled": True, "cursor_column": "potato_live.created_at",
        }))


class TestLiveIngestionAssignmentCompat:
    """BATCH can never serve a runtime-added item, so refuse the combination."""

    def _config(self, strategy=None, enabled=True):
        config = {
            "data_sources": [{
                "type": "database",
                "id": "live_instances",
                "connection_string": "postgresql://localhost/db",
                "query": "SELECT id, text, created_at FROM instances",
                "live_ingestion": {"enabled": enabled, "cursor_column": "created_at"},
            }],
        }
        if strategy is not None:
            config["assignment_strategy"] = strategy
        return config

    def test_batch_strategy_conflicts_with_live_ingestion(self):
        from potato.server_utils.config_module import (
            validate_live_ingestion_assignment_compat,
        )
        with pytest.raises(ConfigValidationError, match="incompatible"):
            validate_live_ingestion_assignment_compat(self._config("batch"))

    def test_batch_strategy_in_dict_form_also_conflicts(self):
        from potato.server_utils.config_module import (
            validate_live_ingestion_assignment_compat,
        )
        with pytest.raises(ConfigValidationError, match="incompatible"):
            validate_live_ingestion_assignment_compat(self._config({"name": "batch"}))

    @pytest.mark.parametrize("strategy", [
        "random", "fixed_order", "least_annotated", "priority", "active_learning",
    ])
    def test_other_strategies_are_allowed(self, strategy):
        from potato.server_utils.config_module import (
            validate_live_ingestion_assignment_compat,
        )
        validate_live_ingestion_assignment_compat(self._config(strategy))

    def test_batch_is_fine_without_live_ingestion(self):
        from potato.server_utils.config_module import (
            validate_live_ingestion_assignment_compat,
        )
        validate_live_ingestion_assignment_compat(self._config("batch", enabled=False))

    def test_no_data_sources_is_fine(self):
        from potato.server_utils.config_module import (
            validate_live_ingestion_assignment_compat,
        )
        validate_live_ingestion_assignment_compat({"assignment_strategy": "batch"})
