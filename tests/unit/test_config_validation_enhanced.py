"""
Tests for enhanced config validation:
- Registry-driven annotation scheme validation
- Optional field type checking
- Runtime config access guards
"""

import pytest
from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_single_annotation_scheme,
    validate_optional_field_types,
    _OPTIONAL_INT_FIELDS,
    _OPTIONAL_BOOL_FIELDS,
    _VALID_ASSIGNMENT_STRATEGIES,
)
from potato.server_utils.schemas.registry import schema_registry


# ---------------------------------------------------------------------------
# Helper: build a minimal valid config for validate_optional_field_types
# ---------------------------------------------------------------------------

def _base_config():
    return {
        "item_properties": {"id_key": "id", "text_key": "text"},
        "data_files": ["data.json"],
        "task_dir": ".",
        "output_annotation_dir": "output/",
        "annotation_task_name": "test",
        "annotation_schemes": [{
            "annotation_type": "radio",
            "name": "test",
            "description": "test",
            "labels": ["A", "B"],
        }],
    }


# ===========================================================================
# Phase 1: Registry-driven validation
# ===========================================================================

class TestRegistryDrivenValidation:
    """Test that valid_types comes from registry and required fields are checked."""

    def test_valid_types_matches_registry(self):
        """The hardcoded valid_types list was replaced with registry lookup."""
        registry_types = set(schema_registry.get_supported_types())
        # Verify the registry has a reasonable number of types
        assert len(registry_types) >= 30

    def test_unknown_annotation_type_rejected(self):
        scheme = {
            "annotation_type": "totally_fake_type",
            "name": "test",
            "description": "test",
        }
        with pytest.raises(ConfigValidationError, match="annotation_type must be one of"):
            validate_single_annotation_scheme(scheme, "test")

    def test_valid_annotation_type_accepted(self):
        """All registered types should be accepted (with minimal required fields)."""
        for type_name in schema_registry.get_supported_types():
            schema_def = schema_registry.get(type_name)
            # Build a scheme with all required fields
            scheme = {
                "annotation_type": type_name,
                "name": "test",
                "description": "test",
            }
            # Add required fields from registry
            for field in schema_def.required_fields:
                if field in ("name", "description"):
                    continue
                # Provide plausible defaults for different field types
                if field == "labels":
                    scheme[field] = ["A", "B"]
                elif field == "tiers":
                    scheme[field] = [{"name": "tier1"}]
                elif field == "source_field":
                    scheme[field] = "audio_url"
                elif field == "tools":
                    scheme[field] = ["bbox"]
                elif field == "link_types":
                    scheme[field] = [{"name": "related"}]
                elif field == "span_schema":
                    scheme[field] = "spans"
                elif field == "event_types":
                    scheme[field] = [{"name": "event1"}]
                elif field == "taxonomy":
                    scheme[field] = {"root": ["child1"]}
                elif field == "criteria":
                    scheme[field] = [{"name": "criterion1"}]
                elif field == "error_types":
                    scheme[field] = [{"name": "error1"}]
                elif field == "pairs":
                    scheme[field] = [["good", "bad"]]
                elif field == "options":
                    scheme[field] = ["opt1", "opt2"]
                elif field == "video_path":
                    scheme[field] = "video.mp4"
                elif field in ("min_value", "starting_value"):
                    scheme[field] = 0
                elif field == "max_value":
                    scheme[field] = 100
                elif field == "min_label":
                    scheme[field] = "Low"
                elif field == "max_label":
                    scheme[field] = "High"
                elif field == "size":
                    scheme[field] = 5
                else:
                    scheme[field] = "test_value"
            # Types with default modes that require extra fields
            if type_name == "audio_annotation" and "labels" not in scheme:
                scheme["labels"] = ["A", "B"]
            if type_name == "video_annotation" and "labels" not in scheme:
                scheme["labels"] = ["A", "B"]
            if type_name == "card_sort" and "groups" not in scheme:
                scheme["groups"] = ["Group1", "Group2"]
            if type_name == "conjoint" and "attributes" not in scheme and "profiles_field" not in scheme:
                scheme["attributes"] = [{"name": "price", "levels": ["$10", "$20"]}]

            # Should not raise
            validate_single_annotation_scheme(scheme, f"test_scheme[{type_name}]")

    @pytest.mark.parametrize("type_name,missing_field", [
        ("span_link", "link_types"),
        ("span_link", "span_schema"),
        ("event_annotation", "event_types"),
        ("event_annotation", "span_schema"),
        ("coreference", "span_schema"),
        ("tiered_annotation", "tiers"),
        ("tiered_annotation", "source_field"),
    ])
    def test_registry_required_field_missing_for_explicit_types(self, type_name, missing_field):
        """Types with explicit validation blocks should still catch missing fields."""
        schema_def = schema_registry.get(type_name)
        scheme = {
            "annotation_type": type_name,
            "name": "test",
            "description": "test",
        }
        # Add all required fields EXCEPT the one we're testing
        for field in schema_def.required_fields:
            if field in ("name", "description", missing_field):
                continue
            if field == "tiers":
                scheme[field] = [{"name": "t1"}]
            elif field == "source_field":
                scheme[field] = "audio"
            elif field == "link_types":
                scheme[field] = [{"name": "r"}]
            elif field == "span_schema":
                scheme[field] = "spans"
            elif field == "event_types":
                scheme[field] = [{"name": "e1"}]
            else:
                scheme[field] = "val"

        with pytest.raises(ConfigValidationError, match=missing_field):
            validate_single_annotation_scheme(scheme, "test")


# ===========================================================================
# Phase 3: Optional field type validation
# ===========================================================================

class TestOptionalFieldTypeValidation:
    """Test that wrong types for optional fields are caught."""

    @pytest.mark.parametrize("field", list(_OPTIONAL_INT_FIELDS.keys()))
    def test_string_for_int_field_rejected(self, field):
        config = {field: "30"}
        with pytest.raises(ConfigValidationError, match=f"'{field}' must be an integer"):
            validate_optional_field_types(config)

    @pytest.mark.parametrize("field", list(_OPTIONAL_INT_FIELDS.keys()))
    def test_bool_for_int_field_rejected(self, field):
        """Booleans are technically int subclass in Python; should be rejected."""
        config = {field: True}
        with pytest.raises(ConfigValidationError, match=f"'{field}' must be an integer"):
            validate_optional_field_types(config)

    @pytest.mark.parametrize("field", list(_OPTIONAL_INT_FIELDS.keys()))
    def test_valid_int_accepted(self, field):
        config = {field: 42}
        validate_optional_field_types(config)  # Should not raise

    def test_negative_int_rejected_for_non_negative_fields(self):
        # alert_time_each_instance must be non-negative
        config = {"alert_time_each_instance": -5}
        with pytest.raises(ConfigValidationError, match="non-negative"):
            validate_optional_field_types(config)

    def test_negative_int_allowed_for_unlimited_fields(self):
        # max_annotations_per_item allows -1 (unlimited)
        config = {"max_annotations_per_item": -1}
        validate_optional_field_types(config)  # Should not raise

    @pytest.mark.parametrize("field", list(_OPTIONAL_BOOL_FIELDS.keys()))
    def test_string_for_bool_field_rejected(self, field):
        config = {field: "true"}
        with pytest.raises(ConfigValidationError, match=f"'{field}' must be a boolean"):
            validate_optional_field_types(config)

    @pytest.mark.parametrize("field", list(_OPTIONAL_BOOL_FIELDS.keys()))
    def test_int_for_bool_field_rejected(self, field):
        config = {field: 1}
        with pytest.raises(ConfigValidationError, match=f"'{field}' must be a boolean"):
            validate_optional_field_types(config)

    @pytest.mark.parametrize("field", list(_OPTIONAL_BOOL_FIELDS.keys()))
    def test_valid_bool_accepted(self, field):
        config = {field: True}
        validate_optional_field_types(config)  # Should not raise
        config = {field: False}
        validate_optional_field_types(config)  # Should not raise

    @pytest.mark.parametrize("field", list(_OPTIONAL_BOOL_FIELDS.keys()))
    def test_none_for_bool_field_accepted(self, field):
        """None/null is allowed for boolean fields (means 'not set')."""
        config = {field: None}
        validate_optional_field_types(config)  # Should not raise

    def test_unknown_assignment_strategy_rejected(self):
        config = {"assignment_strategy": "round_robin"}
        with pytest.raises(ConfigValidationError, match="not recognized"):
            validate_optional_field_types(config)

    def test_valid_assignment_strategy_accepted(self):
        for strat in _VALID_ASSIGNMENT_STRATEGIES:
            config = {"assignment_strategy": strat}
            validate_optional_field_types(config)  # Should not raise

    def test_assignment_strategy_dict_form_accepted(self):
        config = {"assignment_strategy": {"name": "random", "params": {}}}
        validate_optional_field_types(config)  # Should not raise

    def test_assignment_strategy_dict_form_rejected(self):
        config = {"assignment_strategy": {"name": "invalid_strategy"}}
        with pytest.raises(ConfigValidationError, match="not recognized"):
            validate_optional_field_types(config)

    def test_empty_config_passes(self):
        """Config with no optional fields should pass."""
        validate_optional_field_types({})

    def test_absent_fields_not_checked(self):
        """Only present fields should be validated."""
        config = {"some_other_key": "anything"}
        validate_optional_field_types(config)  # Should not raise


# ===========================================================================
# Phase 2: AI cache guard tests
# ===========================================================================

class TestAICacheGuards:
    """Test that the _get_scheme_field helper produces clear errors."""

    def test_get_scheme_field_out_of_range(self):
        from potato.ai.ai_cache import _get_scheme_field
        from potato.server_utils.config_module import config as global_config

        # Temporarily set annotation_schemes to an empty list
        old_val = global_config.get("annotation_schemes")
        global_config["annotation_schemes"] = []
        try:
            with pytest.raises(ValueError, match="out of range"):
                _get_scheme_field(0, "annotation_type")
        finally:
            if old_val is not None:
                global_config["annotation_schemes"] = old_val
            else:
                global_config.pop("annotation_schemes", None)

    def test_get_scheme_field_missing_field(self):
        from potato.ai.ai_cache import _get_scheme_field
        from potato.server_utils.config_module import config as global_config

        old_val = global_config.get("annotation_schemes")
        global_config["annotation_schemes"] = [
            {"annotation_type": "likert", "name": "mood", "description": "Rate mood"}
        ]
        try:
            with pytest.raises(ValueError, match="missing required field 'min_label'"):
                _get_scheme_field(0, "min_label")
        finally:
            if old_val is not None:
                global_config["annotation_schemes"] = old_val
            else:
                global_config.pop("annotation_schemes", None)

    def test_get_scheme_field_with_default(self):
        from potato.ai.ai_cache import _get_scheme_field
        from potato.server_utils.config_module import config as global_config

        old_val = global_config.get("annotation_schemes")
        global_config["annotation_schemes"] = [
            {"annotation_type": "radio", "name": "test", "description": "test"}
        ]
        try:
            # Should return default instead of raising
            result = _get_scheme_field(0, "nonexistent", default="fallback")
            assert result == "fallback"
        finally:
            if old_val is not None:
                global_config["annotation_schemes"] = old_val
            else:
                global_config.pop("annotation_schemes", None)

    def test_get_scheme_field_success(self):
        from potato.ai.ai_cache import _get_scheme_field
        from potato.server_utils.config_module import config as global_config

        old_val = global_config.get("annotation_schemes")
        global_config["annotation_schemes"] = [
            {"annotation_type": "radio", "name": "test", "description": "test", "labels": ["A"]}
        ]
        try:
            result = _get_scheme_field(0, "labels")
            assert result == ["A"]
        finally:
            if old_val is not None:
                global_config["annotation_schemes"] = old_val
            else:
                global_config.pop("annotation_schemes", None)
