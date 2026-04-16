"""
Config file validator CLI.

Usage:
    python -m potato.validate_cli <config.yaml>
    python -m potato.validate_cli <config.yaml> --strict
    python -m potato.validate_cli <config.yaml> --json

Checks performed:
    1. YAML parses cleanly
    2. All required top-level keys present (item_properties, data_files,
       task_dir, output_annotation_dir, annotation_task_name)
    3. Deep structural validation (annotation_schemes, phases, auth, etc.)
       via config_module.validate_yaml_structure()
    4. Unrecognized keys at any nesting level via validate_unknown_keys()

Exit codes:
    0 — all checks passed
    1 — fatal errors found (invalid YAML, missing required fields,
        structural errors)
    2 — warnings only (unrecognized keys) and --strict was passed

In default mode unknown keys are reported but do not fail the exit
code. Use --strict to treat them as fatal (useful for CI).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

import yaml

from potato.server_utils.config_module import (
    ConfigValidationError,
    ConfigSecurityError,
    validate_yaml_structure,
)


@dataclass
class ValidationReport:
    config_file: str
    ok: bool
    errors: List[str] = field(default_factory=list)
    unknown_keys: List[str] = field(default_factory=list)
    other_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "config_file": self.config_file,
            "ok": self.ok,
            "errors": self.errors,
            "unknown_keys": self.unknown_keys,
            "other_warnings": self.other_warnings,
        }


class _WarningCollector(logging.Handler):
    """Captures WARNING-level records from config_module.

    `validate_unknown_keys()` logs unrecognized keys as WARNINGs on the
    `potato.server_utils.config_module` logger rather than raising. We
    install this handler around the validation call to collect them.
    """

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.unknown_keys: List[str] = []
        self.other_warnings: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        # validate_unknown_keys emits this exact prefix
        if "Unrecognized config key" in msg:
            self.unknown_keys.append(msg)
        else:
            self.other_warnings.append(msg)


def validate_config_file(config_file: str) -> ValidationReport:
    """Validate a single config file and return a structured report."""
    report = ValidationReport(config_file=config_file, ok=True)

    # Existence and readability
    if not os.path.isfile(config_file):
        report.ok = False
        report.errors.append(f"Config file not found: {config_file}")
        return report

    # YAML parse
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        report.ok = False
        report.errors.append(f"YAML parse error: {e}")
        return report
    except OSError as e:
        report.ok = False
        report.errors.append(f"Could not read file: {e}")
        return report

    if config_data is None:
        report.ok = False
        report.errors.append("Config file is empty")
        return report

    if not isinstance(config_data, dict):
        report.ok = False
        report.errors.append(
            f"Config root must be a YAML mapping (got {type(config_data).__name__})"
        )
        return report

    # Capture unknown-key warnings while running the full validator
    logger = logging.getLogger("potato.server_utils.config_module")
    collector = _WarningCollector()
    # Save and override propagation so the handler actually sees records
    prior_level = logger.level
    prior_propagate = logger.propagate
    logger.addHandler(collector)
    logger.setLevel(logging.WARNING)
    logger.propagate = False

    config_file_dir = os.path.dirname(os.path.abspath(config_file))
    try:
        validate_yaml_structure(
            config_data,
            project_dir=config_file_dir,
            config_file_dir=config_file_dir,
        )
    except (ConfigValidationError, ConfigSecurityError) as e:
        report.ok = False
        report.errors.append(str(e))
    except Exception as e:
        # Surface unexpected errors but do not crash the CLI
        report.ok = False
        report.errors.append(f"Unexpected validation error ({type(e).__name__}): {e}")
    finally:
        logger.removeHandler(collector)
        logger.setLevel(prior_level)
        logger.propagate = prior_propagate

    report.unknown_keys = collector.unknown_keys
    report.other_warnings = collector.other_warnings
    return report


def _format_human(report: ValidationReport) -> str:
    lines = []
    lines.append(f"Config: {report.config_file}")
    if report.errors:
        lines.append("")
        lines.append("ERRORS:")
        for e in report.errors:
            lines.append(f"  - {e}")
    if report.unknown_keys:
        lines.append("")
        lines.append("UNKNOWN KEYS:")
        for w in report.unknown_keys:
            lines.append(f"  - {w}")
    if report.other_warnings:
        lines.append("")
        lines.append("OTHER WARNINGS:")
        for w in report.other_warnings:
            lines.append(f"  - {w}")
    lines.append("")
    if report.ok and not report.unknown_keys and not report.other_warnings:
        lines.append("OK — no issues found.")
    elif report.ok and report.unknown_keys:
        lines.append(
            f"OK with {len(report.unknown_keys)} unknown-key warning(s). "
            "Re-run with --strict to fail on unknown keys."
        )
    else:
        lines.append(f"FAILED — {len(report.errors)} error(s).")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="potato.validate_cli",
        description=(
            "Validate a Potato YAML config file: checks required keys, "
            "deep structural constraints, and unrecognized keys."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes:\n"
            "  0 — all checks passed\n"
            "  1 — fatal errors (invalid YAML, missing required fields,\n"
            "      structural errors, or unknown keys with --strict)\n"
        ),
    )
    parser.add_argument("config_file", help="Path to YAML config file")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat unknown keys as fatal (exit 1 instead of just warning)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit JSON report on stdout instead of human-readable text",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only emit output if there are errors or (in --strict) warnings",
    )
    args = parser.parse_args(argv)

    report = validate_config_file(args.config_file)

    fatal = not report.ok or (args.strict and bool(report.unknown_keys))

    if args.emit_json:
        print(json.dumps(report.to_dict(), indent=2))
    elif not args.quiet or fatal or report.unknown_keys or report.other_warnings:
        print(_format_human(report))

    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
