"""participants.<fmt> and trials.<fmt> sidecars (potato/export/experiment_sidecars.py)."""

import csv
import json
import os

from potato.export.base import ExportContext
from potato.export.experiment_sidecars import write_participants, write_trials
from tests.helpers.test_utils import create_test_directory


def _write_state(out_dir, user_id, **extra):
    d = os.path.join(out_dir, user_id)
    os.makedirs(d, exist_ok=True)
    state = {"user_id": user_id, "current_phase_and_page": ["done", None]}
    state.update(extra)
    with open(os.path.join(d, "user_state.json"), "w") as f:
        json.dump(state, f)


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _context(config, out_dir):
    return ExportContext(config=config, annotations=[], items={}, schemas=[], output_dir=out_dir)


def test_participants_table():
    base = create_test_directory("sidecar_participants")
    out = os.path.join(base, "annotation_output")
    _write_state(out, "alice", flow_record={
        "conditions": {"feedback": "none"}, "condition_ordinal": 0,
        "skipped_pages": [{"page": "smoking"}], "page_orders": {"group_0": ["b", "a"]},
        "jspsych": {"stroop": {"status": "complete", "attempts": 1, "n_trials": 37, "run_id": "r1"}}})
    _write_state(out, "bob", flow_record={
        "conditions": {"feedback": "immediate"}, "condition_ordinal": 1,
        "screened_out": {"page": "screener", "at": 1.0}})
    config = {"conditions": {"factors": {"feedback": ["none", "immediate"]}}}
    path = write_participants(_context(config, out), base, "csv", ",")
    rows = {r["user_id"]: r for r in _rows(path)}
    assert rows["alice"]["condition_feedback"] == "none"
    assert rows["alice"]["skipped_pages"] == "smoking"
    assert json.loads(rows["alice"]["jspsych_runs"])["stroop"]["n_trials"] == 37
    assert rows["bob"]["screened_out"] == "1" and rows["bob"]["screened_out_page"] == "screener"


def test_participants_skipped_without_flow_features():
    base = create_test_directory("sidecar_participants_off")
    out = os.path.join(base, "annotation_output")
    _write_state(out, "alice")
    assert write_participants(_context({}, out), base, "csv", ",") is None


def test_trials_table_includes_timeouts():
    base = create_test_directory("sidecar_trials")
    out = os.path.join(base, "annotation_output")
    _write_state(out, "alice", flow_record={"conditions": {"feedback": "none"}},
                 instance_id_to_trial={
                     "w1": {"outcome": "response", "key": "f", "label": "word", "rt_ms": 512.5,
                            "onset_epoch_ms": 1000, "flags": [],
                            "intended": {"fixation_ms": 500, "trial_duration_ms": 2000}},
                     "w2": {"outcome": "timeout", "onset_epoch_ms": 4000,
                            "flags": ["tab_hidden"], "tab_hidden": True,
                            "previous_attempts": [{"outcome": "timeout"}]}})
    config = {"trial_timing": {"enabled": True},
              "conditions": {"factors": {"feedback": ["none", "immediate"]}}}
    rows = _rows(write_trials(_context(config, out), base, "csv", ","))
    assert [r["instance_id"] for r in rows] == ["w1", "w2"]
    assert rows[0]["rt_ms"] == "512.5" and rows[0]["intended_fixation_ms"] == "500"
    assert rows[0]["condition_feedback"] == "none"
    assert rows[1]["outcome"] == "timeout" and rows[1]["label"] == ""
    assert rows[1]["flags"] == "tab_hidden" and rows[1]["previous_attempts"] == "1"


def test_trials_skipped_when_off():
    base = create_test_directory("sidecar_trials_off")
    out = os.path.join(base, "annotation_output")
    _write_state(out, "alice", instance_id_to_trial={"w1": {"outcome": "timeout"}})
    assert write_trials(_context({}, out), base, "csv", ",") is None


def test_sidecars_written_when_no_item_was_annotated():
    """Audit 94 re-verify, J5: a jsPsych-only or all-timeout study wrote no
    participants.csv because the CSV export returned before the sidecars."""
    from potato.export.tabular_exporter import _write_delimited
    base = create_test_directory("sidecar_no_rows")
    out = os.path.join(base, "annotation_output")
    _write_state(out, "alice", flow_record={
        "conditions": {"feedback": "none"},
        "jspsych": {"stroop": {"status": "complete", "attempts": 1, "page_loads": 2,
                               "n_trials": 37, "run_id": "r1"}}},
                 instance_id_to_trial={"w1": {"outcome": "timeout", "onset_epoch_ms": 1}})
    config = {"conditions": {"factors": {"feedback": ["none", "immediate"]}},
              "trial_timing": {"enabled": True}}
    ctx = ExportContext(config=config, annotations=[], items={}, schemas=[], output_dir=out)
    result = _write_delimited(ctx, base, "csv", ",")
    names = {os.path.basename(p) for p in result.files_written}
    assert {"participants.csv", "trials.csv"} <= names
    row = _rows(os.path.join(base, "participants.csv"))[0]
    assert json.loads(row["jspsych_runs"])["stroop"]["page_loads"] == 2


def test_csv_cli_writes_sidecars_without_annotations():
    """Audit 94 re-verify, J5 one level up: CSVExporter.can_export refused a
    study with no item annotations, so the CLI never reached the sidecars."""
    import subprocess
    import sys
    import yaml
    base = create_test_directory("sidecar_cli_no_rows")
    out = os.path.join(base, "annotation_output")
    _write_state(out, "alice", flow_record={
        "conditions": {"feedback": "none"},
        "jspsych": {"stroop": {"status": "complete", "attempts": 1, "page_loads": 1,
                               "n_trials": 3, "run_id": "r1"}}})
    with open(os.path.join(base, "data.jsonl"), "w") as f:
        f.write(json.dumps({"id": "i1", "text": "x"}) + "\n")
    cfg = {"annotation_task_name": "cli", "task_dir": ".", "output_annotation_dir": "annotation_output",
           "data_files": ["data.jsonl"], "item_properties": {"id_key": "id", "text_key": "text"},
           "annotation_schemes": [{"name": "r", "annotation_type": "radio", "labels": ["a", "b"],
                                   "description": "d"}],
           "conditions": {"factors": {"feedback": ["none", "immediate"]}}}
    with open(os.path.join(base, "config.yaml"), "w") as f:
        yaml.safe_dump(cfg, f)
    export_dir = os.path.join(base, "export")
    r = subprocess.run([sys.executable, "-m", "potato.export", "--config",
                        os.path.join(base, "config.yaml"), "--format", "csv",
                        "--output", export_dir], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.exists(os.path.join(export_dir, "participants.csv")), r.stdout + r.stderr
