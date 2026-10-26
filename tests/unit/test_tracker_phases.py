"""
Unit tests for the `phases` key of the paradata trackers.

`authenticity`, `keystroke_logging`, `annotation_telemetry` and
`interaction_tracking` accept `phases`: phase types or `phases.order` names.
A typo must be refused at startup, because it would otherwise switch the
tracker off on every page without a word.
"""

from pathlib import Path

import pytest

from potato.phase import UserPhase
from potato.server_utils.config_module import (
    ConfigValidationError,
    KNOWN_CONFIG_KEYS,
    tracker_active_in_phase,
    validate_annotation_telemetry_config,
    validate_authenticity_config,
    validate_keystroke_logging_config,
)
from potato.validate_cli import main

BLOCKS = ("authenticity", "keystroke_logging", "annotation_telemetry",
          "interaction_tracking")
VALIDATORS = {
    "authenticity": validate_authenticity_config,
    "interaction_tracking": validate_authenticity_config,
    "keystroke_logging": validate_keystroke_logging_config,
    "annotation_telemetry": validate_annotation_telemetry_config,
}
PHASES = {
    "order": ["intro", "consent_a", "annotation", "exit"],
    "intro": {"type": "instructions", "file": "intro.json"},
    "consent_a": {"type": "consent", "file": "consent.json"},
    "exit": {"type": "poststudy", "file": "exit.json"},
}


class TestActiveInPhase:
    def test_without_phases_every_page_is_tracked(self):
        for block in BLOCKS:
            for phase in UserPhase:
                assert tracker_active_in_phase(
                    {block: {"enabled": True}}, block, phase, "x")
        assert tracker_active_in_phase({}, "authenticity", None, None)

    def test_phase_type_matches(self):
        cfg = {"authenticity": {"phases": ["annotation"]}}
        assert tracker_active_in_phase(
            cfg, "authenticity", UserPhase.ANNOTATION, "annotation")
        assert not tracker_active_in_phase(
            cfg, "authenticity", UserPhase.CONSENT, "consent_a")

    def test_phase_name_matches_one_page_of_a_type(self):
        cfg = {"keystroke_logging": {"phases": ["exit"]}}
        assert tracker_active_in_phase(
            cfg, "keystroke_logging", UserPhase.POSTSTUDY, "exit")
        assert not tracker_active_in_phase(
            cfg, "keystroke_logging", UserPhase.POSTSTUDY, "other_survey")

    def test_unknown_phase_is_untracked_when_phases_is_set(self):
        cfg = {"authenticity": {"phases": ["annotation"]}}
        assert not tracker_active_in_phase(cfg, "authenticity", None, None)


class TestValidation:
    @pytest.mark.parametrize("block", BLOCKS)
    def test_phases_is_a_known_sub_key(self, block):
        assert "phases" in KNOWN_CONFIG_KEYS[block]

    @pytest.mark.parametrize("block", BLOCKS)
    def test_types_and_order_names_are_accepted(self, block):
        VALIDATORS[block]({"phases": PHASES, block: {
            "enabled": True, "phases": ["annotation", "consent_a", "exit"]}})

    @pytest.mark.parametrize("block", BLOCKS)
    def test_a_typo_is_refused_with_the_valid_values(self, block):
        with pytest.raises(ConfigValidationError) as exc:
            VALIDATORS[block]({"phases": PHASES, block: {
                "enabled": True, "phases": ["concent"]}})
        msg = str(exc.value)
        assert f"{block}.phases" in msg
        assert "'concent'" in msg
        for valid in ("consent", "annotation", "poststudy", "consent_a", "exit"):
            assert valid in msg

    @pytest.mark.parametrize("value", [[], "annotation", [1]])
    def test_wrong_shape_is_refused(self, value):
        with pytest.raises(ConfigValidationError, match="non-empty list"):
            validate_authenticity_config(
                {"authenticity": {"enabled": True, "phases": value}})

    def test_null_means_every_page(self):
        cfg = {"authenticity": {"enabled": True, "phases": None}}
        validate_authenticity_config(cfg)
        assert tracker_active_in_phase(
            cfg, "authenticity", UserPhase.CONSENT, "consent")


def _write(tmp_path: Path, tracker_block: str) -> str:
    (tmp_path / "data.jsonl").write_text('{"id": "1", "text": "hello"}\n')
    (tmp_path / "consent.json").write_text(
        '[{"name": "agree", "annotation_type": "radio", '
        '"description": "Do you agree?", "labels": ["Yes", "No"]}]')
    task_dir = tmp_path.as_posix()
    p = tmp_path / "config.yaml"
    p.write_text(f"""
annotation_task_name: tracker-phases
task_dir: {task_dir}
output_annotation_dir: {task_dir}/output
data_files: [data.jsonl]
item_properties: {{id_key: id, text_key: text}}
annotation_schemes:
  - {{name: label, annotation_type: radio, description: Label, labels: [a, b]}}
phases:
  order: [consent, annotation]
  consent: {{type: consent, file: consent.json}}
{tracker_block}
""")
    return str(p)


class TestValidateCli:
    def test_strict_refuses_a_misspelt_phase(self, tmp_path, capsys):
        path = _write(tmp_path, "authenticity: {enabled: true, phases: [concent]}")
        assert main([path, "--strict"]) != 0
        out = capsys.readouterr()
        text = out.out + out.err
        assert "authenticity.phases" in text
        assert "concent" in text

    def test_strict_accepts_the_study_config(self, tmp_path, capsys):
        path = _write(tmp_path, (
            "authenticity: {enabled: true, phases: [annotation]}\n"
            "keystroke_logging: {enabled: true, phases: [annotation, poststudy]}"))
        assert main([path, "--strict"]) == 0, capsys.readouterr().out
