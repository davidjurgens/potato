"""
Tests for potato.datasets_integration — load_as_dataset() and load_annotations()
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_config_dir(tmp_path):
    """Create a minimal Potato project with annotations."""
    # Data file
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_file = data_dir / "items.json"
    items = [
        {"id": "item_1", "text": "This is great"},
        {"id": "item_2", "text": "This is bad"},
    ]
    data_file.write_text("\n".join(json.dumps(i) for i in items))

    # Annotation output
    out_dir = tmp_path / "annotation_output" / "user_alice"
    out_dir.mkdir(parents=True)
    user_state = {
        "user_id": "alice",
        "instance_id_to_label_to_value": {
            "item_1": {"sentiment": {"positive": "true"}},
            "item_2": {"sentiment": {"negative": "true"}},
        },
        "instance_id_to_span_to_value": {
            "item_1": {
                "highlights": [
                    {"start": 0, "end": 4, "label": "noun", "text": "This"},
                ]
            },
        },
    }
    (out_dir / "user_state.json").write_text(json.dumps(user_state))

    # Config YAML
    config = {
        "annotation_task_name": "Test",
        "data_files": ["data/items.json"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "task_dir": ".",
        "output_annotation_dir": "annotation_output",
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sentiment",
             "labels": [{"name": "positive"}, {"name": "negative"}]},
            {"annotation_type": "span", "name": "highlights",
             "labels": [{"name": "noun"}]},
        ],
    }
    import yaml
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config))

    return str(config_path)


@pytest.fixture
def empty_config_dir(tmp_path):
    """Config that points to an empty output directory (no annotations)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_file = data_dir / "items.json"
    data_file.write_text('{"id": "x", "text": "hello"}\n')

    out_dir = tmp_path / "annotation_output"
    out_dir.mkdir()

    config = {
        "data_files": ["data/items.json"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "task_dir": ".",
        "output_annotation_dir": "annotation_output",
        "annotation_schemes": [],
    }
    import yaml
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config))

    return str(config_path)


# ---------------------------------------------------------------------------
# Tests for load_as_dataset
# ---------------------------------------------------------------------------

class TestLoadAsDataset:
    def test_returns_dataset_dict(self, sample_config_dir):
        """load_as_dataset returns a DatasetDict with expected splits."""
        datasets = pytest.importorskip("datasets")

        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(sample_config_dir)
        assert isinstance(ds, datasets.DatasetDict)
        assert "annotations" in ds
        assert len(ds["annotations"]) == 2  # alice annotated 2 items

    def test_includes_spans_split(self, sample_config_dir):
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(sample_config_dir, include_spans=True)
        assert "spans" in ds
        assert len(ds["spans"]) >= 1

    def test_excludes_spans_when_disabled(self, sample_config_dir):
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(sample_config_dir, include_spans=False)
        assert "spans" not in ds

    def test_includes_items_split(self, sample_config_dir):
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(sample_config_dir, include_items=True)
        assert "items" in ds
        assert len(ds["items"]) == 2

    def test_excludes_items_when_disabled(self, sample_config_dir):
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(sample_config_dir, include_items=False)
        assert "items" not in ds

    def test_empty_annotations_no_annotation_split(self, empty_config_dir):
        """When no annotations exist, the annotations split is absent."""
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(empty_config_dir)
        assert "annotations" not in ds

    def test_import_error_without_datasets(self, sample_config_dir):
        """ImportError raised when datasets not installed."""
        import importlib
        from potato import datasets_integration

        with patch.dict("sys.modules", {"datasets": None}):
            # Force re-evaluation of the import inside load_as_dataset
            with pytest.raises(ImportError, match="datasets"):
                # Call function directly — the lazy import guard fires
                datasets_integration.load_as_dataset(sample_config_dir)


# ---------------------------------------------------------------------------
# Tests for load_annotations
# ---------------------------------------------------------------------------

class TestLoadAnnotations:
    def test_returns_dataframe(self, sample_config_dir):
        import pandas as pd
        from potato.datasets_integration import load_annotations

        df = load_annotations(sample_config_dir)
        assert isinstance(df, pd.DataFrame)
        assert "instance_id" in df.columns
        assert "user_id" in df.columns
        assert len(df) == 2

    def test_empty_raises_value_error(self, empty_config_dir):
        from potato.datasets_integration import load_annotations

        with pytest.raises(ValueError, match="No annotations found"):
            load_annotations(empty_config_dir)


# ---------------------------------------------------------------------------
# Tests for lazy imports from potato package
# ---------------------------------------------------------------------------

class TestLazyImports:
    def test_load_as_dataset_importable(self):
        """load_as_dataset is accessible from potato namespace."""
        import potato
        assert hasattr(potato, "load_as_dataset")
        assert callable(potato.load_as_dataset)

    def test_load_annotations_importable(self):
        import potato
        assert hasattr(potato, "load_annotations")
        assert callable(potato.load_annotations)

    def test_unknown_attr_raises(self):
        import potato
        with pytest.raises(AttributeError):
            _ = potato.nonexistent_thing
