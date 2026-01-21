#!/usr/bin/env python
"""
Config Migration Tool for Potato

This module provides utilities to migrate Potato configuration files
from older formats to the current v2 format.

Usage:
    potato migrate config.yaml --to-v2
    potato migrate config.yaml --to-v2 --output new_config.yaml
    potato migrate config.yaml --to-v2 --in-place
    potato migrate config.yaml --to-v2 --dry-run
"""

import argparse
import logging
import os
import sys
import copy
from typing import Dict, Any, List, Tuple
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class MigrationRule:
    """Base class for migration rules."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def applies(self, config: Dict[str, Any]) -> bool:
        """Check if this rule applies to the config."""
        raise NotImplementedError

    def migrate(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        Apply the migration rule.

        Returns:
            Tuple of (migrated_config, list of changes made)
        """
        raise NotImplementedError


class TextareaToMultilineRule(MigrationRule):
    """Migrate textarea.on to multiline format."""

    def __init__(self):
        super().__init__(
            "textarea_to_multiline",
            "Convert textarea.on to multiline format in textbox schemas"
        )

    def applies(self, config: Dict[str, Any]) -> bool:
        """Check if any annotation scheme uses old textarea format."""
        schemes = self._get_all_schemes(config)
        for scheme in schemes:
            if scheme.get("annotation_type") == "text":
                if "textarea" in scheme and isinstance(scheme["textarea"], dict):
                    if scheme["textarea"].get("on"):
                        return True
        return False

    def migrate(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """Convert textarea.on to multiline."""
        config = copy.deepcopy(config)
        changes = []

        schemes = self._get_all_schemes(config)
        for scheme in schemes:
            if scheme.get("annotation_type") == "text":
                if "textarea" in scheme and isinstance(scheme["textarea"], dict):
                    textarea = scheme["textarea"]
                    if textarea.get("on"):
                        # Convert to new format
                        scheme["multiline"] = True
                        if "rows" in textarea:
                            scheme["rows"] = textarea["rows"]
                        if "cols" in textarea:
                            scheme["cols"] = textarea["cols"]

                        # Remove old textarea config
                        del scheme["textarea"]

                        changes.append(
                            f"Converted textarea.on to multiline in schema '{scheme.get('name', 'unknown')}'"
                        )

        return config, changes

    def _get_all_schemes(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get all annotation schemes from config."""
        schemes = []

        # Top-level annotation_schemes
        if "annotation_schemes" in config:
            schemes.extend(config["annotation_schemes"])

        # Phase-level annotation_schemes
        if "phases" in config:
            phases = config["phases"]
            if isinstance(phases, list):
                for phase in phases:
                    if "annotation_schemes" in phase:
                        schemes.extend(phase["annotation_schemes"])
            elif isinstance(phases, dict):
                for phase_name, phase in phases.items():
                    if phase_name != "order" and isinstance(phase, dict):
                        if "annotation_schemes" in phase:
                            schemes.extend(phase["annotation_schemes"])

        # Training annotation_schemes
        if "training" in config and isinstance(config["training"], dict):
            if "annotation_schemes" in config["training"]:
                for scheme in config["training"]["annotation_schemes"]:
                    if isinstance(scheme, dict):
                        schemes.append(scheme)

        return schemes


class LegacyUserConfigRule(MigrationRule):
    """Migrate legacy user_config format."""

    def __init__(self):
        super().__init__(
            "legacy_user_config",
            "Migrate legacy user_config to login format"
        )

    def applies(self, config: Dict[str, Any]) -> bool:
        """Check if config uses legacy user_config without login."""
        has_user_config = "user_config" in config
        has_login = "login" in config

        # If has user_config but no login, and user_config has old format
        if has_user_config and not has_login:
            user_config = config["user_config"]
            # Check for patterns that suggest old format
            if "allow_all_users" in user_config:
                return True
        return False

    def migrate(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """Migrate user_config to login format."""
        config = copy.deepcopy(config)
        changes = []

        if "user_config" in config and "login" not in config:
            user_config = config["user_config"]

            # Determine login type based on user_config
            if user_config.get("allow_all_users", False):
                config["login"] = {
                    "type": "open",
                }
                changes.append("Added login.type: open (from allow_all_users: true)")
            elif user_config.get("users"):
                config["login"] = {
                    "type": "password",
                }
                changes.append("Added login.type: password (user list detected)")

            # user_config is still valid, just add login section
            changes.append("Note: user_config is still valid, login section added for clarity")

        return config, changes


class LegacyOutputFormatRule(MigrationRule):
    """Suggest modern output format options."""

    def __init__(self):
        super().__init__(
            "output_format",
            "Suggest modern output format options"
        )

    def applies(self, config: Dict[str, Any]) -> bool:
        """Check if config uses legacy output format."""
        output_format = config.get("output_annotation_format", "")
        return output_format in ["csv", "tsv"]

    def migrate(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """Add note about JSON format being recommended."""
        config = copy.deepcopy(config)
        changes = []

        output_format = config.get("output_annotation_format", "")
        if output_format in ["csv", "tsv"]:
            changes.append(
                f"Note: output_annotation_format is '{output_format}'. "
                f"Consider using 'json' for richer annotation data (spans, metadata)."
            )

        return config, changes


class DeprecatedSiteConfigRule(MigrationRule):
    """Handle deprecated site configuration options."""

    def __init__(self):
        super().__init__(
            "deprecated_site_config",
            "Migrate deprecated site configuration options"
        )

    def applies(self, config: Dict[str, Any]) -> bool:
        """Check for deprecated site config options."""
        # site_dir: "default" is still valid but could note about auto-generation
        return config.get("site_dir") == "default"

    def migrate(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """Add note about site auto-generation."""
        config = copy.deepcopy(config)
        changes = []

        if config.get("site_dir") == "default":
            changes.append(
                "Note: site_dir: default uses auto-generated templates. "
                "This is the recommended approach for v2."
            )

        return config, changes


class LegacyLabelRequirementRule(MigrationRule):
    """Migrate legacy label_requirement format."""

    def __init__(self):
        super().__init__(
            "legacy_label_requirement",
            "Ensure label_requirement uses modern format"
        )

    def applies(self, config: Dict[str, Any]) -> bool:
        """Check for old label_requirement format."""
        schemes = self._get_all_schemes(config)
        for scheme in schemes:
            if "label_requirement" in scheme:
                lr = scheme["label_requirement"]
                # Check if it's a simple boolean instead of dict
                if isinstance(lr, bool):
                    return True
        return False

    def migrate(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """Convert label_requirement boolean to dict format."""
        config = copy.deepcopy(config)
        changes = []

        schemes = self._get_all_schemes(config)
        for scheme in schemes:
            if "label_requirement" in scheme:
                lr = scheme["label_requirement"]
                if isinstance(lr, bool):
                    scheme["label_requirement"] = {"required": lr}
                    changes.append(
                        f"Converted label_requirement: {lr} to label_requirement.required: {lr} "
                        f"in schema '{scheme.get('name', 'unknown')}'"
                    )

        return config, changes

    def _get_all_schemes(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get all annotation schemes from config."""
        schemes = []
        if "annotation_schemes" in config:
            schemes.extend(config["annotation_schemes"])
        if "phases" in config:
            phases = config["phases"]
            if isinstance(phases, list):
                for phase in phases:
                    if "annotation_schemes" in phase:
                        schemes.extend(phase["annotation_schemes"])
            elif isinstance(phases, dict):
                for phase_name, phase in phases.items():
                    if phase_name != "order" and isinstance(phase, dict):
                        if "annotation_schemes" in phase:
                            schemes.extend(phase["annotation_schemes"])
        return schemes


# All migration rules in order of application
MIGRATION_RULES = [
    TextareaToMultilineRule(),
    LegacyLabelRequirementRule(),
    LegacyUserConfigRule(),
    LegacyOutputFormatRule(),
    DeprecatedSiteConfigRule(),
]


def migrate_config(config: Dict[str, Any], rules: List[MigrationRule] = None) -> Tuple[Dict[str, Any], List[str]]:
    """
    Apply all migration rules to a configuration.

    Args:
        config: The configuration dictionary to migrate
        rules: Optional list of rules to apply (defaults to all rules)

    Returns:
        Tuple of (migrated_config, list of all changes)
    """
    if rules is None:
        rules = MIGRATION_RULES

    all_changes = []
    current_config = copy.deepcopy(config)

    for rule in rules:
        if rule.applies(current_config):
            current_config, changes = rule.migrate(current_config)
            if changes:
                all_changes.append(f"\n[{rule.name}] {rule.description}:")
                all_changes.extend([f"  - {change}" for change in changes])

    return current_config, all_changes


def load_yaml(file_path: str) -> Dict[str, Any]:
    """Load a YAML configuration file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def save_yaml(config: Dict[str, Any], file_path: str) -> None:
    """Save a configuration to a YAML file."""
    with open(file_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def format_yaml(config: Dict[str, Any]) -> str:
    """Format configuration as YAML string."""
    return yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)


def migrate_arguments():
    """Create argument parser for migrate command."""
    parser = argparse.ArgumentParser(
        description="Migrate Potato configuration files to v2 format",
        prog="potato migrate"
    )

    parser.add_argument(
        "config_file",
        help="Path to the configuration file to migrate"
    )

    parser.add_argument(
        "--to-v2",
        action="store_true",
        dest="to_v2",
        help="Migrate to v2 format (required)",
        required=True
    )

    parser.add_argument(
        "--output", "-o",
        dest="output_file",
        help="Output file path (default: print to stdout)"
    )

    parser.add_argument(
        "--in-place", "-i",
        action="store_true",
        dest="in_place",
        help="Modify the config file in place"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what changes would be made without applying them"
    )

    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        dest="quiet",
        help="Suppress informational output"
    )

    return parser


def main(args=None):
    """Main entry point for the migrate command."""
    parser = migrate_arguments()

    if args is None:
        args = parser.parse_args()
    else:
        args = parser.parse_args(args)

    # Validate arguments
    if args.in_place and args.output_file:
        print("Error: Cannot use both --in-place and --output together", file=sys.stderr)
        return 1

    # Check config file exists
    if not os.path.exists(args.config_file):
        print(f"Error: Configuration file not found: {args.config_file}", file=sys.stderr)
        return 1

    # Load configuration
    try:
        config = load_yaml(args.config_file)
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in configuration file: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: Failed to read configuration file: {e}", file=sys.stderr)
        return 1

    if config is None:
        print("Error: Configuration file is empty", file=sys.stderr)
        return 1

    # Apply migrations
    migrated_config, changes = migrate_config(config)

    # Report changes
    if not args.quiet:
        if changes:
            print("Migration changes:", file=sys.stderr)
            for change in changes:
                print(change, file=sys.stderr)
            print("", file=sys.stderr)
        else:
            print("No migrations needed - config is already up to date.", file=sys.stderr)

    # Handle dry-run
    if args.dry_run:
        if not args.quiet:
            print("Dry run - no changes written.", file=sys.stderr)
            if changes:
                print("\nMigrated configuration would be:", file=sys.stderr)
                print(format_yaml(migrated_config))
        return 0

    # Output the migrated config
    if args.in_place:
        save_yaml(migrated_config, args.config_file)
        if not args.quiet:
            print(f"Updated {args.config_file} in place.", file=sys.stderr)
    elif args.output_file:
        save_yaml(migrated_config, args.output_file)
        if not args.quiet:
            print(f"Wrote migrated config to {args.output_file}", file=sys.stderr)
    else:
        # Print to stdout
        print(format_yaml(migrated_config))

    return 0


if __name__ == "__main__":
    sys.exit(main())
