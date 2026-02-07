"""Tests for LocalFileSource."""

import json
import os
import tempfile
import pytest
from potato.data_sources.base import SourceConfig
from potato.data_sources.sources.local_source import LocalFileSource


class TestLocalFileSource:
    """Tests for LocalFileSource."""

    @pytest.fixture
    def json_file(self, tmp_path):
        """Create a temporary JSON file."""
        data = [
            {"id": "1", "text": "First item"},
            {"id": "2", "text": "Second item"},
            {"id": "3", "text": "Third item"},
        ]
        file_path = tmp_path / "test.json"
        file_path.write_text(json.dumps(data))
        return str(file_path)

    @pytest.fixture
    def jsonl_file(self, tmp_path):
        """Create a temporary JSONL file."""
        items = [
            {"id": "1", "text": "Line one"},
            {"id": "2", "text": "Line two"},
            {"id": "3", "text": "Line three"},
        ]
        file_path = tmp_path / "test.jsonl"
        file_path.write_text("\n".join(json.dumps(item) for item in items))
        return str(file_path)

    @pytest.fixture
    def csv_file(self, tmp_path):
        """Create a temporary CSV file."""
        content = "id,text,label\n1,First text,A\n2,Second text,B\n3,Third text,C"
        file_path = tmp_path / "test.csv"
        file_path.write_text(content)
        return str(file_path)

    @pytest.fixture
    def tsv_file(self, tmp_path):
        """Create a temporary TSV file."""
        content = "id\ttext\tlabel\n1\tFirst text\tA\n2\tSecond text\tB"
        file_path = tmp_path / "test.tsv"
        file_path.write_text(content)
        return str(file_path)

    def test_validate_config_requires_path(self):
        """Test that path is required."""
        config = SourceConfig.from_dict({"type": "file", "path": ""})
        source = LocalFileSource(config)
        errors = source.validate_config()

        assert len(errors) > 0
        assert any("path" in e.lower() for e in errors)

    def test_validate_config_unsupported_extension(self):
        """Test that unsupported extensions are rejected."""
        config = SourceConfig.from_dict({"type": "file", "path": "data.xml"})
        source = LocalFileSource(config)
        errors = source.validate_config()

        assert len(errors) > 0
        assert any("extension" in e.lower() for e in errors)

    def test_is_available_existing_file(self, json_file):
        """Test is_available returns True for existing file."""
        config = SourceConfig.from_dict({"type": "file", "path": json_file})
        source = LocalFileSource(config)

        assert source.is_available() is True

    def test_is_available_missing_file(self):
        """Test is_available returns False for missing file."""
        config = SourceConfig.from_dict({"type": "file", "path": "/nonexistent/file.json"})
        source = LocalFileSource(config)

        assert source.is_available() is False

    def test_read_json_array(self, json_file):
        """Test reading JSON array file."""
        config = SourceConfig.from_dict({"type": "file", "path": json_file})
        source = LocalFileSource(config)

        items = list(source.read_items())

        assert len(items) == 3
        assert items[0]["id"] == "1"
        assert items[1]["text"] == "Second item"

    def test_read_jsonl(self, jsonl_file):
        """Test reading JSONL file."""
        config = SourceConfig.from_dict({"type": "file", "path": jsonl_file})
        source = LocalFileSource(config)

        items = list(source.read_items())

        assert len(items) == 3
        assert items[0]["id"] == "1"
        assert items[2]["text"] == "Line three"

    def test_read_csv(self, csv_file):
        """Test reading CSV file."""
        config = SourceConfig.from_dict({"type": "file", "path": csv_file})
        source = LocalFileSource(config)

        items = list(source.read_items())

        assert len(items) == 3
        assert items[0]["id"] == "1"
        assert items[0]["text"] == "First text"
        assert items[0]["label"] == "A"

    def test_read_tsv(self, tsv_file):
        """Test reading TSV file."""
        config = SourceConfig.from_dict({"type": "file", "path": tsv_file})
        source = LocalFileSource(config)

        items = list(source.read_items())

        assert len(items) == 2
        assert items[0]["id"] == "1"
        assert items[1]["text"] == "Second text"

    def test_read_items_with_start(self, json_file):
        """Test reading with start offset."""
        config = SourceConfig.from_dict({"type": "file", "path": json_file})
        source = LocalFileSource(config)

        items = list(source.read_items(start=1))

        assert len(items) == 2
        assert items[0]["id"] == "2"

    def test_read_items_with_count(self, json_file):
        """Test reading with count limit."""
        config = SourceConfig.from_dict({"type": "file", "path": json_file})
        source = LocalFileSource(config)

        items = list(source.read_items(count=2))

        assert len(items) == 2
        assert items[0]["id"] == "1"
        assert items[1]["id"] == "2"

    def test_read_items_with_start_and_count(self, json_file):
        """Test reading with both start and count."""
        config = SourceConfig.from_dict({"type": "file", "path": json_file})
        source = LocalFileSource(config)

        items = list(source.read_items(start=1, count=1))

        assert len(items) == 1
        assert items[0]["id"] == "2"

    def test_get_total_count(self, json_file):
        """Test getting total item count."""
        config = SourceConfig.from_dict({"type": "file", "path": json_file})
        source = LocalFileSource(config)

        count = source.get_total_count()

        assert count == 3

    def test_supports_partial_reading(self, json_file):
        """Test that local files support partial reading."""
        config = SourceConfig.from_dict({"type": "file", "path": json_file})
        source = LocalFileSource(config)

        assert source.supports_partial_reading() is True

    def test_get_source_id(self, json_file):
        """Test getting source ID."""
        config = SourceConfig.from_dict({
            "type": "file",
            "path": json_file,
            "id": "my_source"
        })
        source = LocalFileSource(config)

        assert source.get_source_id() == "my_source"

    def test_empty_lines_in_jsonl(self, tmp_path):
        """Test that empty lines in JSONL are skipped."""
        file_path = tmp_path / "test.jsonl"
        content = '{"id": "1", "text": "a"}\n\n{"id": "2", "text": "b"}\n'
        file_path.write_text(content)

        config = SourceConfig.from_dict({"type": "file", "path": str(file_path)})
        source = LocalFileSource(config)
        items = list(source.read_items())

        assert len(items) == 2
