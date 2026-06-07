#!/usr/bin/env python3
"""
Unit tests for the config migration CLI tool.

Tests migration rules that convert old config formats to v2.
"""

import pytest
import copy
from potato.migrate_cli import (
    migrate_config,
    HighlightToSpanRule,
    TextareaToMultilineRule,
    LegacyLabelRequirementRule,
    LegacyUserConfigRule,
    LegacyOutputFormatRule,
    MIGRATION_RULES,
)
from potato.server_utils.schemas.registry import schema_registry


class TestHighlightToSpanRule:
    """F-050: the v1 'highlight' annotation type must be renamed to 'span'.

    This is the single most common v1->v2 breaking change (MIGRATION.md). A
    config that still says `annotation_type: highlight` is rejected at boot with
    "Unknown annotation type: highlight", so the migrator MUST rename it or the
    "migrated" config still fails to start.
    """

    def test_detects_highlight_type(self):
        rule = HighlightToSpanRule()
        config = {"annotation_schemes": [
            {"annotation_type": "highlight", "name": "entities"}]}
        assert rule.applies(config) is True

    def test_ignores_modern_span_type(self):
        rule = HighlightToSpanRule()
        config = {"annotation_schemes": [
            {"annotation_type": "span", "name": "entities"}]}
        assert rule.applies(config) is False

    def test_renames_highlight_to_span(self):
        rule = HighlightToSpanRule()
        config = {"annotation_schemes": [
            {"annotation_type": "highlight", "name": "entities",
             "labels": ["PERSON", "ORG"]}]}
        migrated, changes = rule.migrate(config)
        assert migrated["annotation_schemes"][0]["annotation_type"] == "span"
        # other fields preserved
        assert migrated["annotation_schemes"][0]["labels"] == ["PERSON", "ORG"]
        assert any("highlight" in c and "span" in c for c in changes)

    def test_does_not_touch_keyword_highlight_settings(self):
        """Only annotation_type values change — unrelated 'highlight*' keys stay."""
        rule = HighlightToSpanRule()
        config = {
            "keyword_highlights_file": "kw.json",
            "highlight_linebreaks": True,
            "annotation_schemes": [
                {"annotation_type": "highlight", "name": "h"},
                {"annotation_type": "radio", "name": "r"},
            ],
        }
        migrated, _ = rule.migrate(config)
        assert migrated["keyword_highlights_file"] == "kw.json"
        assert migrated["highlight_linebreaks"] is True
        assert migrated["annotation_schemes"][0]["annotation_type"] == "span"
        assert migrated["annotation_schemes"][1]["annotation_type"] == "radio"

    def test_renames_inside_phases_and_training(self):
        """highlight schemes nested in phases (list & dict) and training are renamed."""
        rule = HighlightToSpanRule()
        config = {
            "phases": {
                "order": ["annotation"],
                "annotation": {"annotation_schemes": [
                    {"annotation_type": "highlight", "name": "p_dict"}]},
            },
            "training": {"annotation_schemes": [
                {"annotation_type": "highlight", "name": "t"}]},
            "annotation_schemes": [
                {"annotation_type": "highlight", "name": "top"}],
        }
        migrated, changes = rule.migrate(config)
        assert migrated["annotation_schemes"][0]["annotation_type"] == "span"
        assert migrated["phases"]["annotation"]["annotation_schemes"][0]["annotation_type"] == "span"
        assert migrated["training"]["annotation_schemes"][0]["annotation_type"] == "span"
        assert len(changes) == 3

    def test_migrated_config_passes_v2_type_validation(self):
        """End-to-end: a v1 highlight config validates as a real v2 type after migration."""
        config = {"annotation_schemes": [
            {"annotation_type": "highlight", "name": "entities"}]}
        migrated, _ = migrate_config(config)
        new_type = migrated["annotation_schemes"][0]["annotation_type"]
        assert new_type in schema_registry.get_supported_types()

    def test_idempotent(self):
        """Re-running on already-migrated output is a no-op for this rule."""
        rule = HighlightToSpanRule()
        config = {"annotation_schemes": [
            {"annotation_type": "span", "name": "entities"}]}
        assert rule.applies(config) is False


class TestTextareaToMultilineRule:
    """Tests for textarea.on to multiline migration."""

    def test_detects_old_textarea_format(self):
        """Test that old textarea format is detected."""
        config = {
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "comments",
                    "description": "Add comments",
                    "textarea": {
                        "on": True,
                        "rows": 5,
                        "cols": 50
                    }
                }
            ]
        }
        rule = TextareaToMultilineRule()
        assert rule.applies(config) is True

    def test_no_detection_for_new_format(self):
        """Test that new multiline format is not flagged."""
        config = {
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "comments",
                    "description": "Add comments",
                    "multiline": True,
                    "rows": 5,
                    "cols": 50
                }
            ]
        }
        rule = TextareaToMultilineRule()
        assert rule.applies(config) is False

    def test_migrates_textarea_to_multiline(self):
        """Test that textarea.on is converted to multiline."""
        config = {
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "comments",
                    "description": "Add comments",
                    "textarea": {
                        "on": True,
                        "rows": 5,
                        "cols": 50
                    }
                }
            ]
        }
        rule = TextareaToMultilineRule()
        migrated, changes = rule.migrate(config)

        # Check multiline is set
        assert migrated["annotation_schemes"][0]["multiline"] is True

        # Check rows and cols are at top level
        assert migrated["annotation_schemes"][0]["rows"] == 5
        assert migrated["annotation_schemes"][0]["cols"] == 50

        # Check textarea is removed
        assert "textarea" not in migrated["annotation_schemes"][0]

        # Check changes were logged
        assert len(changes) == 1
        assert "multiline" in changes[0]

    def test_migrates_textarea_without_rows_cols(self):
        """Test migration when rows/cols not specified."""
        config = {
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "comments",
                    "description": "Add comments",
                    "textarea": {
                        "on": True
                    }
                }
            ]
        }
        rule = TextareaToMultilineRule()
        migrated, changes = rule.migrate(config)

        assert migrated["annotation_schemes"][0]["multiline"] is True
        assert "rows" not in migrated["annotation_schemes"][0]
        assert "cols" not in migrated["annotation_schemes"][0]
        assert "textarea" not in migrated["annotation_schemes"][0]

    def test_handles_phases_format(self):
        """Test migration in phase-based configs."""
        config = {
            "phases": [
                {
                    "name": "annotation",
                    "annotation_schemes": [
                        {
                            "annotation_type": "text",
                            "name": "comments",
                            "description": "Add comments",
                            "textarea": {
                                "on": True,
                                "rows": 3
                            }
                        }
                    ]
                }
            ]
        }
        rule = TextareaToMultilineRule()
        assert rule.applies(config) is True

        migrated, changes = rule.migrate(config)
        assert migrated["phases"][0]["annotation_schemes"][0]["multiline"] is True
        assert migrated["phases"][0]["annotation_schemes"][0]["rows"] == 3


class TestLegacyLabelRequirementRule:
    """Tests for label_requirement boolean to dict migration."""

    def test_detects_boolean_label_requirement(self):
        """Test that boolean label_requirement is detected."""
        config = {
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "Select sentiment",
                    "labels": ["positive", "negative"],
                    "label_requirement": True
                }
            ]
        }
        rule = LegacyLabelRequirementRule()
        assert rule.applies(config) is True

    def test_no_detection_for_dict_format(self):
        """Test that dict format is not flagged."""
        config = {
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "Select sentiment",
                    "labels": ["positive", "negative"],
                    "label_requirement": {"required": True}
                }
            ]
        }
        rule = LegacyLabelRequirementRule()
        assert rule.applies(config) is False

    def test_migrates_boolean_to_dict(self):
        """Test that boolean is converted to dict format."""
        config = {
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "Select sentiment",
                    "labels": ["positive", "negative"],
                    "label_requirement": True
                }
            ]
        }
        rule = LegacyLabelRequirementRule()
        migrated, changes = rule.migrate(config)

        assert migrated["annotation_schemes"][0]["label_requirement"] == {"required": True}
        assert len(changes) == 1

    def test_migrates_false_boolean(self):
        """Test migration of false boolean."""
        config = {
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "optional_field",
                    "description": "Optional field",
                    "labels": ["a", "b"],
                    "label_requirement": False
                }
            ]
        }
        rule = LegacyLabelRequirementRule()
        migrated, changes = rule.migrate(config)

        assert migrated["annotation_schemes"][0]["label_requirement"] == {"required": False}


class TestLegacyUserConfigRule:
    """Tests for user_config to login migration."""

    def test_detects_allow_all_users(self):
        """Test detection of allow_all_users pattern."""
        config = {
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": []
        }
        rule = LegacyUserConfigRule()
        assert rule.applies(config) is True

    def test_no_detection_when_login_exists(self):
        """Test that configs with login are not flagged."""
        config = {
            "login": {"type": "open"},
            "user_config": {
                "allow_all_users": True
            },
            "annotation_schemes": []
        }
        rule = LegacyUserConfigRule()
        assert rule.applies(config) is False

    def test_adds_open_login(self):
        """Test that open login is added for allow_all_users."""
        config = {
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": []
        }
        rule = LegacyUserConfigRule()
        migrated, changes = rule.migrate(config)

        assert "login" in migrated
        assert migrated["login"]["type"] == "open"
        assert len(changes) >= 1

    def test_adds_password_login_for_users(self):
        """Test that password login is added when users list exists."""
        config = {
            "user_config": {
                "allow_all_users": False,
                "users": ["user1", "user2"]
            },
            "annotation_schemes": []
        }
        rule = LegacyUserConfigRule()
        migrated, changes = rule.migrate(config)

        assert "login" in migrated
        assert migrated["login"]["type"] == "password"


class TestLegacyOutputFormatRule:
    """Tests for output format suggestions."""

    def test_detects_csv_format(self):
        """Test that CSV format is detected."""
        config = {
            "output_annotation_format": "csv",
            "annotation_schemes": []
        }
        rule = LegacyOutputFormatRule()
        assert rule.applies(config) is True

    def test_detects_tsv_format(self):
        """Test that TSV format is detected."""
        config = {
            "output_annotation_format": "tsv",
            "annotation_schemes": []
        }
        rule = LegacyOutputFormatRule()
        assert rule.applies(config) is True

    def test_no_detection_for_json(self):
        """Test that JSON format is not flagged."""
        config = {
            "output_annotation_format": "json",
            "annotation_schemes": []
        }
        rule = LegacyOutputFormatRule()
        assert rule.applies(config) is False

    def test_adds_note_about_json(self):
        """Test that a note about JSON is added."""
        config = {
            "output_annotation_format": "csv",
            "annotation_schemes": []
        }
        rule = LegacyOutputFormatRule()
        migrated, changes = rule.migrate(config)

        # Config should not be modified
        assert migrated["output_annotation_format"] == "csv"

        # But a note should be added
        assert len(changes) == 1
        assert "json" in changes[0].lower()


class TestMigrateConfig:
    """Tests for the main migrate_config function."""

    def test_applies_all_rules(self):
        """Test that all applicable rules are applied."""
        config = {
            "user_config": {
                "allow_all_users": True
            },
            "output_annotation_format": "tsv",
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "comments",
                    "description": "Add comments",
                    "textarea": {
                        "on": True
                    }
                }
            ]
        }

        migrated, changes = migrate_config(config)

        # Check textarea was migrated
        assert migrated["annotation_schemes"][0]["multiline"] is True

        # Check login was added
        assert "login" in migrated

        # Check multiple changes were logged
        assert len(changes) > 2

    def test_no_changes_for_modern_config(self):
        """Test that modern configs have no changes."""
        config = {
            "login": {"type": "open"},
            "output_annotation_format": "json",
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "comments",
                    "description": "Add comments",
                    "multiline": True
                }
            ]
        }

        migrated, changes = migrate_config(config)

        # No structural changes (only notes may be present)
        assert migrated["annotation_schemes"][0] == config["annotation_schemes"][0]

    def test_preserves_unrelated_fields(self):
        """Test that unrelated fields are preserved."""
        config = {
            "port": 8000,
            "annotation_task_name": "My Task",
            "custom_field": {"nested": "value"},
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "comments",
                    "description": "Add comments",
                    "textarea": {"on": True}
                }
            ]
        }

        migrated, changes = migrate_config(config)

        # Check unrelated fields are preserved
        assert migrated["port"] == 8000
        assert migrated["annotation_task_name"] == "My Task"
        assert migrated["custom_field"] == {"nested": "value"}

    def test_does_not_modify_original(self):
        """Test that original config is not modified."""
        config = {
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "comments",
                    "description": "Add comments",
                    "textarea": {"on": True}
                }
            ]
        }
        original = copy.deepcopy(config)

        migrate_config(config)

        # Original should be unchanged
        assert config == original


class TestMigrationRulesOrder:
    """Tests to ensure migration rules are in correct order."""

    def test_all_rules_have_required_methods(self):
        """Test that all rules implement required methods."""
        for rule in MIGRATION_RULES:
            assert hasattr(rule, 'applies')
            assert hasattr(rule, 'migrate')
            assert hasattr(rule, 'name')
            assert hasattr(rule, 'description')

    def test_rules_return_correct_types(self):
        """Test that rules return correct types."""
        config = {"annotation_schemes": []}

        for rule in MIGRATION_RULES:
            # applies should return bool
            result = rule.applies(config)
            assert isinstance(result, bool)

            # migrate should return tuple of (dict, list)
            if result:
                migrated, changes = rule.migrate(config)
                assert isinstance(migrated, dict)
                assert isinstance(changes, list)
