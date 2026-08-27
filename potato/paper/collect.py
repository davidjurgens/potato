"""Offline collection of a Potato project's annotations for Paper Mode.

Reads the task config plus every ``{output_annotation_dir}/<user>/user_state.json``
and flattens labels into records. No Flask, no singletons — safe to run against
a live or archived project directory.

On-disk label format (see ``InMemoryUserState.save``):
``instance_id_to_label_to_value`` maps instance_id to a LIST of
``[{"schema": ..., "name": ...}, value]`` pairs.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Scheme types whose values are meaningful categories for distribution/IAA tables
CATEGORICAL_TYPES = {"radio", "likert", "multiselect", "select", "bws"}


@dataclass
class LabelRecord:
    annotator: str
    instance_id: str
    schema: str
    value: str


@dataclass
class ProjectData:
    config: Dict[str, Any]
    config_path: str
    task_name: str
    schemes: List[Dict[str, Any]]           # categorical schemes only
    skipped_schemes: List[Dict[str, Any]]   # non-categorical (span, textbox, ...)
    records: List[LabelRecord] = field(default_factory=list)
    # annotator -> list of per-instance seconds (from behavioral data)
    timings: Dict[str, List[float]] = field(default_factory=dict)
    annotators: List[str] = field(default_factory=list)
    instance_ids: List[str] = field(default_factory=list)  # annotated instances
    total_items: Optional[int] = None       # dataset size, if data files readable
    # username -> "passed" | "failed" | "in_progress", from each saved
    # training_state. This is the exclusion record a reviewer asks for: how
    # many people were screened out, and by what.
    training_outcomes: Dict[str, str] = field(default_factory=dict)


def _scheme_type(scheme: Dict[str, Any]) -> str:
    return scheme.get("annotation_type", "")


def _flatten_labels(payload: Any) -> List[Any]:
    """Yield [key_dict, value] pairs from either the list or legacy dict form."""
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, list) and len(p) == 2]
    if isinstance(payload, dict):
        return [[k, v] for k, v in payload.items()]
    return []


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "off", "none")
    return bool(value)


def _is_bool_flag(value: Any) -> bool:
    """True when the stored value is a boolean selection flag, not a label.

    Radio/likert/select checkboxes persist as name=<label>, value="true"; a
    likert *scale value* like "3" is not a flag and is used as the label itself.
    """
    if isinstance(value, bool):
        return True
    return isinstance(value, str) and value.strip().lower() in ("true", "false")


def _extract_records(username: str, state: Dict[str, Any],
                     scheme_types: Dict[str, str]) -> List[LabelRecord]:
    records = []
    labels_by_instance = state.get("instance_id_to_label_to_value", {}) or {}
    for instance_id, payload in labels_by_instance.items():
        for pair in _flatten_labels(payload):
            key, value = pair
            if not isinstance(key, dict):
                continue
            schema = key.get("schema")
            name = key.get("name")
            if not schema or schema not in scheme_types:
                continue
            stype = scheme_types[schema]
            if stype == "multiselect":
                # One record per *selected* checkbox; the label is the name.
                if _truthy(value):
                    records.append(LabelRecord(username, str(instance_id),
                                               schema, str(name)))
            else:
                if value is None or value == "":
                    continue
                # Single-choice schemes (radio/likert/select) collected through
                # the UI store the *selected option in `name`* with value "true"
                # (a boolean flag). Older/synthetic data stores the label as the
                # value directly. Use the option name when the value is just a
                # flag, so real UI data yields the chosen label rather than
                # collapsing every annotation to "true".
                if _is_bool_flag(value):
                    if not _truthy(value):
                        continue
                    label = str(name) if name not in (None, "") else str(value)
                else:
                    label = str(value)
                records.append(LabelRecord(username, str(instance_id),
                                           schema, label))
    return records


def _extract_timings(state: Dict[str, Any]) -> List[float]:
    """Per-instance active seconds from behavioral data, when present."""
    seconds = []
    behavioral = state.get("instance_id_to_behavioral_data", {}) or {}
    for data in behavioral.values():
        if not isinstance(data, dict):
            continue
        ms = data.get("total_time_ms") or 0
        if ms and ms > 0:
            seconds.append(ms / 1000.0)
            continue
        # Fall back to the interaction timestamp span
        interactions = data.get("interactions") or []
        stamps = [i.get("timestamp") for i in interactions
                  if isinstance(i, dict) and isinstance(i.get("timestamp"), (int, float))]
        if len(stamps) >= 2:
            span = max(stamps) - min(stamps)
            if 0 < span < 3600:  # ignore pathological gaps (left tab open)
                seconds.append(span)
    return seconds


def _training_outcome(state: Dict[str, Any]) -> Optional[str]:
    """
    Whether this annotator passed, failed, or is still in the training gate.

    A dataset report is asked to say how many annotators were screened out and
    on what basis, and the saved training state is the only place that is
    recorded. Returns None when training was not used, so a project without a
    gate does not report a fabricated exclusion count of zero as if it had
    screened people and excluded none.
    """
    training = state.get("training_state")
    if not isinstance(training, dict) or not training:
        return None
    # An untouched TrainingState serialises with no questions and no verdict,
    # which means the user never reached the gate rather than that they are
    # partway through it.
    if not training.get("completed_questions") and not (
            training.get("passed") or training.get("failed")):
        return None
    if training.get("failed"):
        return "failed"
    if training.get("passed"):
        return "passed"
    return "in_progress"


def _count_data_items(config: Dict[str, Any], base_dir: str) -> Optional[int]:
    """Count items across the configured data files (best effort)."""
    total = 0
    found = False
    for rel in config.get("data_files", []) or []:
        path = rel if os.path.isabs(rel) else os.path.join(base_dir, rel)
        if not os.path.exists(path):
            continue
        found = True
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                continue
            if content.startswith("["):
                total += len(json.loads(content))
            elif path.endswith((".csv", ".tsv")):
                total += max(0, len(content.splitlines()) - 1)
            else:  # jsonl
                total += sum(1 for line in content.splitlines() if line.strip())
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not count items in %s", path)
    return total if found else None


def collect_project(config_path: str) -> ProjectData:
    """Load a project's config and every annotator's saved state."""
    config_path = os.path.abspath(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    base_dir = os.path.dirname(config_path)

    all_schemes = config.get("annotation_schemes", []) or []
    schemes = [s for s in all_schemes if _scheme_type(s) in CATEGORICAL_TYPES]
    skipped = [s for s in all_schemes if _scheme_type(s) not in CATEGORICAL_TYPES]
    scheme_types = {s.get("name"): _scheme_type(s) for s in schemes}

    output_dir = config.get("output_annotation_dir", "annotation_output")
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(base_dir, output_dir)

    project = ProjectData(
        config=config,
        config_path=config_path,
        task_name=config.get("annotation_task_name", "Annotation Task"),
        schemes=schemes,
        skipped_schemes=skipped,
        total_items=_count_data_items(config, base_dir),
    )

    if not os.path.isdir(output_dir):
        logger.warning("Output directory %s does not exist; no annotations found",
                       output_dir)
        return project

    for entry in sorted(os.listdir(output_dir)):
        state_path = os.path.join(output_dir, entry, "user_state.json")
        if not os.path.isfile(state_path):
            continue
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.warning("Skipping unreadable state file %s", state_path)
            continue
        username = state.get("user_id", entry)
        records = _extract_records(username, state, scheme_types)
        if records:
            project.records.extend(records)
            project.annotators.append(username)
        timings = _extract_timings(state)
        if timings:
            project.timings[username] = timings
        outcome = _training_outcome(state)
        if outcome:
            project.training_outcomes[username] = outcome

    project.instance_ids = sorted({r.instance_id for r in project.records})
    return project
