"""
Server integration tests for potato.datasets_integration.

Tests load_as_dataset() and load_annotations() against a real running
Potato server with actual annotations saved to disk.
"""

import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NUM_ITEMS = 5


def _make_config(test_name="ds_integ"):
    """Create config with radio + span schemes so both annotation types exist."""
    test_dir = create_test_directory(test_name)
    data = [
        {"id": f"item_{i}", "text": f"Sample sentence number {i} for testing."}
        for i in range(1, NUM_ITEMS + 1)
    ]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[
            {
                "name": "sentiment",
                "description": "Classify sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
            },
            {
                "name": "highlights",
                "description": "Highlight spans",
                "annotation_type": "span",
                "labels": ["important", "error"],
            },
        ],
        data_files=[data_file],
    )
    return config_file, test_dir


def _register_and_annotate(base_url, username="annotator_a"):
    """Register, login, and submit annotations for several items."""
    session = requests.Session()
    session.post(f"{base_url}/register", data={"email": username, "pass": "pass"})
    session.post(f"{base_url}/auth", data={"email": username, "pass": "pass"})
    session.get(f"{base_url}/annotate")

    # Annotate items 1-3
    for i in range(1, 4):
        session.post(f"{base_url}/updateinstance", json={
            "instance_id": f"item_{i}",
            "annotations": {"sentiment:positive": "true"},
        })
    return session


# ---------------------------------------------------------------------------
# Tests: load_as_dataset against a running server
# ---------------------------------------------------------------------------

class TestLoadAsDatasetServer:
    """Integration tests that annotate via HTTP then load as DatasetDict."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        config_file, test_dir = _make_config()
        server = FlaskTestServer(port=9870, config_file=config_file)
        if not server.start():
            pytest.fail("Failed to start server for datasets integration test")
        request.cls.server = server
        request.cls.config_file = config_file
        request.cls.test_dir = test_dir

        # Create annotations via the running server
        _register_and_annotate(server.base_url, "user_one")
        _register_and_annotate(server.base_url, "user_two")

        yield server
        server.stop()

    def test_returns_dataset_dict_type(self):
        datasets = pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(self.config_file)
        assert isinstance(ds, datasets.DatasetDict)

    def test_annotations_split_has_rows(self):
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(self.config_file)
        assert "annotations" in ds
        # Two users annotated 3 items each = 6 annotation rows
        assert len(ds["annotations"]) >= 6

    def test_annotation_rows_have_instance_and_user_ids(self):
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(self.config_file)
        row = ds["annotations"][0]
        assert "instance_id" in row
        assert "user_id" in row
        assert row["instance_id"] != ""
        assert row["user_id"] != ""

    def test_items_split_contains_all_items(self):
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(self.config_file, include_items=True)
        assert "items" in ds
        assert len(ds["items"]) == NUM_ITEMS

    def test_items_split_excluded_when_disabled(self):
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(self.config_file, include_items=False)
        assert "items" not in ds

    def test_spans_split_excluded_when_disabled(self):
        pytest.importorskip("datasets")
        from potato.datasets_integration import load_as_dataset

        ds = load_as_dataset(self.config_file, include_spans=False)
        assert "spans" not in ds


# ---------------------------------------------------------------------------
# Tests: load_annotations against a running server
# ---------------------------------------------------------------------------

class TestLoadAnnotationsServer:
    """Integration tests for load_annotations() returning a DataFrame."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        config_file, test_dir = _make_config("ds_integ_df")
        server = FlaskTestServer(port=9871, config_file=config_file)
        if not server.start():
            pytest.fail("Failed to start server for load_annotations test")
        request.cls.server = server
        request.cls.config_file = config_file
        request.cls.test_dir = test_dir

        _register_and_annotate(server.base_url, "df_user")

        yield server
        server.stop()

    def test_returns_dataframe(self):
        import pandas as pd
        from potato.datasets_integration import load_annotations

        df = load_annotations(self.config_file)
        assert isinstance(df, pd.DataFrame)

    def test_dataframe_has_expected_columns(self):
        from potato.datasets_integration import load_annotations

        df = load_annotations(self.config_file)
        assert "instance_id" in df.columns
        assert "user_id" in df.columns

    def test_dataframe_row_count_matches_annotations(self):
        from potato.datasets_integration import load_annotations

        df = load_annotations(self.config_file)
        # One user annotated 3 items
        assert len(df) >= 3

    def test_user_id_values_are_correct(self):
        from potato.datasets_integration import load_annotations

        df = load_annotations(self.config_file)
        assert "df_user" in df["user_id"].values


# ---------------------------------------------------------------------------
# Tests: build_dataset_dict via exporter directly
# ---------------------------------------------------------------------------

class TestBuildDatasetDictServer:
    """Integration test for the refactored HuggingFaceExporter.build_dataset_dict()."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        config_file, test_dir = _make_config("ds_integ_build")
        server = FlaskTestServer(port=9872, config_file=config_file)
        if not server.start():
            pytest.fail("Failed to start server for build_dataset_dict test")
        request.cls.server = server
        request.cls.config_file = config_file

        _register_and_annotate(server.base_url, "builder_user")

        yield server
        server.stop()

    def test_build_dataset_dict_returns_dataset_dict(self):
        datasets = pytest.importorskip("datasets")
        from potato.export.cli import build_export_context
        from potato.export.huggingface_exporter import HuggingFaceExporter

        context = build_export_context(self.config_file)
        exporter = HuggingFaceExporter()
        ds = exporter.build_dataset_dict(context)

        assert isinstance(ds, datasets.DatasetDict)
        assert "annotations" in ds

    def test_build_dataset_dict_without_items(self):
        datasets = pytest.importorskip("datasets")
        from potato.export.cli import build_export_context
        from potato.export.huggingface_exporter import HuggingFaceExporter

        context = build_export_context(self.config_file)
        exporter = HuggingFaceExporter()
        ds = exporter.build_dataset_dict(context, include_items=False)

        assert "items" not in ds
        assert "annotations" in ds

    def test_build_dataset_dict_raises_on_empty(self):
        """Empty ExportContext raises ValueError."""
        pytest.importorskip("datasets")
        from potato.export.base import ExportContext
        from potato.export.huggingface_exporter import HuggingFaceExporter

        empty_context = ExportContext(
            config={}, annotations=[], items={}, schemas=[], output_dir=""
        )
        exporter = HuggingFaceExporter()

        with pytest.raises(ValueError, match="No data to build"):
            exporter.build_dataset_dict(empty_context)
