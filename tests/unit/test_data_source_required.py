"""
Regression test for F-038: data_files must NOT be unconditionally required.

A config may declare its data via data_files, data_directory, OR data_sources.
The blanket required-fields check previously listed 'data_files', so a
data_directory- or data_sources-only config failed validation before the
dedicated "at least one data source" check could run.
"""

import pytest

from potato.server_utils.config_module import (
    validate_yaml_structure,
    ConfigValidationError,
)


def _base_config(**overrides):
    cfg = {
        "annotation_task_name": "Test",
        "item_properties": {"id_key": "id", "text_key": "text"},
        "task_dir": ".",
        "output_annotation_dir": "annotation_output/",
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "q",
             "description": "Quality", "labels": ["good", "bad"]}
        ],
    }
    cfg.update(overrides)
    return cfg


class TestDataSourceRequirement:
    def test_data_directory_only_validates(self):
        """A config with data_directory and no data_files must validate."""
        validate_yaml_structure(_base_config(data_directory="incoming"))

    def test_data_sources_only_validates(self):
        """A config with data_sources and no data_files must validate."""
        cfg = _base_config(data_sources=[
            {"type": "file", "name": "local", "path": "data/x.json"}
        ])
        validate_yaml_structure(cfg)

    def test_data_files_still_validates(self):
        """The common data_files config keeps working (regression guard)."""
        validate_yaml_structure(_base_config(data_files=["data/x.json"]))

    def test_no_data_source_still_rejected(self):
        """With none of the three, validation must still fail clearly."""
        with pytest.raises(ConfigValidationError, match="data source"):
            validate_yaml_structure(_base_config())
