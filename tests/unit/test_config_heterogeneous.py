"""
Unit tests for heterogeneous-coverage config wiring:
    num_annotators_per_item (int OR dict)
    per_annotator_quota
    legacy max_annotations_per_item alias
"""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    resolve_num_annotators_per_item,
    validate_num_annotators_per_item,
    validate_optional_field_types,
    validate_per_annotator_quota,
)


class TestNumAnnotatorsValidation:
    def test_int_form_ok(self):
        validate_num_annotators_per_item(3)

    def test_negative_int_rejected(self):
        with pytest.raises(ConfigValidationError):
            validate_num_annotators_per_item(-1)

    def test_full_dict_ok(self):
        validate_num_annotators_per_item({
            "default": 1,
            "overlap_sample": {"fraction": 0.1, "count": 3, "stratify_by": "cat", "seed": 7},
            "adaptive": {"enabled": True, "disagreement_threshold": 0.5, "boost_to": 3},
            "min": 1,
        })

    def test_unknown_top_key_rejected(self):
        with pytest.raises(ConfigValidationError):
            validate_num_annotators_per_item({"default": 1, "bogus": 2})

    def test_fraction_out_of_range(self):
        with pytest.raises(ConfigValidationError):
            validate_num_annotators_per_item({
                "default": 1, "overlap_sample": {"fraction": 1.5, "count": 3},
            })

    def test_count_not_greater_than_default(self):
        with pytest.raises(ConfigValidationError):
            validate_num_annotators_per_item({
                "default": 3, "overlap_sample": {"fraction": 0.1, "count": 3},
            })

    def test_adaptive_boost_must_exceed_default(self):
        with pytest.raises(ConfigValidationError):
            validate_num_annotators_per_item({
                "default": 2, "adaptive": {"enabled": True, "boost_to": 2},
            })

    def test_min_exceeds_default(self):
        with pytest.raises(ConfigValidationError):
            validate_num_annotators_per_item({"default": 1, "min": 2})


class TestPerAnnotatorQuotaValidation:
    def test_full_quota_ok(self):
        validate_per_annotator_quota({
            "default": 100,
            "by_user": {"alice": 30},
            "by_user_role": {"expert": 30, "novice": 200},
        })

    def test_negative_default_rejected(self):
        with pytest.raises(ConfigValidationError):
            validate_per_annotator_quota({"default": -1})

    def test_non_string_user_rejected(self):
        with pytest.raises(ConfigValidationError):
            validate_per_annotator_quota({"by_user": {"": 10}})


class TestResolution:
    def test_int_form(self):
        assert resolve_num_annotators_per_item({"num_annotators_per_item": 3}) == 3

    def test_dict_default(self):
        assert resolve_num_annotators_per_item({"num_annotators_per_item": {"default": 1}}) == 1

    def test_legacy_fallback(self):
        assert resolve_num_annotators_per_item({"max_annotations_per_item": 5}) == 5

    def test_empty_returns_minus_one(self):
        assert resolve_num_annotators_per_item({}) == -1


class TestDeprecationGate:
    def test_conflicting_values_raise(self):
        with pytest.raises(ConfigValidationError):
            validate_optional_field_types({
                "max_annotations_per_item": 1,
                "num_annotators_per_item": {"default": 2},
            })

    def test_consistent_values_warn_but_pass(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            with pytest.raises(DeprecationWarning):
                validate_optional_field_types({
                    "max_annotations_per_item": 2,
                    "num_annotators_per_item": {"default": 2},
                })
