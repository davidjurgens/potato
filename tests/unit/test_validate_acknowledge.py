"""
`validation.acknowledge` lets a study accept a warning it expects.

`potato validate --strict` fails on every warning. Some warnings are expected
for a given design (under `assignment_strategy: engine` a free-text scheme is
always reported, because the engine cannot label it), and an agent could not
tell "expected here" from "fix this". Reported by the potato-skill agent as U1.

Matching is by substring of the warning text, with a minimum length so a short
entry cannot silence unrelated problems, and an entry that matches nothing is
reported so a stale acknowledgement cannot hide the next problem.
"""

import yaml

from potato.validate_cli import main, validate_config_file

UNKNOWN = "annotation_schemes[s].legacy_flag"


def write(tmp_path, acknowledge=None, extra_key=True):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "d.jsonl").write_text('{"id": "1", "text": "hi"}\n')
    scheme = {"annotation_type": "radio", "name": "s", "description": "d",
              "labels": ["a", "b"]}
    if extra_key:
        scheme["legacy_flag"] = True
    config = {
        "annotation_task_name": "probe",
        "task_dir": ".",
        "output_annotation_dir": "out/",
        "data_files": ["data/d.jsonl"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [scheme],
    }
    if acknowledge is not None:
        config["validation"] = {"acknowledge": acknowledge}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    return str(path)


def test_without_acknowledgement_strict_fails(tmp_path):
    path = write(tmp_path)
    assert any(UNKNOWN in k for k in validate_config_file(path).unknown_keys)
    assert main([path, "--strict", "--quiet"]) == 1


def test_an_acknowledged_warning_does_not_fail_strict(tmp_path):
    path = write(tmp_path, acknowledge=[UNKNOWN])
    report = validate_config_file(path)
    assert report.unknown_keys == []
    assert report.other_warnings == []
    assert any(UNKNOWN in w for w in report.acknowledged)
    assert main([path, "--strict", "--quiet"]) == 0


def test_the_validation_block_is_itself_a_known_key(tmp_path):
    report = validate_config_file(write(tmp_path, acknowledge=[UNKNOWN]))
    assert not any("'validation" in k for k in report.unknown_keys + report.acknowledged)


def test_a_short_entry_is_refused(tmp_path):
    report = validate_config_file(write(tmp_path, acknowledge=["legacy"]))
    assert any(UNKNOWN in k for k in report.unknown_keys), "must not have matched"
    assert any("shorter than" in w for w in report.other_warnings)


def test_a_stale_entry_is_reported(tmp_path):
    path = write(tmp_path, acknowledge=[UNKNOWN], extra_key=False)
    report = validate_config_file(path)
    assert any("matches no warning" in w for w in report.other_warnings)
    assert main([path, "--strict", "--quiet"]) == 1


def test_a_non_list_is_reported_and_ignored(tmp_path):
    report = validate_config_file(write(tmp_path, acknowledge=UNKNOWN))
    assert any("must be a list" in w for w in report.other_warnings)
    assert any(UNKNOWN in k for k in report.unknown_keys)


def test_json_report_carries_the_acknowledged_list(tmp_path):
    report = validate_config_file(write(tmp_path, acknowledge=[UNKNOWN]))
    assert report.to_dict()["acknowledged"] == report.acknowledged
