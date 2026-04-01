"""
Unit tests for IBWS configuration validation.
"""

import pytest
from unittest.mock import patch, MagicMock

from potato.server_utils.config_module import _validate_ibws_config, ConfigValidationError


def make_valid_config():
    """Create a valid IBWS config dict."""
    return {
        "ibws_config": {
            "tuple_size": 4,
            "max_rounds": None,
            "seed": 42,
            "scoring_method": "counting",
            "tuples_per_item_per_round": 2,
        },
        "annotation_schemes": [
            {"annotation_type": "bws", "name": "test_bws"}
        ],
    }


class TestIBWSConfigValidation:
    """Test _validate_ibws_config()."""

    def test_valid_config(self):
        config = make_valid_config()
        # Should not raise
        _validate_ibws_config(config)

    def test_mutual_exclusivity_with_bws(self):
        config = make_valid_config()
        config["bws_config"] = {"tuple_size": 4}

        with pytest.raises(ConfigValidationError, match="mutually exclusive"):
            _validate_ibws_config(config)

    def test_requires_bws_scheme(self):
        config = make_valid_config()
        config["annotation_schemes"] = [
            {"annotation_type": "radio", "name": "test_radio"}
        ]

        with pytest.raises(ConfigValidationError, match="annotation_type: bws"):
            _validate_ibws_config(config)

    def test_invalid_tuple_size(self):
        config = make_valid_config()
        config["ibws_config"]["tuple_size"] = 1

        with pytest.raises(ConfigValidationError, match="tuple_size"):
            _validate_ibws_config(config)

    def test_invalid_max_rounds(self):
        config = make_valid_config()
        config["ibws_config"]["max_rounds"] = 0

        with pytest.raises(ConfigValidationError, match="max_rounds"):
            _validate_ibws_config(config)

    def test_null_max_rounds_valid(self):
        config = make_valid_config()
        config["ibws_config"]["max_rounds"] = None
        # Should not raise
        _validate_ibws_config(config)

    def test_invalid_scoring_method(self):
        config = make_valid_config()
        config["ibws_config"]["scoring_method"] = "invalid_method"

        with pytest.raises(ConfigValidationError, match="scoring_method"):
            _validate_ibws_config(config)

    def test_invalid_tuples_per_item(self):
        config = make_valid_config()
        config["ibws_config"]["tuples_per_item_per_round"] = 0

        with pytest.raises(ConfigValidationError, match="tuples_per_item_per_round"):
            _validate_ibws_config(config)

    def test_invalid_seed(self):
        config = make_valid_config()
        config["ibws_config"]["seed"] = "not_an_int"

        with pytest.raises(ConfigValidationError, match="seed"):
            _validate_ibws_config(config)

    def test_ibws_config_must_be_dict(self):
        config = make_valid_config()
        config["ibws_config"] = "not_a_dict"

        with pytest.raises(ConfigValidationError, match="must be a dictionary"):
            _validate_ibws_config(config)
