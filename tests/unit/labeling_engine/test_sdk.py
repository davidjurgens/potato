"""The Python SDK over a real config file: run, label, certify, export."""

import json
import os
import shutil

import pytest
import yaml

from potato.persistence import clear_db_cache


@pytest.fixture(autouse=True)
def _restore_global_config():
    """load_study goes through init_config, which merges the file into the
    process-wide config dict; without this the engine block outlived these
    tests and broke the next app any later test built."""
    from potato.server_utils import config_module
    saved = dict(config_module.config)
    yield
    config_module.config.clear()
    config_module.config.update(saved)


@pytest.fixture
def study_dir(monkeypatch):
    # load_study resolves data paths as the server does; the unit-suite's
    # path-validation skip would bypass that.
    monkeypatch.delenv("POTATO_SKIP_CONFIG_PATH_VALIDATION", raising=False)
    d = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "output",
                                     "engine_sdk_test"))
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "data"))
    with open(os.path.join(d, "data", "items.jsonl"), "w") as f:
        for k in range(80):
            f.write(json.dumps({"id": f"x{k}", "text": f"t{k}",
                                "gold": "a" if k % 3 else "b"}) + "\n")
    cfg = {"task_dir": ".", "annotation_task_name": "sdk", "output_annotation_dir": "out",
           "data_files": ["data/items.jsonl"],
           "item_properties": {"id_key": "id", "text_key": "text"},
           "user_config": {"allow_all_users": True},
           "annotation_schemes": [{"name": "s", "annotation_type": "radio",
                                   "labels": ["a", "b"], "description": "d"}],
           "labeling_engine": {"enabled": True,
                               "sources": [{"id": "fx", "kind": "fixture"}],
                               "contracts": [{"id": "p", "kind": "ppi", "schema": "s"}],
                               "humans": {"calibration_rate": 0.5}}}
    with open(os.path.join(d, "config.yaml"), "w") as f:
        yaml.safe_dump(cfg, f)
    clear_db_cache()
    yield d
    clear_db_cache()
    shutil.rmtree(d, ignore_errors=True)


def test_round_trip(study_dir):
    from potato.labeling_engine.sdk import Study
    st = Study(os.path.join(study_dir, "config.yaml"))
    st.run()
    assert st.status()["predictions"] == 80
    reqs = st.requests(status="open")
    assert reqs
    gold = {json.loads(l)["id"]: json.loads(l)["gold"]
            for l in open(os.path.join(study_dir, "data", "items.jsonl"))}
    for r in reqs:
        st.label(r.item_id, r.schema, gold[r.item_id], "sdk-user", request_id=r.id)
    assert st.certify()["s"]["p"]["status"] == "met"
    st.run()
    res = st.export(os.path.join(study_dir, "bundle"))
    assert res.success and res.stats["by_origin"].get("human") == len(reqs)
    assert st.certificate("md").startswith("# Labeling certificate")


def test_run_refuses_while_another_writer_holds_the_study(study_dir):
    from potato.labeling_engine.sdk import Study
    st = Study(os.path.join(study_dir, "config.yaml"))
    assert st.engine.store.acquire_writer("server-elsewhere")
    with pytest.raises(RuntimeError, match="server-elsewhere"):
        st.run()


@pytest.mark.parametrize("argv", [
    ["run", "--json"],
    ["status", "--json"],
    ["certify", "--json"],
    ["certificate", "--format", "json"],
])
def test_cli_json_output_is_the_only_thing_on_stdout(study_dir, argv, capfd):
    # init_config printed a notice to stdout, so every `--json | jq` and
    # json.loads(stdout) broke on the first line.
    from potato.labeling_engine.cli import main
    cfg = os.path.join(study_dir, "config.yaml")
    if argv[0] != "run":
        assert main(["run", cfg]) == 0
        capfd.readouterr()
    assert main([argv[0], cfg] + argv[1:]) == 0
    json.loads(capfd.readouterr().out)


def test_cli_calls_is_json_lines_on_stdout(study_dir, capfd):
    from potato.labeling_engine.cli import main
    cfg = os.path.join(study_dir, "config.yaml")
    assert main(["run", cfg]) == 0
    capfd.readouterr()
    assert main(["calls", cfg]) == 0
    lines = [l for l in capfd.readouterr().out.splitlines() if l.strip()]
    assert lines and all(json.loads(l) for l in lines)


def test_a_failing_source_does_not_stop_the_cascade_and_run_says_so(study_dir, capfd):
    """Found by potato-skill (H1): a misconfigured tier failed the whole
    cascade, `label run` exited 0, and status said nothing."""
    from potato.labeling_engine.cli import main
    path = os.path.join(study_dir, "config.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f)
    cfg["labeling_engine"]["sources"] = [
        {"id": "broken", "kind": "static", "predictions_file": "missing.jsonl"},
        {"id": "fx", "kind": "fixture"}]
    cfg["labeling_engine"]["cascade"] = ["broken", "fx"]
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f)
    code = main(["run", path, "--until", "predicted", "--json"])
    out, err = capfd.readouterr()
    assert code == 1 and "s/broken" in err
    status = json.loads(out)["status"]
    src = status["schemes"]["s"]["sources"]
    assert src["broken"]["last_run"]["status"] == "failed"
    assert "missing.jsonl" in src["broken"]["last_run"]["message"]
    # The next tier still ran, on every item: the failed tier escalated none.
    assert src["fx"]["ok"] + src["fx"]["abstain"] == 80


def test_a_source_whose_every_answer_fails_makes_run_exit_non_zero(study_dir, capfd):
    """Found by potato-skill (H4): a source with a wrong key logged 60 errors
    and run printed an ordinary insufficient study, exit 0."""
    from potato.labeling_engine.cli import main
    path = os.path.join(study_dir, "config.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f)
    # Every answer is off the label list: an error per item.
    cfg["labeling_engine"]["sources"] = [{"id": "col", "kind": "static", "field": "gold"}]
    cfg["annotation_schemes"][0]["labels"] = ["c", "d"]
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f)
    code = main(["run", path, "--until", "predicted"])
    out, err = capfd.readouterr()
    assert code == 1 and "s/col" in err
    assert "source col: 0 ok" in out and "not one of" in out


def test_an_invalid_engine_block_is_one_bullet_per_problem_and_no_traceback(study_dir,
                                                                           capfd):
    """Found by potato-skill (I8)."""
    from potato.labeling_engine.cli import main
    from potato.validate_cli import validate_config_file
    path = os.path.join(study_dir, "config.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f)
    cfg["labeling_engine"]["contracts"] = [{"id": "plan", "kind": "budget_first",
                                            "schema": "s"}]
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f)
    report = validate_config_file(path)
    assert report.errors == ["labeling_engine.contracts[0] needs human_labels or human_usd"]
    assert main(["run", path]) == 1
    out, err = capfd.readouterr()
    assert "Traceback" not in out + err and "needs human_labels" in out + err


def test_cli_certify_refuses_while_a_server_drives_the_study(study_dir, capfd):
    """Found by potato-skill (A7): certify wrote contract results and spent
    looks behind a running server's planner."""
    from potato.labeling_engine.cli import main
    from potato.labeling_engine.sdk import Study
    path = os.path.join(study_dir, "config.yaml")
    st = Study(path)
    assert st.engine.store.acquire_writer("server-elsewhere")
    assert main(["certify", path]) == 2
    assert "server-elsewhere is driving this study" in capfd.readouterr().err
    assert st.engine.store.latest_contract_version("p") is None
