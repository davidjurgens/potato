"""
Pytest plugin for Potato evaluations — run evaluators in your own test suite and
gate CI on aggregate score thresholds.

    import pytest
    from potato.testing import expect

    @pytest.mark.potato_eval
    def test_answer(potato_eval):
        out = my_agent("2+2")
        potato_eval.log_outputs(out)
        potato_eval.log_feedback("correct", 1.0 if out == "4" else 0.0)
        expect(out).to_contain("4")

Run with gating:

    pytest --potato-threshold correct=0.8 --potato-experiment my-suite

If the mean ``correct`` across eval tests drops below 0.8, the run fails. With
``--potato-experiment`` the run is also recorded as an Experiment (written to
``$POTATO_EVAL_STORE`` / ``./eval_store``) so it shows in the comparison view.

The plugin is inert unless eval tests run or thresholds are set, so it's safe to
auto-load alongside an existing suite.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest


# ----- collector -----

class EvalCase:
    """Per-test handle injected via the ``potato_eval`` fixture."""

    def __init__(self, test_id: str, record: Dict[str, Any]):
        self.test_id = test_id
        self._record = record

    def log_inputs(self, inputs: Any) -> None:
        self._record["inputs"] = inputs

    def log_outputs(self, outputs: Any) -> None:
        self._record["outputs"] = outputs

    def log_reference_outputs(self, reference: Any) -> None:
        self._record["reference_outputs"] = reference

    def log_feedback(self, key: str, score: float) -> None:
        self._record["feedback"][key] = float(score)


class EvalCollector:
    def __init__(self):
        self.records: Dict[str, Dict[str, Any]] = {}

    def case(self, test_id: str) -> EvalCase:
        rec = self.records.setdefault(test_id, {
            "test_id": test_id, "inputs": None, "outputs": None,
            "reference_outputs": None, "feedback": {},
        })
        return EvalCase(test_id, rec)

    def aggregate(self) -> Dict[str, float]:
        sums: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for rec in self.records.values():
            for k, v in rec["feedback"].items():
                sums[k] = sums.get(k, 0.0) + v
                counts[k] = counts.get(k, 0) + 1
        return {k: sums[k] / counts[k] for k in sums if counts[k]}

    def has_data(self) -> bool:
        return any(rec["feedback"] for rec in self.records.values())


# ----- pytest hooks -----

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "potato_eval: mark a test as a Potato evaluation case")
    config._potato_collector = EvalCollector()
    config._potato_report = {}


def pytest_addoption(parser):
    group = parser.getgroup("potato", "Potato evaluation")
    group.addoption("--potato-threshold", action="append", default=[], metavar="KEY=MIN",
                    help="Fail if mean(KEY) < MIN. Repeatable.")
    group.addoption("--potato-experiment", default=os.environ.get("POTATO_EVAL_EXPERIMENT"),
                    metavar="DATASET", help="Record results as an Experiment for this dataset.")
    group.addoption("--potato-no-sync", action="store_true",
                    help="Disable experiment recording even if --potato-experiment is set.")


@pytest.fixture
def potato_eval(request):
    """Per-test eval handle: log_inputs/outputs/reference_outputs/feedback."""
    collector = request.config._potato_collector
    return collector.case(request.node.nodeid)


def _parse_thresholds(raw: List[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for item in raw:
        if "=" in item:
            k, v = item.split("=", 1)
            try:
                out[k.strip()] = float(v)
            except ValueError:
                pass
    return out


def compute_violations(aggregates: Dict[str, float],
                       thresholds: Dict[str, float]) -> List[tuple]:
    """Return (key, actual, minimum) for each threshold not met. Missing key
    counts as a violation (actual=None)."""
    violations = []
    for key, minimum in thresholds.items():
        actual = aggregates.get(key)
        if actual is None or actual < minimum:
            violations.append((key, actual, minimum))
    return violations


def _sync_experiment(config, aggregates: Dict[str, float]) -> Optional[str]:
    dataset = config.getoption("--potato-experiment")
    if not dataset or config.getoption("--potato-no-sync"):
        return None
    try:
        from potato.experiments.models import Experiment, ExperimentResult
        from potato.experiments.storage import create_experiment_store
        base = os.environ.get("POTATO_EVAL_STORE", "./eval_store")
        backend = os.environ.get("POTATO_EVAL_STORAGE", "file")
        store = create_experiment_store(backend, base)
        exp_id = f"ci-{len(store.list(dataset)) + 1:04d}"
        collector: EvalCollector = config._potato_collector
        results = [ExperimentResult(
            example_id=rec["test_id"], outputs=rec["outputs"],
            scores=rec["feedback"], results=[],
        ) for rec in collector.records.values()]
        store.save(Experiment(
            id=exp_id, dataset_name=dataset, dataset_version="ci",
            created_at=datetime.now().isoformat(timespec="seconds"),
            name=os.environ.get("POTATO_EVAL_SUITE", "ci"),
            metadata={"source": "pytest", "git_sha": os.environ.get("GITHUB_SHA", "")},
            aggregate_scores=aggregates, example_count=len(results), results=results,
        ))
        return exp_id
    except Exception as e:  # never let sync break the run
        config._potato_report["sync_error"] = str(e)
        return None


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    collector: EvalCollector = getattr(config, "_potato_collector", None)
    if collector is None or not collector.has_data():
        return

    aggregates = collector.aggregate()
    thresholds = _parse_thresholds(config.getoption("--potato-threshold"))
    violations = compute_violations(aggregates, thresholds)

    synced = _sync_experiment(config, aggregates)
    config._potato_report.update({
        "aggregates": aggregates, "violations": violations,
        "thresholds": thresholds, "synced": synced,
        "n_cases": len(collector.records),
    })

    # Gate the build: fail the session if a threshold was violated.
    if violations and session.exitstatus == 0:
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    report = getattr(config, "_potato_report", {}) or {}
    if not report.get("aggregates"):
        return
    tr = terminalreporter
    tr.write_sep("=", "Potato evaluation")
    tr.write_line(f"cases: {report['n_cases']}")
    for key, score in sorted(report["aggregates"].items()):
        thr = report["thresholds"].get(key)
        suffix = f"  (threshold {thr})" if thr is not None else ""
        tr.write_line(f"  {key}: {score:.3f}{suffix}")
    if report.get("synced"):
        tr.write_line(f"recorded experiment: {report['synced']}")
    if report.get("sync_error"):
        tr.write_line(f"experiment sync failed: {report['sync_error']}")
    for key, actual, minimum in report.get("violations", []):
        shown = "n/a" if actual is None else f"{actual:.3f}"
        tr.write_line(f"THRESHOLD FAILED: {key} = {shown} < {minimum}")
