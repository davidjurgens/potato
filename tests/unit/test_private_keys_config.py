"""``item_properties.private_keys`` is checked at load."""

import pytest

from potato.server_utils.config_module import ConfigValidationError, validate_yaml_structure


def _config(tmp_path, private_keys):
    return {
        "item_properties": {"id_key": "id", "text_key": "text",
                            "private_keys": private_keys},
        "data_files": [{"path": "test.json", "format": "json"}],
        "task_dir": str(tmp_path),
        "output_annotation_dir": "output",
        "annotation_task_name": "Test",
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "tone", "description": "Tone",
             "labels": ["good", "bad"]}],
    }


def test_a_list_of_field_names_is_accepted(tmp_path):
    validate_yaml_structure(_config(tmp_path, ["model_a", "model_b"]),
                            str(tmp_path), str(tmp_path))


@pytest.mark.parametrize("value", ["model_a", [1], [""], {"a": 1}])
def test_anything_else_is_refused(tmp_path, value):
    with pytest.raises(ConfigValidationError, match="private_keys must be a list"):
        validate_yaml_structure(_config(tmp_path, value), str(tmp_path), str(tmp_path))


def test_the_text_field_cannot_be_private(tmp_path):
    with pytest.raises(ConfigValidationError, match="cannot include text"):
        validate_yaml_structure(_config(tmp_path, ["text"]), str(tmp_path), str(tmp_path))
