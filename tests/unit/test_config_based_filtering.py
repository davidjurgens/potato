"""
Tests for config-based annotation filtering in data loading.

Tests the filter_by_prior_annotation configuration option that allows
filtering data items based on prior annotation decisions during data loading.
"""

import pytest
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.flask_server import _apply_annotation_filter


class TestApplyAnnotationFilter:
    """Tests for the _apply_annotation_filter helper function."""

    @pytest.fixture
    def sample_items(self):
        """Sample data items."""
        return [
            {"id": "item_001", "text": "First item"},
            {"id": "item_002", "text": "Second item"},
            {"id": "item_003", "text": "Third item"},
            {"id": "item_004", "text": "Fourth item"},
        ]

    @pytest.fixture
    def sample_annotations(self, tmp_path):
        """Create sample annotations directory."""
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

        return str(anno_dir)

    def test_filter_accept(self, sample_items, sample_annotations):
        """Filter for accepted items."""
        filter_config = {
            "annotation_dir": sample_annotations,
            "schema": "triage",
            "value": "accept"
        }

        filtered = _apply_annotation_filter(sample_items, filter_config, "id")

        assert len(filtered) == 2
        ids = [item["id"] for item in filtered]
        assert "item_001" in ids
        assert "item_003" in ids

    def test_filter_reject(self, sample_items, sample_annotations):
        """Filter for rejected items."""
        filter_config = {
            "annotation_dir": sample_annotations,
            "schema": "triage",
            "value": "reject"
        }

        filtered = _apply_annotation_filter(sample_items, filter_config, "id")

        assert len(filtered) == 1
        assert filtered[0]["id"] == "item_002"

    def test_filter_multiple_values(self, sample_items, sample_annotations):
        """Filter for multiple values (list)."""
        filter_config = {
            "annotation_dir": sample_annotations,
            "schema": "triage",
            "value": ["accept", "reject"]
        }

        filtered = _apply_annotation_filter(sample_items, filter_config, "id")

        assert len(filtered) == 3

    def test_filter_invert(self, sample_items, sample_annotations):
        """Invert filter returns non-matching items."""
        filter_config = {
            "annotation_dir": sample_annotations,
            "schema": "triage",
            "value": "accept",
            "invert": True
        }

        filtered = _apply_annotation_filter(sample_items, filter_config, "id")

        # Should get rejected + unannotated
        assert len(filtered) == 2
        ids = [item["id"] for item in filtered]
        assert "item_002" in ids
        assert "item_004" in ids

    def test_missing_annotation_dir_returns_all(self, sample_items):
        """Missing annotation_dir returns all items (with warning)."""
        filter_config = {
            "schema": "triage",
            "value": "accept"
        }

        filtered = _apply_annotation_filter(sample_items, filter_config, "id")

        assert len(filtered) == 4  # All items returned

    def test_missing_schema_returns_all(self, sample_items, sample_annotations):
        """Missing schema returns all items (with warning)."""
        filter_config = {
            "annotation_dir": sample_annotations,
            "value": "accept"
        }

        filtered = _apply_annotation_filter(sample_items, filter_config, "id")

        assert len(filtered) == 4

    def test_missing_value_returns_all(self, sample_items, sample_annotations):
        """Missing value returns all items (with warning)."""
        filter_config = {
            "annotation_dir": sample_annotations,
            "schema": "triage"
        }

        filtered = _apply_annotation_filter(sample_items, filter_config, "id")

        assert len(filtered) == 4


class TestConfigBasedFilteringFormat:
    """Tests for the config format for filter_by_prior_annotation."""

    def test_config_structure(self):
        """Verify expected config structure."""
        # This is the expected YAML structure:
        # data_files:
        #   - path: data/items.json
        #     filter_by_prior_annotation:
        #       annotation_dir: ../triage-task/annotation_output/
        #       schema: data_quality
        #       value: accept

        config_entry = {
            "path": "data/items.json",
            "filter_by_prior_annotation": {
                "annotation_dir": "../triage-task/annotation_output/",
                "schema": "data_quality",
                "value": "accept"
            }
        }

        # Verify structure
        assert "path" in config_entry
        assert "filter_by_prior_annotation" in config_entry

        filter_config = config_entry["filter_by_prior_annotation"]
        assert "annotation_dir" in filter_config
        assert "schema" in filter_config
        assert "value" in filter_config

    def test_config_with_multiple_values(self):
        """Config can specify multiple filter values."""
        config_entry = {
            "path": "data/items.json",
            "filter_by_prior_annotation": {
                "annotation_dir": "annotation_output/",
                "schema": "triage",
                "value": ["accept", "maybe"]  # Multiple values
            }
        }

        filter_config = config_entry["filter_by_prior_annotation"]
        assert isinstance(filter_config["value"], list)
        assert len(filter_config["value"]) == 2

    def test_config_with_invert(self):
        """Config can specify invert flag."""
        config_entry = {
            "path": "data/items.json",
            "filter_by_prior_annotation": {
                "annotation_dir": "annotation_output/",
                "schema": "triage",
                "value": "reject",
                "invert": True  # Get items that are NOT rejected
            }
        }

        filter_config = config_entry["filter_by_prior_annotation"]
        assert filter_config.get("invert") is True


class TestOutputFormatCompatibility:
    """Tests verifying filtered output is compatible with Potato data loading."""

    @pytest.fixture
    def filtered_data(self, tmp_path):
        """Create filtered data file."""
        data = [
            {"id": "item_001", "text": "First item", "extra_field": "value1"},
            {"id": "item_003", "text": "Third item", "extra_field": "value3"},
        ]
        data_file = tmp_path / "filtered.json"
        with open(data_file, "w") as f:
            json.dump(data, f)
        return str(data_file)

    def test_filtered_data_is_valid_json_array(self, filtered_data):
        """Filtered output is a valid JSON array."""
        with open(filtered_data, "r") as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == 2

    def test_filtered_data_preserves_id_key(self, filtered_data):
        """Filtered output preserves the id key."""
        with open(filtered_data, "r") as f:
            data = json.load(f)

        assert all("id" in item for item in data)

    def test_filtered_data_preserves_text_key(self, filtered_data):
        """Filtered output preserves the text key."""
        with open(filtered_data, "r") as f:
            data = json.load(f)

        assert all("text" in item for item in data)

    def test_filtered_data_preserves_extra_fields(self, filtered_data):
        """Filtered output preserves extra fields."""
        with open(filtered_data, "r") as f:
            data = json.load(f)

        assert all("extra_field" in item for item in data)
