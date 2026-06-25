"""
Experiment runner.

Executes a set of evaluators against a dataset version and produces an
``Experiment`` record. The "target" — how each example's outputs are produced —
is pluggable:

  - ``target`` callable: ``outputs = target(inputs)`` (SDK / pytest / live app)
  - ``outputs_map``: a precomputed ``{example_id: outputs}`` (offline scoring)
  - otherwise outputs are read from ``example.metadata['outputs']`` or
    ``example.inputs['outputs']`` (traces already carrying the agent run)

Evaluators are specified declaratively as ``{"name": ..., "params": {...}}`` and
built via the evaluators registry, so the same runner serves the admin UI, the
automation engine, and the CI plugin.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from potato.eval_datasets.models import Example
from potato.eval_datasets.storage import DatasetStore
from potato.evaluators.registry import build_evaluator
from potato.experiments.models import Experiment, ExperimentResult

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _example_outputs(
    example: Example,
    target: Optional[Callable[[Dict[str, Any]], Any]],
    outputs_map: Optional[Dict[str, Any]],
) -> Any:
    if target is not None:
        return target(example.inputs)
    if outputs_map is not None and example.id in outputs_map:
        return outputs_map[example.id]
    if "outputs" in example.metadata:
        return example.metadata["outputs"]
    if isinstance(example.inputs, dict) and "outputs" in example.inputs:
        return example.inputs["outputs"]
    return example.inputs


def run_experiment(
    dataset_store: DatasetStore,
    dataset_name: str,
    evaluator_specs: List[Dict[str, Any]],
    *,
    experiment_id: str,
    name: str = "",
    target: Optional[Callable[[Dict[str, Any]], Any]] = None,
    outputs_map: Optional[Dict[str, Any]] = None,
    as_of: str = "latest",
    splits: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Experiment:
    """Run evaluators over a dataset version and return an Experiment record."""
    version_id = dataset_store.resolve_version(dataset_name, as_of) or as_of
    examples = dataset_store.list_examples(dataset_name, as_of=as_of, splits=splits)

    # Build evaluators once (reused across examples).
    evaluators = []
    for spec in evaluator_specs:
        ev = build_evaluator(spec["name"], spec.get("params"))
        # Track the configured key so per-spec keys don't collide.
        evaluators.append((spec.get("key", ev.key), ev))

    results: List[ExperimentResult] = []
    score_accum: Dict[str, List[float]] = {}

    for ex in examples:
        outputs = _example_outputs(ex, target, outputs_map)
        ex_scores: Dict[str, Optional[float]] = {}
        ex_results: List[Dict[str, Any]] = []
        for key, ev in evaluators:
            try:
                r = ev.evaluate(
                    outputs=outputs,
                    reference_outputs=ex.reference_outputs,
                    inputs=ex.inputs,
                )
            except Exception as e:  # one evaluator failing must not abort the run
                logger.error(f"Evaluator '{key}' failed on example {ex.id}: {e}")
                ex_scores[key] = None
                ex_results.append({"key": key, "score": None, "comment": f"error: {e}"})
                continue
            ex_scores[key] = r.score
            ex_results.append(r.to_dict())
            if r.score is not None:
                score_accum.setdefault(key, []).append(r.score)
        results.append(ExperimentResult(
            example_id=ex.id, outputs=outputs, scores=ex_scores, results=ex_results,
        ))

    aggregate = {k: (sum(v) / len(v)) for k, v in score_accum.items() if v}

    return Experiment(
        id=experiment_id,
        dataset_name=dataset_name,
        dataset_version=version_id,
        created_at=_now(),
        name=name,
        metadata=metadata or {},
        aggregate_scores=aggregate,
        example_count=len(examples),
        results=results,
    )
