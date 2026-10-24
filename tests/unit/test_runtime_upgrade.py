"""Audit 96 R3: records from the jsPsych phase before runtime phases existed
are read, not dropped."""

import sqlite3
import time

from potato.user_state_management import upgrade_flow_record
from tests.helpers.test_utils import create_test_directory


def test_old_flow_record_key_becomes_runtimes():
    rec = upgrade_flow_record({"jspsych": {"stroop": {"status": "complete", "run_id": "r1"}},
                               "conditions": {"g": "a"}})
    assert "jspsych" not in rec
    assert rec["runtimes"]["stroop"] == {"status": "complete", "run_id": "r1", "kind": "jspsych"}
    assert rec["conditions"] == {"g": "a"}


def test_old_runs_table_is_copied():
    d = create_test_directory("runtime_upgrade_db")
    conn = sqlite3.connect(f"{d}/project.sqlite")
    conn.executescript("""CREATE TABLE jspsych_runs (run_id TEXT PRIMARY KEY, project TEXT NOT NULL,
        user_id TEXT NOT NULL, phase TEXT, page TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
        n_trials INTEGER NOT NULL DEFAULT 0, conditions TEXT, interaction TEXT, data BLOB);""")
    conn.execute("INSERT INTO jspsych_runs (run_id, project, user_id, page, status, started_at, "
                 "n_trials) VALUES ('old1', 'proj', 'u1', 'stroop', 'complete', ?, 3)", (time.time(),))
    conn.commit()
    conn.close()
    from potato.runtimes import store
    store._upgraded.discard(d)
    run = store.get_run(d, "old1")
    assert run is not None and run["runtime"] == "jspsych" and run["n_trials"] == 3


def test_participants_export_reads_an_old_record():
    """Audit 96 R3 re-verify: the export read user_state.json off disk without
    the upgrade, so an old jsPsych run left runtime_runs empty."""
    import csv
    import json
    import os
    from potato.export.base import ExportContext
    from potato.export.experiment_sidecars import write_participants
    d = create_test_directory("runtime_upgrade_export")
    os.makedirs(f"{d}/u1", exist_ok=True)
    with open(f"{d}/u1/user_state.json", "w") as f:
        json.dump({"user_id": "u1", "flow_record": {
            "conditions": {"g": "a"},
            "jspsych": {"stroop": {"status": "complete", "run_id": "r1", "n_trials": 3}}}}, f)
    config = {"conditions": {"factors": {"g": ["a", "b"]}}, "output_annotation_dir": d}
    ctx = ExportContext(config=config, annotations=[], items={}, schemas=[], output_dir=d)
    path = write_participants(ctx, d, "csv", ",")
    row = next(csv.DictReader(open(path)))
    runs = json.loads(row["runtime_runs"])
    assert runs["stroop"]["kind"] == "jspsych" and runs["stroop"]["n_trials"] == 3
