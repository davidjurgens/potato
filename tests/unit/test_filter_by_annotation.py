"""
Tests for filter_by_annotation module.

Tests both the CLI functionality and the programmatic API for filtering
data items based on prior annotation decisions.
"""

import pytest
import json
import os
import tempfile
from pathlib import Path

from potato.filter_by_annotation import (
    load_annotations_from_dir,
    load_data_file,
    filter_items_by_annotation,
    get_annotation_summary,
)


class TestLoadAnnotationsFromDir:
    """Tests for loading annotations from directory."""

    def test_load_from_empty_dir(self, tmp_path):
        """Empty directory returns empty dict."""
        annotations = load_annotations_from_dir(str(tmp_path))
        assert annotations == {}

    def test_load_from_nonexistent_dir(self, tmp_path):
        """Nonexistent directory returns empty dict."""
        annotations = load_annotations_from_dir(str(tmp_path / "nonexistent"))
        assert annotations == {}

    def test_load_triage_annotations(self, tmp_path):
        """Load triage annotations from user_state.json."""
        # Create user directory and state file
        user_dir = tmp_path / "user1"
        user_dir.mkdir()

        user_state = {
            "user_id": "user1",
            "instance_id_to_label_to_value": {
                "item_001": [
                    [{"schema": "data_quality", "name": "accept"}, "accept"]
                ],
                "item_002": [
                    [{"schema": "data_quality", "name": "reject"}, "reject"]
                ],
                "item_003": [
                    [{"schema": "data_quality", "name": "skip"}, "skip"]
                ],
            }
        }

        with open(user_dir / "user_state.json", "w") as f:
            json.dump(user_state, f)

        annotations = load_annotations_from_dir(str(tmp_path))

        assert len(annotations) == 3
        assert annotations["item_001"]["data_quality"]["name"] == "accept"
        assert annotations["item_002"]["data_quality"]["name"] == "reject"
        assert annotations["item_003"]["data_quality"]["name"] == "skip"

    def test_load_from_multiple_users(self, tmp_path):
        """Load annotations from multiple users."""
        # User 1
        user1_dir = tmp_path / "user1"
        user1_dir.mkdir()
        with open(user1_dir / "user_state.json", "w") as f:
            json.dump({
                "user_id": "user1",
                "instance_id_to_label_to_value": {
                    "item_001": [[{"schema": "quality", "name": "good"}, "good"]],
                }
            }, f)

        # User 2
        user2_dir = tmp_path / "user2"
        user2_dir.mkdir()
        with open(user2_dir / "user_state.json", "w") as f:
            json.dump({
                "user_id": "user2",
                "instance_id_to_label_to_value": {
                    "item_002": [[{"schema": "quality", "name": "bad"}, "bad"]],
                }
            }, f)

        annotations = load_annotations_from_dir(str(tmp_path))

        assert len(annotations) == 2
        assert "item_001" in annotations
        assert "item_002" in annotations

    def test_skip_invalid_json(self, tmp_path):
        """Invalid JSON files are skipped."""
        user_dir = tmp_path / "user1"
        user_dir.mkdir()

        with open(user_dir / "user_state.json", "w") as f:
            f.write("not valid json")

        annotations = load_annotations_from_dir(str(tmp_path))
        assert annotations == {}


class TestLoadDataFile:
    """Tests for loading data files."""

    def test_load_json_array(self, tmp_path):
        """Load JSON array file."""
        data_file = tmp_path / "data.json"
        data = [
            {"id": "1", "text": "Hello"},
            {"id": "2", "text": "World"},
        ]
        with open(data_file, "w") as f:
            json.dump(data, f)

        items = load_data_file(str(data_file))
        assert len(items) == 2
        assert items[0]["id"] == "1"

    def test_load_jsonl(self, tmp_path):
        """Load JSONL file."""
        data_file = tmp_path / "data.jsonl"
        with open(data_file, "w") as f:
            f.write('{"id": "1", "text": "Hello"}\n')
            f.write('{"id": "2", "text": "World"}\n')

        items = load_data_file(str(data_file))
        assert len(items) == 2

    def test_load_nonexistent_raises(self, tmp_path):
        """Loading nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            load_data_file(str(tmp_path / "nonexistent.json"))


class TestFilterItemsByAnnotation:
    """Tests for filtering items by annotation."""

    @pytest.fixture
    def sample_data(self, tmp_path):
        """Create sample data and annotations."""
        # Create data file
        data_file = tmp_path / "data.json"
        data = [
            {"id": "item_001", "text": "Good text"},
            {"id": "item_002", "text": "Bad text"},
            {"id": "item_003", "text": "Maybe text"},
            {"id": "item_004", "text": "Unannotated text"},
        ]
        with open(data_file, "w") as f:
            json.dump(data, f)

        # Create annotation output
        anno_dir = tmp_path / "annotation_output"
        user_dir = anno_dir / "user1"
        user_dir.mkdir(parents=True)

        user_state = {
            "user_id": "user1",
            "instance_id_to_label_to_value": {
                "item_001": [[{"schema": "triage", "name": "accept"}, "accept"]],
                "item_002": [[{"schema": "triage", "name": "reject"}, "reject"]],
                "item_003": [[{"schema": "triage", "name": "accept"}, "accept"]],
                # item_004 not annotated
            }
        }
        with open(user_dir / "user_state.json", "w") as f:
            json.dump(user_state, f)

        return {
            "data_file": str(data_file),
            "annotation_dir": str(anno_dir),
        }

    def test_filter_accept(self, sample_data):
        """Filter for accepted items."""
        filtered = filter_items_by_annotation(
            annotation_dir=sample_data["annotation_dir"],
            data_file=sample_data["data_file"],
            schema_name="triage",
            filter_value="accept"
        )

        assert len(filtered) == 2
        ids = [item["id"] for item in filtered]
        assert "item_001" in ids
        assert "item_003" in ids
        assert "item_002" not in ids

    def test_filter_reject(self, sample_data):
        """Filter for rejected items."""
        filtered = filter_items_by_annotation(
            annotation_dir=sample_data["annotation_dir"],
            data_file=sample_data["data_file"],
            schema_name="triage",
            filter_value="reject"
        )

        assert len(filtered) == 1
        assert filtered[0]["id"] == "item_002"

    def test_filter_multiple_values(self, sample_data):
        """Filter for multiple values."""
        filtered = filter_items_by_annotation(
            annotation_dir=sample_data["annotation_dir"],
            data_file=sample_data["data_file"],
            schema_name="triage",
            filter_value=["accept", "reject"]
        )

        assert len(filtered) == 3

    def test_filter_invert(self, sample_data):
        """Invert filter returns non-matching items."""
        filtered = filter_items_by_annotation(
            annotation_dir=sample_data["annotation_dir"],
            data_file=sample_data["data_file"],
            schema_name="triage",
            filter_value="accept",
            invert=True
        )

        # Should get reject + unannotated
        assert len(filtered) == 2
        ids = [item["id"] for item in filtered]
        assert "item_002" in ids
        assert "item_004" in ids

    def test_filter_custom_id_key(self, tmp_path):
        """Use custom ID key."""
        # Create data with custom ID key
        data_file = tmp_path / "data.json"
        data = [
            {"custom_id": "item_001", "text": "Hello"},
            {"custom_id": "item_002", "text": "World"},
        ]
        with open(data_file, "w") as f:
            json.dump(data, f)

        # Create annotations
        anno_dir = tmp_path / "annotations"
        user_dir = anno_dir / "user1"
        user_dir.mkdir(parents=True)
        with open(user_dir / "user_state.json", "w") as f:
            json.dump({
                "user_id": "user1",
                "instance_id_to_label_to_value": {
                    "item_001": [[{"schema": "q", "name": "yes"}, "yes"]],
                }
            }, f)

        filtered = filter_items_by_annotation(
            annotation_dir=str(anno_dir),
            data_file=str(data_file),
            schema_name="q",
            filter_value="yes",
            id_key="custom_id"
        )

        assert len(filtered) == 1
        assert filtered[0]["custom_id"] == "item_001"


class TestGetAnnotationSummary:
    """Tests for annotation summary."""

    def test_summary_counts(self, tmp_path):
        """Get annotation value counts."""
        user_dir = tmp_path / "user1"
        user_dir.mkdir()

        user_state = {
            "user_id": "user1",
            "instance_id_to_label_to_value": {
                "item_001": [[{"schema": "triage", "name": "accept"}, "accept"]],
                "item_002": [[{"schema": "triage", "name": "accept"}, "accept"]],
                "item_003": [[{"schema": "triage", "name": "reject"}, "reject"]],
            }
        }
        with open(user_dir / "user_state.json", "w") as f:
            json.dump(user_state, f)

        counts = get_annotation_summary(str(tmp_path), "triage")

        assert counts["accept"] == 2
        assert counts["reject"] == 1

    def test_summary_empty_schema(self, tmp_path):
        """Empty summary for unknown schema."""
        user_dir = tmp_path / "user1"
        user_dir.mkdir()

        with open(user_dir / "user_state.json", "w") as f:
            json.dump({
                "user_id": "user1",
                "instance_id_to_label_to_value": {}
            }, f)

        counts = get_annotation_summary(str(tmp_path), "unknown")
        assert counts == {}


class TestOutputFormat:
    """Tests verifying the output format is correct for downstream tasks."""

    def test_output_preserves_all_fields(self, tmp_path):
        """Filtered output preserves all original fields."""
        # Create data with extra fields
        data_file = tmp_path / "data.json"
        data = [
            {"id": "1", "text": "Hello", "category": "greeting", "score": 0.9},
            {"id": "2", "text": "World", "category": "noun", "score": 0.8},
        ]
        with open(data_file, "w") as f:
            json.dump(data, f)

        # Create annotations
        anno_dir = tmp_path / "annotations"
        user_dir = anno_dir / "user1"
        user_dir.mkdir(parents=True)
        with open(user_dir / "user_state.json", "w") as f:
            json.dump({
                "user_id": "user1",
                "instance_id_to_label_to_value": {
                    "1": [[{"schema": "q", "name": "yes"}, "yes"]],
                }
            }, f)

        filtered = filter_items_by_annotation(
            annotation_dir=str(anno_dir),
            data_file=str(data_file),
            schema_name="q",
            filter_value="yes"
        )

        assert len(filtered) == 1
        item = filtered[0]
        assert item["id"] == "1"
        assert item["text"] == "Hello"
        assert item["category"] == "greeting"
        assert item["score"] == 0.9

    def test_output_can_be_used_as_input(self, tmp_path):
        """Filtered output can be written and read back."""
        # Create and filter data
        data_file = tmp_path / "data.json"
        data = [{"id": "1", "text": "Hello"}, {"id": "2", "text": "World"}]
        with open(data_file, "w") as f:
            json.dump(data, f)

        anno_dir = tmp_path / "annotations"
        user_dir = anno_dir / "user1"
        user_dir.mkdir(parents=True)
        with open(user_dir / "user_state.json", "w") as f:
            json.dump({
                "user_id": "user1",
                "instance_id_to_label_to_value": {
                    "1": [[{"schema": "q", "name": "yes"}, "yes"]],
                }
            }, f)

        filtered = filter_items_by_annotation(
            annotation_dir=str(anno_dir),
            data_file=str(data_file),
            schema_name="q",
            filter_value="yes"
        )

        # Write output
        output_file = tmp_path / "filtered.json"
        with open(output_file, "w") as f:
            json.dump(filtered, f)

        # Read back and verify
        with open(output_file, "r") as f:
            reloaded = json.load(f)

        assert len(reloaded) == 1
        assert reloaded[0]["id"] == "1"
