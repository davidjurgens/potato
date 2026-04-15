"""
Tests for config key validation with typo suggestions.

Verifies that validate_unknown_keys() warns about unrecognized config keys
at all nesting levels and suggests close matches for likely typos.
"""

import logging
import pytest
from potato.server_utils.config_module import validate_unknown_keys, KNOWN_CONFIG_KEYS


class TestValidateUnknownKeys:
    """Tests for the validate_unknown_keys function."""

    def test_known_keys_no_warnings(self, caplog):
        """Config with only known keys should produce no warnings."""
        config = {
            "task_dir": ".",
            "data_files": ["data.json"],
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "debug": True,
        }
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        assert len(caplog.records) == 0

    def test_top_level_typo_with_suggestion(self, caplog):
        """A top-level typo should warn and suggest the correct key."""
        config = {"require_pasword": True}
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        assert len(caplog.records) == 1
        assert "require_pasword" in caplog.records[0].message
        assert "require_password" in caplog.records[0].message

    def test_top_level_typo_annotation_schemes(self, caplog):
        """Common typo in annotation_schemes should be caught."""
        config = {"annotaiton_schemes": []}
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        assert len(caplog.records) == 1
        assert "annotaiton_schemes" in caplog.records[0].message
        assert "annotation_schemes" in caplog.records[0].message

    def test_completely_unknown_key_no_suggestion(self, caplog):
        """A completely unknown key should warn without suggestions."""
        config = {"zzz_foobar_xyz": 42}
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        assert len(caplog.records) == 1
        assert "zzz_foobar_xyz" in caplog.records[0].message
        assert "will be ignored" in caplog.records[0].message

    def test_nested_typo_with_suggestion(self, caplog):
        """A typo in a nested key should include the full dotted path."""
        config = {"training": {"enabeld": True}}
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        assert len(caplog.records) == 1
        assert "training.enabeld" in caplog.records[0].message
        assert "enabled" in caplog.records[0].message

    def test_nested_typo_item_properties(self, caplog):
        """A typo in item_properties sub-key should be caught."""
        config = {"item_properties": {"id_key": "id", "text_ky": "text"}}
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        assert len(caplog.records) == 1
        assert "item_properties.text_ky" in caplog.records[0].message
        assert "text_key" in caplog.records[0].message

    def test_multiple_unknown_keys(self, caplog):
        """Multiple unknown keys at different levels should each get a warning."""
        config = {
            "foobar": True,
            "training": {"enabeld": True, "data_file": "data.json"},
            "bazqux": 99,
        }
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        # Should have 3 warnings: foobar, bazqux (top-level), training.enabeld (nested)
        assert len(caplog.records) == 3
        messages = [r.message for r in caplog.records]
        assert any("foobar" in m for m in messages)
        assert any("bazqux" in m for m in messages)
        assert any("training.enabeld" in m for m in messages)

    def test_non_dict_value_for_dict_key_no_crash(self, caplog):
        """If a key expects a dict but gets a scalar, validation should not crash."""
        config = {"training": "not_a_dict"}
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        # No crash, no warnings (training is a known key, value just isn't a dict)
        assert len(caplog.records) == 0

    def test_non_dict_config_data_no_crash(self, caplog):
        """Passing a non-dict config should not crash."""
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys("not a dict")
        assert len(caplog.records) == 0

    def test_empty_config_no_warnings(self, caplog):
        """An empty config should produce no warnings."""
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys({})
        assert len(caplog.records) == 0

    def test_known_nested_keys_no_warnings(self, caplog):
        """Known nested keys should not produce warnings."""
        config = {
            "server": {"port": 8000, "host": "0.0.0.0", "debug": True},
            "database": {"type": "mysql", "host": "localhost", "port": 3306},
        }
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        assert len(caplog.records) == 0

    def test_server_nested_typo(self, caplog):
        """A typo in server sub-key should be caught with dotted path."""
        config = {"server": {"prot": 8000}}
        with caplog.at_level(logging.WARNING):
            validate_unknown_keys(config)
        assert len(caplog.records) == 1
        assert "server.prot" in caplog.records[0].message
        assert "port" in caplog.records[0].message

    def test_schema_completeness(self):
        """KNOWN_CONFIG_KEYS should have a reasonable number of entries."""
        assert len(KNOWN_CONFIG_KEYS) > 50

    def test_schema_values_are_valid_types(self):
        """All schema values should be None, set, or dict."""
        for key, value in KNOWN_CONFIG_KEYS.items():
            assert value is None or isinstance(value, (set, dict)), \
                f"KNOWN_CONFIG_KEYS['{key}'] has invalid type: {type(value)}"
