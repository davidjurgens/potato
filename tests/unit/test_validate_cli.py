"""
Unit tests for the config validator CLI (`potato.validate_cli`).

Covers:
- Required-field enforcement
- Unknown-key detection (with and without --strict)
- YAML parse errors
- File-not-found / empty / non-dict configs
- JSON output format
- Quiet mode
- A valid config passes cleanly
"""

import json
from pathlib import Path

import pytest

from potato.validate_cli import (
    main,
    validate_config_file,
    ValidationReport,
)


# =====================================================================
# Helpers
# =====================================================================


def _write_config(tmp_path: Path, body: str) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(body)
    return str(p)


def _minimal_valid_config(task_dir: str) -> str:
    """A config that satisfies required-field validation."""
    return f"""
annotation_task_name: Test Task
task_dir: {task_dir}
output_annotation_dir: {task_dir}/output
data_files:
  - data.jsonl
item_properties:
  id_key: id
  text_key: text
annotation_schemes:
  - name: sentiment
    annotation_type: radio
    labels:
      - positive
      - negative
    description: Rate the sentiment
port: 8000
host: 0.0.0.0
"""


# =====================================================================
# validate_config_file — programmatic API
# =====================================================================


class TestValidateConfigFile:
    def test_valid_minimal_config_ok(self, tmp_path):
        config_file = _write_config(tmp_path, _minimal_valid_config(str(tmp_path)))
        report = validate_config_file(config_file)
        assert report.ok is True
        assert report.errors == []

    def test_missing_required_fields(self, tmp_path):
        config_file = _write_config(
            tmp_path,
            """
annotation_task_name: Incomplete
item_properties:
  id_key: id
  text_key: text
""",
        )
        report = validate_config_file(config_file)
        assert report.ok is False
        assert any("Missing required" in e for e in report.errors)
        # Should specifically name the missing fields
        err = " ".join(report.errors)
        assert "data_files" in err
        assert "task_dir" in err
        assert "output_annotation_dir" in err

    def test_file_not_found(self, tmp_path):
        report = validate_config_file(str(tmp_path / "does_not_exist.yaml"))
        assert report.ok is False
        assert any("not found" in e for e in report.errors)

    def test_empty_file(self, tmp_path):
        config_file = _write_config(tmp_path, "")
        report = validate_config_file(config_file)
        assert report.ok is False
        assert any("empty" in e.lower() for e in report.errors)

    def test_malformed_yaml(self, tmp_path):
        config_file = _write_config(
            tmp_path,
            """
task_dir: .
annotation_task_name: Test
invalid: here
   bad: indent
""",
        )
        report = validate_config_file(config_file)
        assert report.ok is False
        assert any("YAML parse error" in e for e in report.errors)

    def test_non_dict_root(self, tmp_path):
        """Root must be a mapping, not a list or scalar."""
        config_file = _write_config(tmp_path, "- just\n- a\n- list\n")
        report = validate_config_file(config_file)
        assert report.ok is False
        assert any("YAML mapping" in e or "mapping" in e for e in report.errors)

    def test_unknown_top_level_key_warns_but_does_not_fail(self, tmp_path):
        body = _minimal_valid_config(str(tmp_path)) + "\nnonexistent_key: some_value\n"
        config_file = _write_config(tmp_path, body)
        report = validate_config_file(config_file)
        # Unknown keys are warnings, not errors
        assert report.ok is True
        assert any("nonexistent_key" in w for w in report.unknown_keys)

    def test_unknown_nested_key_detected(self, tmp_path):
        body = _minimal_valid_config(str(tmp_path)) + """
authentication:
  method: in_memory
  totally_bogus_subkey: true
"""
        config_file = _write_config(tmp_path, body)
        report = validate_config_file(config_file)
        assert report.ok is True
        # Nested path should be reported
        assert any(
            "authentication.totally_bogus_subkey" in w for w in report.unknown_keys
        )

    def test_multiple_unknown_keys_all_reported(self, tmp_path):
        body = (
            _minimal_valid_config(str(tmp_path))
            + "\nfoo_key: 1\nbar_key: 2\nbaz_key: 3\n"
        )
        config_file = _write_config(tmp_path, body)
        report = validate_config_file(config_file)
        assert len(report.unknown_keys) == 3

    def test_ai_support_requires_endpoint_type(self, tmp_path):
        """Enabled ai_support without endpoint_type must fail."""
        body = (
            _minimal_valid_config(str(tmp_path))
            + """
ai_support:
  enabled: true
  ai_config:
    temperature: 0.5
"""
        )
        config_file = _write_config(tmp_path, body)
        report = validate_config_file(config_file)
        assert report.ok is False
        assert any("endpoint_type" in e for e in report.errors)

    def test_ai_config_file_defers_endpoint_type_check(self, tmp_path):
        """When ai_config_file is set, endpoint_type may live in the external
        file — validator should not require it in the YAML."""
        body = (
            _minimal_valid_config(str(tmp_path))
            + """
ai_support:
  enabled: true
  ai_config_file: ai-config.yaml
  ai_config:
    temperature: 0.5
"""
        )
        config_file = _write_config(tmp_path, body)
        report = validate_config_file(config_file)
        assert report.ok is True, f"Unexpected errors: {report.errors}"


# =====================================================================
# main() — CLI entry point
# =====================================================================


class TestMainEntry:
    def test_valid_config_exits_zero(self, tmp_path, capsys):
        config_file = _write_config(tmp_path, _minimal_valid_config(str(tmp_path)))
        rc = main([config_file])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OK" in out

    def test_missing_required_exits_one(self, tmp_path, capsys):
        config_file = _write_config(tmp_path, "annotation_task_name: Bad\n")
        rc = main([config_file])
        assert rc == 1
        out = capsys.readouterr().out
        assert "FAILED" in out
        assert "Missing required" in out

    def test_unknown_key_non_strict_exits_zero(self, tmp_path, capsys):
        body = _minimal_valid_config(str(tmp_path)) + "\nbogus_key: x\n"
        config_file = _write_config(tmp_path, body)
        rc = main([config_file])
        assert rc == 0
        out = capsys.readouterr().out
        assert "bogus_key" in out

    def test_unknown_key_strict_exits_one(self, tmp_path, capsys):
        body = _minimal_valid_config(str(tmp_path)) + "\nbogus_key: x\n"
        config_file = _write_config(tmp_path, body)
        rc = main([config_file, "--strict"])
        assert rc == 1

    def test_json_output_is_valid_json(self, tmp_path, capsys):
        config_file = _write_config(tmp_path, _minimal_valid_config(str(tmp_path)))
        rc = main([config_file, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is True
        assert parsed["config_file"] == config_file
        assert parsed["errors"] == []
        assert parsed["unknown_keys"] == []

    def test_json_output_includes_errors_on_failure(self, tmp_path, capsys):
        config_file = _write_config(
            tmp_path, "item_properties: {id_key: id, text_key: t}\n"
        )
        rc = main([config_file, "--json"])
        assert rc == 1
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is False
        assert len(parsed["errors"]) >= 1

    def test_quiet_mode_silent_on_success(self, tmp_path, capsys):
        config_file = _write_config(tmp_path, _minimal_valid_config(str(tmp_path)))
        rc = main([config_file, "--quiet"])
        assert rc == 0
        out = capsys.readouterr().out
        assert out == ""

    def test_quiet_mode_prints_errors(self, tmp_path, capsys):
        config_file = _write_config(tmp_path, "annotation_task_name: x\n")
        rc = main([config_file, "--quiet"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "FAILED" in out

    def test_quiet_mode_prints_unknown_keys_even_without_strict(self, tmp_path, capsys):
        body = _minimal_valid_config(str(tmp_path)) + "\nbogus_key: x\n"
        config_file = _write_config(tmp_path, body)
        rc = main([config_file, "--quiet"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "bogus_key" in out

    def test_file_not_found_exits_one(self, tmp_path, capsys):
        rc = main([str(tmp_path / "missing.yaml")])
        assert rc == 1
        out = capsys.readouterr().out
        assert "not found" in out.lower()

    def test_strict_with_nested_unknown_key(self, tmp_path, capsys):
        body = _minimal_valid_config(str(tmp_path)) + """
authentication:
  method: in_memory
  mystery_field: value
"""
        config_file = _write_config(tmp_path, body)
        rc = main([config_file, "--strict"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "authentication.mystery_field" in out


# =====================================================================
# Log capture isolation
# =====================================================================


class TestLogCaptureIsolation:
    """The validator must not leave log handlers attached after running."""

    def test_handler_removed_after_run(self, tmp_path):
        import logging
        logger = logging.getLogger("potato.server_utils.config_module")
        before = list(logger.handlers)

        config_file = _write_config(tmp_path, _minimal_valid_config(str(tmp_path)))
        validate_config_file(config_file)

        after = list(logger.handlers)
        assert len(after) == len(before), (
            "validate_config_file leaked a log handler"
        )

    def test_handler_removed_even_on_error(self, tmp_path):
        import logging
        logger = logging.getLogger("potato.server_utils.config_module")
        before = list(logger.handlers)

        config_file = _write_config(tmp_path, "annotation_task_name: x\n")
        validate_config_file(config_file)

        after = list(logger.handlers)
        assert len(after) == len(before)
