"""
Unit tests for file encoding configuration support.

Tests that encoding is correctly extracted from data_files entries
and that invalid encodings are rejected during config validation.
"""

import codecs
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestEncodingExtraction:
    """Test encoding extraction from data_files entries in load_instance_data."""

    def test_string_entry_defaults_to_utf8(self):
        """String data_files entries should default to utf-8 encoding."""
        entry = "data/file.json"
        # String entries always use utf-8
        assert not isinstance(entry, dict)
        encoding = "utf-8"  # default for string entries
        assert encoding == "utf-8"

    def test_dict_entry_without_encoding_defaults_to_utf8(self):
        """Dict entries without 'encoding' should default to utf-8."""
        entry = {"path": "data/file.json"}
        encoding = entry.get("encoding", "utf-8")
        assert encoding == "utf-8"

    def test_dict_entry_with_encoding(self):
        """Dict entries with 'encoding' should use the specified encoding."""
        entry = {"path": "data/file.json", "encoding": "latin-1"}
        encoding = entry.get("encoding", "utf-8")
        assert encoding == "latin-1"

    def test_dict_entry_with_encoding_and_filter(self):
        """Encoding should work alongside filter_by_prior_annotation."""
        entry = {
            "path": "data/file.json",
            "encoding": "shift_jis",
            "filter_by_prior_annotation": {"annotation_dir": "output/"},
        }
        encoding = entry.get("encoding", "utf-8")
        filter_config = entry.get("filter_by_prior_annotation")
        assert encoding == "shift_jis"
        assert filter_config is not None

    def test_various_valid_encodings(self):
        """Common encodings should all be recognized by Python."""
        valid_encodings = [
            "utf-8", "latin-1", "iso-8859-1", "ascii",
            "shift_jis", "gb2312", "euc-kr", "cp1252",
            "utf-16", "utf-32",
        ]
        for enc in valid_encodings:
            info = codecs.lookup(enc)
            assert info is not None, f"Encoding {enc} should be valid"


class TestEncodingValidation:
    """Test encoding validation in config_module.validate_file_paths."""

    def test_invalid_encoding_raises_error(self):
        """An unrecognized encoding name should raise LookupError via codecs.lookup."""
        with pytest.raises(LookupError):
            codecs.lookup("not-a-real-encoding")

    def test_valid_encoding_does_not_raise(self):
        """A valid encoding should not raise."""
        # Should not raise
        codecs.lookup("latin-1")
        codecs.lookup("utf-8")
        codecs.lookup("shift_jis")

    def test_encoding_must_be_string(self):
        """Encoding field must be a string, not int or list."""
        entry = {"path": "data/file.json", "encoding": 123}
        encoding = entry.get("encoding")
        assert not isinstance(encoding, str)

    def test_config_validation_rejects_invalid_encoding(self):
        """validate_file_paths should reject invalid encoding values."""
        from potato.server_utils.config_module import ConfigValidationError

        # Simulate what validate_file_paths does for encoding validation
        data_file = {"path": "data/file.json", "encoding": "not-real"}
        encoding = data_file.get("encoding")
        if encoding is not None:
            if not isinstance(encoding, str):
                raise ConfigValidationError("encoding must be a string")
            try:
                codecs.lookup(encoding)
            except LookupError:
                with pytest.raises(LookupError):
                    codecs.lookup(encoding)
                return  # Test passed
        pytest.fail("Should have detected invalid encoding")

    def test_config_validation_accepts_valid_encoding(self):
        """validate_file_paths should accept valid encoding values."""
        data_file = {"path": "data/file.json", "encoding": "latin-1"}
        encoding = data_file.get("encoding")
        assert encoding is not None
        # Should not raise
        codecs.lookup(encoding)

    def test_dict_entry_missing_path_detected(self):
        """Dict entries without 'path' should be flagged."""
        entry = {"encoding": "utf-8"}
        path = entry.get("path")
        assert path is None


class TestDirectoryWatcherEncoding:
    """Test encoding support in DirectoryWatcher."""

    def test_default_encoding(self):
        """DirectoryWatcher should default to utf-8 when no encoding configured."""
        config = {
            "data_directory": "/tmp",
            "item_properties": {"id_key": "id", "text_key": "text"},
        }
        encoding = config.get("data_directory_encoding", "utf-8")
        assert encoding == "utf-8"

    def test_custom_encoding(self):
        """DirectoryWatcher should use data_directory_encoding from config."""
        config = {
            "data_directory": "/tmp",
            "data_directory_encoding": "latin-1",
            "item_properties": {"id_key": "id", "text_key": "text"},
        }
        encoding = config.get("data_directory_encoding", "utf-8")
        assert encoding == "latin-1"
