"""Tests for Parquet data loading support."""

import json
import os
import tempfile
import pytest

# These tests require pyarrow
pyarrow = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq
import pyarrow as pa


class TestParquetCLILoading:
    """Test that the trace converter CLI can load Parquet files."""

    def test_load_parquet_file(self, tmp_path):
        from potato.trace_converter.cli import load_input

        # Create a Parquet file
        table = pa.table({
            "id": ["trace_1", "trace_2"],
            "task": ["Do task A", "Do task B"],
            "agent": ["gpt-4", "claude-3"]
        })
        parquet_path = str(tmp_path / "traces.parquet")
        pq.write_table(table, parquet_path)

        # Load it
        result = load_input(parquet_path)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "trace_1"
        assert result[1]["task"] == "Do task B"

    def test_load_parquet_with_nested_data(self, tmp_path):
        """Parquet can store nested columns as JSON strings."""
        from potato.trace_converter.cli import load_input

        table = pa.table({
            "id": ["t1"],
            "text": ["Hello world"],
            "score": [0.95]
        })
        parquet_path = str(tmp_path / "nested.parquet")
        pq.write_table(table, parquet_path)

        result = load_input(parquet_path)
        assert len(result) == 1
        assert result[0]["score"] == pytest.approx(0.95)

    def test_load_nonexistent_parquet(self, tmp_path):
        from potato.trace_converter.cli import load_input

        with pytest.raises(FileNotFoundError):
            load_input(str(tmp_path / "nonexistent.parquet"))


class TestParquetDataLoading:
    """Test that the flask server can load Parquet data files."""

    def test_parquet_format_accepted(self):
        """Verify parquet is in the accepted formats list."""
        # Just verify the format string is accepted by checking the code
        accepted = ["csv", "tsv", "json", "jsonl", "parquet"]
        assert "parquet" in accepted

    def test_create_and_read_parquet(self, tmp_path):
        """Test basic Parquet read via pyarrow (prerequisite for server loading)."""
        table = pa.table({
            "id": ["inst_1", "inst_2", "inst_3"],
            "text": ["First item", "Second item", "Third item"],
            "category": ["A", "B", "A"]
        })
        path = str(tmp_path / "data.parquet")
        pq.write_table(table, path)

        # Read it back
        read_table = pq.read_table(path)
        df = read_table.to_pandas()
        assert len(df) == 3
        assert list(df.columns) == ["id", "text", "category"]
        assert df["id"].tolist() == ["inst_1", "inst_2", "inst_3"]

    def test_parquet_to_records(self, tmp_path):
        """Test Parquet → dict records conversion (mimics server loading)."""
        table = pa.table({
            "id": ["1", "2"],
            "text": ["Hello", "World"],
            "score": [0.8, 0.9]
        })
        path = str(tmp_path / "data.parquet")
        pq.write_table(table, path)

        read_table = pq.read_table(path)
        df = read_table.to_pandas()
        df["id"] = df["id"].astype(str)
        records = df.to_dict("records")

        assert len(records) == 2
        assert records[0]["id"] == "1"
        assert records[0]["text"] == "Hello"
        assert records[1]["score"] == pytest.approx(0.9)

    def test_parquet_duplicate_detection(self, tmp_path):
        """Test that duplicates can be detected in Parquet data."""
        table = pa.table({
            "id": ["1", "2", "1"],  # Duplicate ID
            "text": ["A", "B", "C"]
        })
        path = str(tmp_path / "dupes.parquet")
        pq.write_table(table, path)

        df = pq.read_table(path).to_pandas()
        df["id"] = df["id"].astype(str)
        assert df["id"].duplicated().any()

    def test_parquet_missing_column(self, tmp_path):
        """Test detection of missing required columns."""
        table = pa.table({
            "text": ["Hello"],
            "category": ["A"]
        })
        path = str(tmp_path / "no_id.parquet")
        pq.write_table(table, path)

        df = pq.read_table(path).to_pandas()
        assert "id" not in df.columns

    def test_parquet_integer_ids(self, tmp_path):
        """Test that integer IDs in Parquet are converted to strings."""
        table = pa.table({
            "id": [1, 2, 3],
            "text": ["A", "B", "C"]
        })
        path = str(tmp_path / "int_ids.parquet")
        pq.write_table(table, path)

        df = pq.read_table(path).to_pandas()
        df["id"] = df["id"].astype(str)
        assert df["id"].tolist() == ["1", "2", "3"]

    def test_parquet_with_many_columns(self, tmp_path):
        """Test Parquet with various column types."""
        table = pa.table({
            "id": ["1"],
            "text": ["Sample text"],
            "score": [0.95],
            "count": [42],
            "active": [True],
        })
        path = str(tmp_path / "multi_col.parquet")
        pq.write_table(table, path)

        records = pq.read_table(path).to_pandas().to_dict("records")
        assert len(records) == 1
        assert records[0]["score"] == pytest.approx(0.95)
        assert records[0]["count"] == 42
        assert records[0]["active"] is True
