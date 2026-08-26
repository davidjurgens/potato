"""Deprecated config keys fold onto their replacement and say so.

`output_annotation_format` was a live setting until the v2 storage rewrite
deleted the only code that read it. It survived in 175 example configs and an
unknown number of user configs, silently doing nothing. The loader now reads it
as `export_annotation_format` and warns; these tests pin both halves.
"""

import logging

import pytest
import yaml

from potato.server_utils.config_module import (
    DEPRECATED_KEY_ALIASES,
    apply_deprecated_key_aliases,
    deprecated_key_warnings,
    KNOWN_CONFIG_KEYS,
    validate_yaml_structure,
)


class TestApplyDeprecatedKeyAliases:
    def test_value_moves_to_the_replacement_key(self):
        config = {"output_annotation_format": "csv"}
        apply_deprecated_key_aliases(config)
        assert config == {"export_annotation_format": "csv"}

    def test_json_becomes_jsonl(self):
        """'json' was accepted by the old key but is not an exporter name."""
        config = {"output_annotation_format": "json"}
        apply_deprecated_key_aliases(config)
        assert config == {"export_annotation_format": "jsonl"}

    def test_an_explicit_replacement_wins(self):
        config = {
            "output_annotation_format": "tsv",
            "export_annotation_format": ["parquet"],
        }
        apply_deprecated_key_aliases(config)
        assert config == {"export_annotation_format": ["parquet"]}

    def test_an_empty_value_does_not_enable_auto_export(self):
        """Folding an empty legacy value must not switch exporting on."""
        config = {"output_annotation_format": ""}
        apply_deprecated_key_aliases(config)
        assert config == {}

    def test_a_list_value_maps_element_by_element(self):
        config = {"output_annotation_format": ["json", "csv"]}
        apply_deprecated_key_aliases(config)
        assert config == {"export_annotation_format": ["jsonl", "csv"]}

    def test_the_legacy_key_is_removed(self):
        """Nothing downstream should read a key whose meaning moved."""
        config = {"output_annotation_format": "csv"}
        apply_deprecated_key_aliases(config)
        assert "output_annotation_format" not in config

    def test_a_config_without_the_key_is_untouched(self):
        config = {"export_annotation_format": "csv"}
        apply_deprecated_key_aliases(config)
        assert config == {"export_annotation_format": "csv"}

    def test_returns_one_message_per_deprecated_key(self):
        messages = apply_deprecated_key_aliases({"output_annotation_format": "csv"})
        assert len(messages) == 1
        assert "output_annotation_format" in messages[0]
        assert "export_annotation_format" in messages[0]


class TestWarning:
    def test_the_warning_is_logged(self, caplog):
        with caplog.at_level(logging.WARNING, logger="potato.server_utils.config_module"):
            apply_deprecated_key_aliases({"output_annotation_format": "csv"})
        assert any("deprecated" in r.getMessage() for r in caplog.records)

    def test_the_warning_names_the_replacement_and_the_removal(self):
        message = deprecated_key_warnings({"output_annotation_format": "csv"})[0]
        assert "export_annotation_format" in message
        assert "later release" in message

    def test_deprecated_key_warnings_does_not_mutate(self):
        config = {"output_annotation_format": "csv"}
        deprecated_key_warnings(config)
        assert config == {"output_annotation_format": "csv"}

    def test_validate_warns_without_folding(self, tmp_path, caplog):
        """`potato validate` reports the key; validation itself changes nothing."""
        data_file = tmp_path / "items.json"
        data_file.write_text('[{"id": "1", "text": "hello"}]')
        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "task_dir": str(tmp_path),
            "output_annotation_dir": str(tmp_path / "out"),
            "annotation_task_name": "deprecation test",
            "data_files": [str(data_file)],
            "output_annotation_format": "csv",
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "q", "description": "q",
                 "labels": ["a", "b"]},
            ],
        }
        with caplog.at_level(logging.WARNING, logger="potato.server_utils.config_module"):
            validate_yaml_structure(config, project_dir=str(tmp_path),
                                    config_file_dir=str(tmp_path))
        assert any("output_annotation_format" in r.getMessage() for r in caplog.records)
        assert config["output_annotation_format"] == "csv"


class TestStillAccepted:
    def test_the_key_stays_known(self):
        """Otherwise an old config gets 'unrecognized key' instead of a reason."""
        for legacy in DEPRECATED_KEY_ALIASES:
            assert legacy in KNOWN_CONFIG_KEYS

    def test_each_replacement_is_a_real_key(self):
        for replacement in DEPRECATED_KEY_ALIASES.values():
            assert replacement in KNOWN_CONFIG_KEYS


class TestNoConfigShipsTheDeprecatedKey:
    """Examples teach by copy-paste; none may carry a deprecated key."""

    def test_no_example_config_uses_a_deprecated_key(self, repo_root):
        import subprocess

        tracked = subprocess.check_output(
            ["git", "ls-files", "examples", "deployment"],
            cwd=repo_root, text=True,
        ).split()
        offenders = []
        for name in tracked:
            if not name.endswith((".yaml", ".yml")):
                continue
            path = repo_root / name
            try:
                data = yaml.safe_load(path.read_text())
            except yaml.YAMLError:
                continue
            if not isinstance(data, dict):
                continue
            for legacy in DEPRECATED_KEY_ALIASES:
                if legacy in data:
                    offenders.append(f"{name}: {legacy}")
        assert not offenders, "deprecated keys in shipped configs:\n" + "\n".join(offenders)


@pytest.fixture
def repo_root():
    from pathlib import Path
    return Path(__file__).resolve().parents[2]
