"""Experiment runner tests against both storage backends."""

import pytest

from potato.eval_datasets.models import Example
from potato.eval_datasets.storage import create_store
from potato.experiments.runner import run_experiment
from potato.experiments.storage import create_experiment_store


@pytest.fixture(params=["file", "sqlite"])
def stores(request, tmp_path):
    backend = request.param
    return create_store(backend, str(tmp_path)), create_experiment_store(backend, str(tmp_path))


def test_run_experiment_with_outputs_map(stores):
    ds, exp_store = stores
    ds.create_dataset("d1")
    ds.add_examples("d1", [
        Example(id="a", inputs={"q": "1+1"}, reference_outputs={"output": "2"}),
        Example(id="b", inputs={"q": "2+2"}, reference_outputs={"output": "4"}),
    ])
    outputs_map = {"a": "2", "b": "5"}  # b is wrong
    exp = run_experiment(
        ds, "d1",
        [{"name": "exact_match"}],
        experiment_id="exp-0001",
        outputs_map=outputs_map,
    )
    assert exp.example_count == 2
    # one of two correct -> mean 0.5
    assert exp.aggregate_scores["exact_match"] == pytest.approx(0.5)
    exp_store.save(exp)
    assert exp_store.get("exp-0001").aggregate_scores["exact_match"] == pytest.approx(0.5)


def test_run_experiment_with_target_callable(stores):
    ds, _ = stores
    ds.create_dataset("d1")
    ds.add_examples("d1", [Example(id="a", inputs={"n": 3}, reference_outputs={"output": "9"})])
    exp = run_experiment(
        ds, "d1",
        [{"name": "exact_match"}],
        experiment_id="exp-0001",
        target=lambda inputs: str(inputs["n"] ** 2),
    )
    assert exp.aggregate_scores["exact_match"] == 1.0


def test_trajectory_evaluator_in_experiment(stores):
    ds, _ = stores
    ds.create_dataset("traj")
    ref = {"conversation": [{"speaker": "Agent (Action)", "text": 'search({"q": "x"})'}]}
    out = {"conversation": [{"speaker": "Agent (Action)", "text": 'search({"q": "x"})'}]}
    ds.add_examples("traj", [
        Example(id="t1", inputs={"task": "find x"}, reference_outputs=ref,
                metadata={"outputs": out}),
    ])
    exp = run_experiment(
        ds, "traj",
        [{"name": "trajectory_match", "params": {"mode": "unordered"}}],
        experiment_id="exp-0001",
    )
    assert exp.aggregate_scores["trajectory_match"] == 1.0


def test_evaluator_error_does_not_abort_run(stores):
    ds, _ = stores
    ds.create_dataset("d1")
    ds.add_examples("d1", [Example(id="a", inputs={}, reference_outputs={"output": "x"})])

    # json_schema_match on non-JSON output -> score 0, not a crash
    exp = run_experiment(
        ds, "d1",
        [{"name": "json_valid"}],
        experiment_id="exp-0001",
        outputs_map={"a": "not json"},
    )
    assert exp.results[0].scores["json_valid"] == 0.0


def test_experiment_compare_listing(stores):
    ds, exp_store = stores
    ds.create_dataset("d1")
    ds.add_examples("d1", [Example(id="a", inputs={}, reference_outputs={"output": "x"})])
    e1 = run_experiment(ds, "d1", [{"name": "exact_match"}], experiment_id="exp-0001",
                        outputs_map={"a": "x"})
    e2 = run_experiment(ds, "d1", [{"name": "exact_match"}], experiment_id="exp-0002",
                        outputs_map={"a": "y"})
    exp_store.save(e1)
    exp_store.save(e2)
    listed = exp_store.list("d1")
    assert {e.id for e in listed} == {"exp-0001", "exp-0002"}
