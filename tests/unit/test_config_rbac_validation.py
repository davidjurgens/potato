"""Unit tests for rbac + cohort-scheme config validation."""

import pytest

from potato.server_utils.config_module import (
    validate_rbac_config,
    validate_cohort_schemes_config,
    ConfigValidationError,
)


# --- RBAC ---------------------------------------------------------------

def test_valid_rbac_passes():
    validate_rbac_config(
        {
            "rbac": {
                "enabled": True,
                "roles": {"lead": ["annotate", "view_admin_dashboard"]},
                "user_role_assignments": {"x": "lead", "y": "admin"},
                "sso_role_mapping": {"org:acme": "adjudicator"},
            }
        }
    )


def test_absent_rbac_is_noop():
    validate_rbac_config({})  # no error


def test_rbac_must_be_mapping():
    with pytest.raises(ConfigValidationError):
        validate_rbac_config({"rbac": ["not", "a", "dict"]})


def test_unknown_permission_rejected():
    with pytest.raises(ConfigValidationError):
        validate_rbac_config({"rbac": {"roles": {"lead": ["fly"]}}})


def test_unknown_role_reference_rejected():
    with pytest.raises(ConfigValidationError):
        validate_rbac_config({"rbac": {"user_role_assignments": {"x": "ghost"}}})


def test_sso_mapping_to_unknown_role_rejected():
    with pytest.raises(ConfigValidationError):
        validate_rbac_config({"rbac": {"sso_role_mapping": {"org:z": "ghost"}}})


def test_enabled_must_be_bool():
    with pytest.raises(ConfigValidationError):
        validate_rbac_config({"rbac": {"enabled": "yes"}})


def test_builtin_roles_are_referenceable():
    validate_rbac_config({"rbac": {"user_role_assignments": {"x": "adjudicator"}}})


# --- cohort schemes -----------------------------------------------------

_SCHEMES = [
    {"name": "a", "annotation_type": "radio", "description": "d", "labels": ["x"]},
    {"name": "b", "annotation_type": "radio", "description": "d", "labels": ["y"]},
]


def test_valid_cohort_schemes_passes():
    validate_cohort_schemes_config(
        {
            "annotation_schemes": _SCHEMES,
            "scheme_sets": {"minimal": ["a"]},
            "batch_assignment": {
                "groups": [
                    {"name": "g1", "annotators": ["u"], "schemes": "minimal"},
                    {"name": "g2", "annotators": ["v"], "schemes": ["a", "b"]},
                ]
            },
        }
    )


def test_absent_cohort_config_is_noop():
    validate_cohort_schemes_config({"annotation_schemes": _SCHEMES})


def test_scheme_sets_must_be_mapping():
    with pytest.raises(ConfigValidationError):
        validate_cohort_schemes_config(
            {"annotation_schemes": _SCHEMES, "scheme_sets": ["a"]}
        )


def test_unknown_scheme_name_in_group_rejected():
    with pytest.raises(ConfigValidationError):
        validate_cohort_schemes_config(
            {
                "annotation_schemes": _SCHEMES,
                "batch_assignment": {
                    "groups": [{"name": "g", "annotators": ["u"], "schemes": ["ghost"]}]
                },
            }
        )


def test_unknown_scheme_set_name_rejected():
    with pytest.raises(ConfigValidationError):
        validate_cohort_schemes_config(
            {
                "annotation_schemes": _SCHEMES,
                "batch_assignment": {
                    "groups": [{"name": "g", "annotators": ["u"], "schemes": "nope"}]
                },
            }
        )


def test_inline_scheme_dict_in_binding_validated():
    # A valid inline scheme dict passes single-scheme validation.
    validate_cohort_schemes_config(
        {
            "annotation_schemes": _SCHEMES,
            "batch_assignment": {
                "groups": [
                    {
                        "name": "g",
                        "annotators": ["u"],
                        "schemes": [
                            {
                                "name": "extra",
                                "annotation_type": "radio",
                                "description": "d",
                                "labels": ["p", "q"],
                            }
                        ],
                    }
                ]
            },
        }
    )
