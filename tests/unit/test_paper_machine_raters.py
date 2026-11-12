"""Paper Mode describes people: declared machine raters are left out."""

import json
import os

import yaml

from potato.paper.collect import collect_project
from potato.paper.metrics import compute_metrics


def _write_state(out_dir, user, label, origin=None):
    d = os.path.join(out_dir, user)
    os.makedirs(d, exist_ok=True)
    state = {"user_id": user, "instance_id_to_label_to_value": {
        "i1": [[{"schema": "s", "name": label}, True]],
        "i2": [[{"schema": "s", "name": label}, True]]}}
    if origin:
        state["origin"] = origin
    with open(os.path.join(d, "user_state.json"), "w") as f:
        json.dump(state, f)


def test_machine_raters_are_excluded_and_counted(tmp_path):
    out = tmp_path / "annotation_output"
    _write_state(str(out), "alice", "pos")
    _write_state(str(out), "bob", "pos")
    _write_state(str(out), "gpt", "neg", origin={"kind": "llm", "id": "gpt"})
    _write_state(str(out), "pipeline", "neg")   # declared in the config only
    cfg = {"annotation_task_name": "t", "output_annotation_dir": "annotation_output",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio",
                                   "labels": ["pos", "neg"]}],
           "machine_annotators": {"enabled": True, "annotators": [
               {"id": "pipeline", "kind": "tool", "tool": "x"}]}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    project = collect_project(str(path))
    assert sorted(project.annotators) == ["alice", "bob"]
    assert sorted(project.machine_raters) == ["gpt", "pipeline"]
    m = compute_metrics(project)
    assert m["n_annotators"] == 2 and m["n_machine_raters_excluded"] == 2
