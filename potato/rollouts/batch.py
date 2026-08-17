"""
Running the rollout judge over a whole project, and scoring it against people.

``POST /api/rollout/judge`` judges the annotator's *current* item, which is the
right shape for a single interactive check and the wrong shape for the thing
the judge exists for. The point of a machine break-point is not to help one
annotator; it is to make an automated world-model benchmark **checkable** —
"our metric agrees with human judgement" becomes a number instead of a claim —
and that needs every item judged and every judgement compared.

## The human side has to be built, not read

There is no single human break-point to compare against. There are N
annotators, each of whom either marked a break on a stream, marked it clean, or
never got to it, and the three are different answers.
:func:`human_consensus` collapses them per stream:

- if more annotators marked the stream **clean** than marked a break, the
  consensus is "no break" — a real answer the judge can be right or wrong about;
- if more marked a break, the consensus time is the **median** of their marks
  and the category is the modal one. Median, not mean: one annotator who marked
  the wrong moment entirely should move the consensus by one position, not drag
  it halfway across the clip;
- a stream nobody answered about contributes nothing. Counting silence as
  "clean" would manufacture agreement with a judge that also found nothing.

## Judging is not free and this does not pretend otherwise

One model call per stream, plus an ffmpeg seek per sampled frame. A four-panel
comparison over 500 items is 2000 calls. The runner therefore reports what it
skipped and why, takes an explicit item limit, and never runs itself.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Where predictions are persisted, beside the LLM-judge ones. Keyed by prompt
#: version so re-running after a prompt change compares like with like rather
#: than silently overwriting the previous run's evidence.
PREDICTIONS_FILE = "rollout_predictions.json"


def predictions_path(config: Dict[str, Any]) -> str:
    from potato.server_utils import judge_alignment

    return os.path.join(os.path.dirname(judge_alignment.predictions_path(config)),
                        PREDICTIONS_FILE)


def load_predictions(config: Dict[str, Any]) -> Dict[str, Dict[str, dict]]:
    path = predictions_path(config)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle) or {}
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return {}


def save_predictions(config: Dict[str, Any],
                     predictions: Dict[str, Dict[str, dict]]) -> None:
    path = predictions_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(predictions, handle, indent=2)


def rollout_schemas(config: Dict[str, Any]) -> List[dict]:
    """Every ``rollout_evaluation`` scheme in the config."""
    schemes = list(config.get("annotation_schemes") or [])
    for phase in (config.get("phases") or {}).values():
        if isinstance(phase, dict):
            schemes.extend(phase.get("annotation_schemes") or [])
    return [s for s in schemes if isinstance(s, dict)
            and s.get("annotation_type") == "rollout_evaluation"]


# ---------------------------------------------------------------------------
# The human side
# ---------------------------------------------------------------------------

def human_consensus(schema: Dict[str, Any],
                    rows: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    ``{f"{instance}::{stream}": {"t": seconds or None, "type": category}}``.

    ``rows`` is ``{instance_id: {annotator: stored_value}}`` — the same raw
    shape the agreement report takes, so the consensus the judge is scored
    against is derived from exactly the annotations the humans were scored on.
    """
    from potato.server_utils import annotation_values
    from potato.server_utils.iaa import rollouts as rollout_iaa

    consensus: Dict[str, Dict[str, Any]] = {}
    for instance_id, per_user in rows.items():
        parsed = {}
        for user_id, stored in per_user.items():
            value = annotation_values.rollout_value(schema, stored)
            if value is not None:
                parsed[user_id] = value
        if not parsed:
            continue

        streams = set()
        for value in parsed.values():
            streams |= rollout_iaa.answered_streams(value.get("violations"),
                                                    value.get("clean"))

        for stream_id in sorted(streams):
            times: List[float] = []
            types: List[str] = []
            clean_votes = 0
            for value in parsed.values():
                marks = rollout_iaa.by_stream(value.get("violations")).get(
                    stream_id, [])
                if marks:
                    # The earliest mark: the question is where the rollout
                    # *stops* making sense, so a second mark later in the same
                    # stream is a further failure, not a competing answer.
                    first = min(marks, key=lambda m: _as_float(m.get("t")))
                    time = _as_float(first.get("t"))
                    if time is not None:
                        times.append(time)
                        types.append(str(first.get("type") or ""))
                elif stream_id in set(value.get("clean") or []):
                    clean_votes += 1

            if not times and not clean_votes:
                continue  # nobody answered about this stream
            key = f"{instance_id}::{stream_id}"
            if len(times) > clean_votes:
                consensus[key] = {"t": _median(times),
                                  "type": Counter(types).most_common(1)[0][0],
                                  "n_marked": len(times),
                                  "n_clean": clean_votes}
            else:
                consensus[key] = {"t": None, "type": "",
                                  "n_marked": len(times),
                                  "n_clean": clean_votes}
    return consensus


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


# ---------------------------------------------------------------------------
# The batch
# ---------------------------------------------------------------------------

def run_judge_batch(config: Dict[str, Any],
                    schema_names: Optional[Sequence[str]] = None,
                    max_items: Optional[int] = None,
                    stream_ids: Optional[Sequence[str]] = None,
                    prompt_version: str = "") -> Dict[str, Any]:
    """
    Judge every rollout in the project and persist the predictions.

    Returns a summary naming what was judged and what was skipped. Skips are
    reported rather than logged because a run that quietly judged 40 of 500
    items and reported success would produce an alignment number over a sample
    nobody chose.
    """
    from potato.ai.rollout_judge import RolloutJudge
    from potato.item_state_management import get_item_state_manager
    from potato.rollouts.models import RolloutError
    from potato.rollouts.registry import read_rollout_set
    from potato.rollouts.routes import (
        _default_types, _local_path, _manifest_resolver, _visual_endpoint)

    endpoint = _visual_endpoint()
    if endpoint is None:
        return {"error": "No vision-capable AI endpoint is configured. "
                         "Judging a rollout needs a model that can see the "
                         "frames.", "judged": 0}

    manager = get_item_state_manager()
    if manager is None:
        return {"error": "No items are loaded.", "judged": 0}

    wanted = set(schema_names or [])
    schemas = [s for s in rollout_schemas(config)
               if not wanted or s.get("name") in wanted]
    if not schemas:
        return {"error": "No rollout_evaluation schema is configured.",
                "judged": 0}

    stored = load_predictions(config)
    judged = failed = 0
    skipped: List[str] = []
    for schema in schemas:
        schema_name = schema.get("name") or ""
        types = [t.get("name") if isinstance(t, dict) else str(t)
                 for t in (schema.get("violation_types") or _default_types())]
        options = dict((schema.get("ai_support") or {}).get("judge") or {})
        judge = RolloutJudge(config, endpoint, options)

        seen = 0
        for instance_id, item in manager.iter_items():
            if max_items is not None and seen >= max_items:
                skipped.append(f"{schema_name}: stopped at the {max_items}-item "
                               f"limit")
                break
            try:
                rollout = read_rollout_set(
                    item.get_data() or {}, schema, set_id=str(instance_id),
                    resolve_manifest=_manifest_resolver())
            except RolloutError as exc:
                skipped.append(f"{instance_id}: {exc}")
                continue
            seen += 1

            for stream in rollout.streams:
                if stream_ids and stream.stream_id not in stream_ids:
                    continue
                path = _local_path(stream.url)
                if path is None:
                    skipped.append(
                        f"{instance_id}::{stream.stream_id}: not a local file, "
                        f"so its frames cannot be sampled")
                    continue
                prediction = judge.judge_stream(
                    path, stream.duration or rollout.duration, types,
                    instance_id=str(instance_id), schema_name=schema_name,
                    stream_id=stream.stream_id, prompt=rollout.prompt,
                    prompt_version=prompt_version)
                payload = prediction.to_dict()
                version = payload.get("prompt_version") or prompt_version or "v0"
                stored.setdefault(version, {})[
                    f"{instance_id}::{schema_name}::{stream.stream_id}"] = payload
                if payload.get("error"):
                    failed += 1
                else:
                    judged += 1

    save_predictions(config, stored)
    return {"judged": judged, "failed": failed, "skipped": skipped,
            "n_skipped": len(skipped),
            "schemas": [s.get("name") for s in schemas]}


def alignment_report(config: Dict[str, Any],
                     schema_name: Optional[str] = None,
                     tolerance: float = 0.5,
                     version: Optional[str] = None) -> Dict[str, Any]:
    """
    Score the persisted predictions against the human consensus.

    Separate from :func:`run_judge_batch` on purpose: the alignment can be
    recomputed at a different tolerance, or after more people annotate, without
    paying for the model calls again.
    """
    from potato.ai.rollout_judge import BreakPrediction, align_with_humans
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager

    stored = load_predictions(config)
    if not stored:
        return {"error": "No judge predictions have been recorded yet. Run the "
                         "batch first.", "n_predictions": 0}
    chosen = version or sorted(stored)[-1]
    rows = stored.get(chosen) or {}

    manager = get_item_state_manager()
    user_manager = get_user_state_manager()
    if manager is None or user_manager is None:
        return {"error": "No items are loaded.", "n_predictions": 0}

    user_states = {}
    for user_id in user_manager.get_user_ids():
        state = user_manager.get_user_state(user_id)
        if state is not None:
            user_states[user_id] = state

    report: Dict[str, Any] = {"prompt_version": chosen, "tolerance": tolerance,
                              "schemas": {}}
    for schema in rollout_schemas(config):
        name = schema.get("name") or ""
        if schema_name and name != schema_name:
            continue
        predictions = [BreakPrediction.from_dict(payload)
                       for key, payload in rows.items()
                       if key.split("::")[1:2] == [name]]
        if not predictions:
            report["schemas"][name] = {
                "error": f"no predictions recorded for '{name}' at prompt "
                         f"version {chosen}"}
            continue
        raw = _gather_annotations(manager.get_instance_ids(), user_states, name)
        report["schemas"][name] = align_with_humans(
            predictions, human_consensus(schema, raw), tolerance=tolerance)
    return report


def _gather_annotations(instance_ids, user_states, schema_name):
    """
    ``{instance_id: {annotator: stored_value}}``, from one annotator upwards.

    Deliberately *not* ``dispatcher._gather_raw``, which requires two
    annotators per item. That threshold is right for inter-annotator agreement
    — one person agrees with nobody — and wrong here: the judge is being scored
    against people, so a single annotator's answer is a perfectly good thing to
    be right or wrong about, and reusing the stricter gatherer would silently
    drop every singly-annotated item from the denominator.
    """
    from potato.server_utils.iaa.dispatcher import _schema_values

    rows: Dict[str, Dict[str, Any]] = {}
    for instance_id in instance_ids:
        per_user = {}
        for user_id, state in user_states.items():
            values = _schema_values(state, instance_id, schema_name)
            if values is not None:
                per_user[user_id] = values
        if per_user:
            rows[instance_id] = per_user
    return rows
