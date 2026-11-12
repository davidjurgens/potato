"""The training run queue: a run started while another is in flight waits.

First in, first out, one run at a time. The queue is the run ledger (status
``waiting``), so it survives a restart, and a waiting run's bundle is built
when it starts. "Busy" is set by hand here (the manager's own status
dict), so the tests control when a turn comes instead of racing a real fit;
the runs that do start are real sklearn-text runs on the local backend.
"""

import pytest

from potato.training import store
from potato.training.manager import TrainingManager
from tests.unit.test_training_backends import _wait, project  # noqa: F401

PARAMS = {"min_instances": 4}


def _until_done(config, run_ids, timeout=240):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        runs = [store.load_run(config, r) for r in run_ids]
        if all(r.is_terminal for r in runs):
            return runs
        time.sleep(0.3)
    pytest.fail("runs did not finish: %s" % [(r.run_id, r.status) for r in runs])


def _busy(manager, run_id="someone-else"):
    manager._set(state="running", run_id=run_id)


def _idle(manager):
    manager._set(state="success")


def _queue(manager, n):
    outcomes = [manager.start_run("sklearn-text", ["sentiment"], params=PARAMS)
                for _ in range(n)]
    assert all(o.get("queued") for o in outcomes), outcomes
    return outcomes


def test_a_run_started_while_busy_waits_with_its_position(project):  # noqa: F811
    manager = project.manager
    _busy(manager)
    first, second = _queue(manager, 2)
    assert (first["position"], second["position"]) == (1, 2)
    assert first["started"] is False
    assert [q["run_id"] for q in manager.queue()] == [first["run_id"],
                                                      second["run_id"]]
    assert store.load_run(project.config, first["run_id"]).status == "waiting"


def test_waiting_runs_start_in_order_when_the_turn_comes(project):  # noqa: F811
    manager = project.manager
    _busy(manager)
    first, second = _queue(manager, 2)
    _idle(manager)
    assert manager._start_next_waiting() == first["run_id"]
    # The first finishing starts the second, with nobody asking. Read the
    # ledger, not the status: between the two runs the manager is idle.
    runs = _until_done(project.config, [first["run_id"], second["run_id"]])
    assert [r.status for r in runs] == ["success", "success"]
    assert runs[0].finished_at <= runs[1].started_at
    assert manager.queue() == []


def test_queue_false_and_a_full_queue_refuse(project):  # noqa: F811
    manager = project.manager
    _busy(manager)
    refused = manager.start_run("sklearn-text", ["sentiment"], params=PARAMS,
                                queue=False)
    assert refused["started"] is False and not refused.get("queued")
    assert "already in progress" in refused["error"]

    manager.queue_max = 2
    _queue(manager, 2)
    full = manager.start_run("sklearn-text", ["sentiment"], params=PARAMS)
    assert full.get("http_status") == 429 and "queue_max" in full["error"]


def test_a_bad_request_is_refused_now_not_when_its_turn_comes(project):  # noqa: F811
    manager = project.manager
    _busy(manager)
    outcome = manager.start_run("sklearn-text", ["no-such-scheme"])
    assert outcome["started"] is False and not outcome.get("queued")
    assert manager.queue() == []


def test_a_waiting_run_can_be_cancelled(project):  # noqa: F811
    manager = project.manager
    _busy(manager)
    first, second = _queue(manager, 2)
    assert manager.cancel(first["run_id"]) == {"cancelled": True,
                                               "run_id": first["run_id"]}
    run = store.load_run(project.config, first["run_id"])
    assert run.status == "cancelled" and run.error == "Cancelled before it started"
    assert [q["position"] for q in manager.queue()] == [1]
    assert manager.queue()[0]["run_id"] == second["run_id"]


def test_the_queue_survives_a_restart(project):  # noqa: F811
    manager = project.manager
    _busy(manager)
    (waiting,) = _queue(manager, 1)
    manager.shutdown()

    restarted = TrainingManager(project.config)
    restarted._context_from_live_state = manager._context_from_live_state
    try:
        assert restarted.resume_queue() == waiting["run_id"]
        _wait(restarted)
        assert store.load_run(project.config, waiting["run_id"]).status == "success"
    finally:
        restarted.shutdown()


def test_a_run_that_can_no_longer_start_is_failed_and_skipped(project):  # noqa: F811
    manager = project.manager
    _busy(manager)
    first, second = _queue(manager, 2)
    # While it waited, its scheme went away.
    stale = store.load_run(project.config, first["run_id"])
    stale.schema_names = ["removed-scheme"]
    store.record_run(project.config, stale)
    _idle(manager)
    assert manager._start_next_waiting() == second["run_id"]
    failed = store.load_run(project.config, first["run_id"])
    assert failed.status == "error" and failed.error_code == "invalid_when_dequeued"
    _wait(manager)


def test_auto_retrain_does_not_queue(project):  # noqa: F811
    manager = project.manager
    project.config["model_training"]["auto_retrain"] = {
        "enabled": True, "trainer": "sklearn-text", "schemas": ["sentiment"],
        "update_frequency": 1, "min_interval_s": 0, "params": PARAMS}
    _busy(manager)
    _queue(manager, 1)
    _idle(manager)
    # Nothing running, but a run is waiting: auto-retrain leaves it its turn.
    outcome = manager.maybe_auto_retrain()
    assert outcome == {"started": False,
                       "reason": "runs are waiting in the queue"}
    assert len(manager.queue()) == 1


# ---------------------------------------------------------- audit 100

def test_a_dequeue_that_raises_does_not_stick_the_queue(project, monkeypatch):  # noqa: F811
    manager = project.manager
    _busy(manager)
    first, second = _queue(manager, 2)
    _idle(manager)
    real = manager._launch
    calls = []

    def flaky(run):
        calls.append(run.run_id)
        if len(calls) == 1:
            raise RuntimeError("disk full")
        return real(run)
    monkeypatch.setattr(manager, "_launch", flaky)
    assert manager._start_next_waiting_safely() == second["run_id"]
    failed = store.load_run(project.config, first["run_id"])
    assert failed.status == "error" and failed.error_code == "dequeue_failed"
    _until_done(project.config, [second["run_id"]])


def test_a_stuck_queue_is_started_by_the_next_request(project):  # noqa: F811
    manager = project.manager
    _busy(manager)
    (stuck,) = _queue(manager, 1)
    _idle(manager)     # the run ended, but nothing started the waiting one
    outcome = manager.start_run("sklearn-text", ["sentiment"], params=PARAMS)
    assert outcome.get("queued") and outcome["position"] == 1
    assert store.load_run(project.config, stuck["run_id"]).status != "waiting"
    _until_done(project.config, [stuck["run_id"], outcome["run_id"]])


def test_a_run_a_crash_left_running_is_closed_at_startup(project):  # noqa: F811
    for state in ("running", "queued", "building"):
        store.record_run(project.config, store.TrainingRun(
            run_id="crashed-" + state, trainer="sklearn-text",
            schema_names=["sentiment"], status=state))
    restarted = TrainingManager(project.config)
    try:
        restarted.resume_queue()
    finally:
        restarted.shutdown()
    for state in ("running", "queued", "building"):
        run = store.load_run(project.config, "crashed-" + state)
        assert run.status == "error" and run.error_code == "interrupted"
        assert state in run.error


@pytest.mark.parametrize("value", ["abc", None, [], 0, -1, True, 2.5])
def test_a_bad_queue_max_cannot_stop_the_server(value):
    from potato.training.config_check import training_config_problems
    manager = TrainingManager({"task_dir": ".", "model_training": {"queue_max": value}})
    assert manager.queue_max == 10
    problems = training_config_problems({"model_training": {"queue_max": value}})
    assert (value is None) == (problems == []), problems


def test_cancelling_an_unknown_run_names_it(project):  # noqa: F811
    assert project.manager.cancel("nope") == {
        "cancelled": False, "error": "Run nope is not in progress or waiting"}
