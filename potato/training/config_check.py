"""Checks on ``model_training`` settings and on a run before it starts.

Each of these used to pass ``validate --strict`` and boot, and fail later:
at the next automatic retrain, when the run's bundle was built, in a log
line at boot, or as prelabels that never appeared. The same checks serve
config validation (all problems at once) and ``start_run`` (a refusal before
a bundle is built).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Sequence

#: The split names the trainers read. Anything else is trained on as if it
#: were nothing: no held-out score, no predictions.
SPLIT_NAMES = ("train", "val", "test")

AUTO_RETRAIN_KEYS = ("enabled", "trainer", "schemas", "min_interval_s",
                     "update_frequency", "params", "backend", "accept_licence")
WRITEBACK_KEYS = ("schemas", "min_confidence", "field", "include_unlabeled")

#: Spellings people reach for, and the key they meant.
_NEAR = {"accept_license": "accept_licence", "acceptLicence": "accept_licence",
         "schema": "schemas", "minimum_confidence": "min_confidence",
         "min_conf": "min_confidence"}


def _schemes(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {s["name"]: s for s in config.get("annotation_schemes", []) or []
            if isinstance(s, dict) and s.get("name")}


def run_problems(config: Dict[str, Any], trainer: str,
                 schema_names: Sequence[str]) -> List[str]:
    """Why a run of *trainer* on *schema_names* cannot start, checked
    before the bundle is built: an unknown trainer or scheme, or a scheme
    of a kind the trainer does not handle."""
    from potato.training.registry import (get_trainer_class, trainer_names,
                                          trainers_for_schema)

    if trainer not in trainer_names():
        return ["Unknown trainer %r. Known trainers: %s"
                % (trainer, ", ".join(trainer_names()))]
    try:
        problem = get_trainer_class(trainer).config_problem(config)
    except Exception:  # noqa: BLE001 - an unimportable trainer fails later
        problem = None
    if problem:
        return ["%s cannot run in this project: %s." % (trainer, problem)]
    schemes = _schemes(config)
    problems = []
    for name in schema_names:
        scheme = schemes.get(name)
        if scheme is None:
            problems.append("No annotation scheme named %r. Schemes: %s"
                            % (name, ", ".join(sorted(schemes)) or "(none)"))
            continue
        fits = [t.name for t in trainers_for_schema(scheme)]
        if trainer not in fits:
            problems.append(
                "%s does not train %r (%s). Trainers for it: %s"
                % (trainer, name, scheme.get("annotation_type"),
                   ", ".join(fits) or "none"))
    return problems


def _unknown_keys(block: Dict[str, Any], known: Sequence[str],
                  where: str) -> List[str]:
    problems = []
    for key in block:
        if key in known:
            continue
        hint = _NEAR.get(key)
        problems.append("%s.%s is not a setting%s. Settings: %s"
                        % (where, key, " (did you mean %s?)" % hint
                           if hint else "", ", ".join(known)))
    return problems


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _calibration_problems(config: Dict[str, Any]) -> List[str]:
    """A decision model's ``calibration`` file that is not there: every
    answer from that model would fail."""
    task_dir = config.get("task_dir") or "."
    found = []
    engine = config.get("labeling_engine") or {}
    for raw in engine.get("sources") or []:
        if isinstance(raw, dict):
            path = (raw.get("options") or {}).get("calibration")
            if path:
                found.append(("labeling_engine source %r options.calibration"
                              % raw.get("id"), path))
    solo = config.get("solo_mode") or {}
    for n, model in enumerate(solo.get("labeling_models") or []):
        if isinstance(model, dict) and model.get("calibration"):
            found.append(("solo_mode.labeling_models[%d].calibration" % n,
                          model["calibration"]))
    problems = []
    for where, path in found:
        full = path if os.path.isabs(str(path)) else os.path.join(task_dir, str(path))
        if not os.path.isfile(full):
            problems.append("%s: no file at %s. It is the calibration.json of "
                            "a decision-calibrate run." % (where, path))
    return problems


def training_config_problems(config: Dict[str, Any]) -> List[str]:
    """Every problem with ``model_training`` (and decision-model calibration
    files), as messages."""
    problems = _calibration_problems(config)
    training = config.get("model_training")
    if not isinstance(training, dict):
        return problems
    where = "model_training"
    schemes = _schemes(config)

    splits = training.get("splits")
    if splits is not None:
        if not isinstance(splits, dict) or not splits:
            problems.append("%s.splits must map split names to fractions" % where)
        else:
            odd = [k for k in splits if k not in SPLIT_NAMES]
            if odd:
                problems.append("%s.splits: %s %s not a split the trainers use; "
                                "use train, val and test"
                                % (where, ", ".join(map(repr, odd)),
                                   "is" if len(odd) == 1 else "are"))
            if not all(_number(v) and v >= 0 for v in splits.values()) \
                    or not sum(v for v in splits.values() if _number(v)):
                problems.append("%s.splits fractions must be numbers >= 0 with "
                                "a positive sum" % where)
            elif "train" not in splits:
                problems.append("%s.splits has no train split" % where)

    writeback = training.get("writeback")
    if isinstance(writeback, dict):
        problems.extend(_unknown_keys(writeback, WRITEBACK_KEYS,
                                      where + ".writeback"))
        for name in writeback.get("schemas") or []:
            if name not in schemes:
                problems.append("%s.writeback.schemas names %r, which is not an "
                                "annotation scheme" % (where, name))
        floor = writeback.get("min_confidence")
        if floor is not None and not (_number(floor) and 0 <= floor <= 1):
            problems.append("%s.writeback.min_confidence must be a number "
                            "from 0 to 1, not %r" % (where, floor))
        pre = config.get("pre_annotation") or {}
        field = writeback.get("field") or "predictions"
        if writeback.get("schemas") and isinstance(pre, dict) \
                and pre.get("enabled") and (pre.get("field") or "predictions") != field:
            problems.append(
                "pre_annotation.field is %r but model_training.writeback "
                "writes prelabels to %r; an enabled pre_annotation block "
                "decides which field the page reads, so no training prelabel "
                "would show. Make the two the same."
                % (pre.get("field") or "predictions", field))

    auto = training.get("auto_retrain")
    if isinstance(auto, dict):
        problems.extend(_auto_retrain_problems(config, auto, where + ".auto_retrain"))
    return problems


def _auto_retrain_problems(config: Dict[str, Any], auto: Dict[str, Any],
                           where: str) -> List[str]:
    from potato.training.backends import load_backends
    from potato.training.registry import get_trainer_class, resolve_params

    problems = _unknown_keys(auto, AUTO_RETRAIN_KEYS, where)
    for key in ("min_interval_s", "update_frequency"):
        if key in auto and not (_number(auto[key]) and auto[key] >= 0):
            problems.append("%s.%s must be a number >= 0" % (where, key))
    for key in ("enabled", "accept_licence"):
        if key in auto and not isinstance(auto[key], bool):
            problems.append("%s.%s must be true or false, not %r"
                            % (where, key, auto[key]))
    if not auto.get("enabled"):
        return problems
    trainer = auto.get("trainer")
    schemas = auto.get("schemas") or []
    if not trainer or not schemas:
        problems.append("%s needs a trainer and schemas" % where)
        return problems
    found = run_problems(config, trainer, schemas)
    problems.extend("%s: %s" % (where, p) for p in found)
    if found:
        return problems
    try:
        resolve_params(config, trainer, auto.get("params") or {})
    except ValueError as exc:
        problems.append("%s.params: %s" % (where, exc))
    backends = load_backends(config)
    backend = auto.get("backend")
    if backend and backend not in backends:
        problems.append("%s.backend %r is not a backend under "
                        "model_training.backends" % (where, backend))
    else:
        from potato.training.backends import default_backend_name
        chosen = backends.get(backend or default_backend_name(config))
        try:
            local_only = getattr(get_trainer_class(trainer), "local_only", False)
        except Exception:  # noqa: BLE001
            local_only = False
        if local_only and chosen is not None and chosen.type != "local":
            problems.append("%s: %s runs only on the local backend, and the "
                            "backend is %r" % (where, trainer, chosen.name))
    # A licence not yet accepted is not a config error: the documented
    # behaviour is a skipped run with the reason in skip_reason.
    return problems
