"""
Between-subjects conditions.

A ``conditions`` block declares one or more factors. Each participant is
assigned one cell -- one level of every factor -- the first time the server
sees them, and keeps it:

.. code-block:: yaml

    conditions:
      factors:
        feedback: [none, immediate]
        font: [serif, sans]
      assignment: balanced        # balanced | random | round_robin
      balance_on: assigned        # assigned | completed
      max_per_cell: 40            # optional
      cells:                      # optional: a subset of the full factorial, with weights
        - {feedback: none, font: serif, weight: 2}

The assignment is stored on ``user_state.flow_record`` as ``conditions``
(``{factor: level}``), ``condition_cell`` (the cell's index),
``condition_ordinal`` (the participant's arrival number) and ``cell_ordinal``
(their arrival number within the cell, which picks the Latin-square row for
counterbalanced pages, so each cell walks the whole square). Page ``show_when`` rules and
question ``display_logic`` can test ``condition.<factor>``.

The assigner is owned by ``UserStateManager`` and rebuilt with it, rather than
held as a module singleton that would keep the first config it saw.
"""

from __future__ import annotations

import itertools
import logging
import random
import threading
from typing import Any, Dict, Iterable, List, Optional

from potato.server_utils.phase_flow import flow_record
from potato.server_utils.presentation_order import order_seed

logger = logging.getLogger(__name__)

ASSIGNMENT_METHODS = ("balanced", "random", "round_robin")
BALANCE_ON = ("assigned", "completed")


def _cell_key(cell: Dict[str, Any], factors: Iterable[str]) -> tuple:
    return tuple(str(cell.get(f)) for f in factors)


def build_cells(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The cells a ``conditions`` block declares, each ``{factor: level, ...}``
    with a ``weight``. The full factorial unless ``cells`` lists a subset."""
    factors = spec.get("factors") or {}
    names = list(factors)
    explicit = spec.get("cells")
    cells = []
    if explicit:
        for raw in explicit:
            cell = {f: str(raw[f]) for f in names}
            cell["weight"] = float(raw.get("weight", 1))
            cells.append(cell)
    else:
        for combo in itertools.product(*(factors[f] for f in names)):
            cell = {f: str(v) for f, v in zip(names, combo)}
            cell["weight"] = 1.0
            cells.append(cell)
    return cells


class ConditionAssigner:
    """Assigns each participant one cell of the declared design."""

    def __init__(self, config: Dict[str, Any]):
        spec = (config or {}).get("conditions") or {}
        self.factors: List[str] = list((spec.get("factors") or {}).keys())
        self.cells = build_cells(spec) if self.factors else []
        self.assignment = spec.get("assignment", "balanced")
        self.balance_on = spec.get("balance_on", "assigned")
        self.max_per_cell = spec.get("max_per_cell")
        self._counts = [0] * len(self.cells)
        self._next_ordinal = 0
        self._lock = threading.Lock()
        self._index = {_cell_key(c, self.factors): i for i, c in enumerate(self.cells)}

    @property
    def enabled(self) -> bool:
        return bool(self.cells)

    # -- bookkeeping -------------------------------------------------------

    def cell_of(self, user_state) -> Optional[int]:
        rec = flow_record(user_state)
        cell = rec.get("condition_cell")
        if isinstance(cell, int) and 0 <= cell < len(self.cells):
            return cell
        conds = rec.get("conditions")
        if isinstance(conds, dict):
            return self._index.get(_cell_key(conds, self.factors))
        return None

    def rebuild_from_users(self, user_states: Iterable[Any]) -> None:
        """Recount assignments from states loaded off disk (server restart)."""
        with self._lock:
            self._counts = [0] * len(self.cells)
            top = -1
            for us in user_states:
                cell = self.cell_of(us)
                if cell is not None:
                    self._counts[cell] += 1
                ordinal = flow_record(us).get("condition_ordinal")
                if isinstance(ordinal, int):
                    top = max(top, ordinal)
            self._next_ordinal = top + 1

    def counts(self, user_states: Optional[Iterable[Any]] = None) -> List[int]:
        """Per-cell counts used for balancing.

        ``balance_on: completed`` counts only participants who reached the end
        without being screened out, so dropouts are replaced; it needs the
        user states to look at.
        """
        if self.balance_on != "completed" or user_states is None:
            return list(self._counts)
        from potato.phase import UserPhase
        counts = [0] * len(self.cells)
        for us in user_states:
            rec = flow_record(us)
            if rec.get("screened_out"):
                continue
            try:
                done = us.get_phase() == UserPhase.DONE
            except Exception:
                done = False
            cell = self.cell_of(us)
            if done and cell is not None:
                counts[cell] += 1
        return counts

    # -- assignment --------------------------------------------------------

    def ensure(self, user_state, user_states: Optional[Iterable[Any]] = None) -> Optional[Dict[str, str]]:
        """Assign a cell if the participant has none; return their conditions.

        Idempotent. ``user_states`` is only read for ``balance_on: completed``.
        """
        if not self.enabled:
            return None
        rec = flow_record(user_state)
        if self.cell_of(user_state) is not None and isinstance(rec.get("conditions"), dict):
            return rec["conditions"]
        with self._lock:
            # Re-check under the lock: two first requests from one participant
            # can race here.
            if self.cell_of(user_state) is not None and isinstance(rec.get("conditions"), dict):
                return rec["conditions"]
            ordinal = self._next_ordinal
            self._next_ordinal += 1
            cell = self._choose(str(user_state.user_id), ordinal,
                                self.counts(list(user_states) if user_states is not None else None))
            # Position within the cell, so a Latin square walks all of its
            # rows inside every cell. Indexing the square by the global
            # ordinal confounded block order with condition: round-robin
            # assignment over two cells gave each cell one row forever.
            cell_ordinal = self._counts[cell]
            self._counts[cell] += 1
            conditions = {f: self.cells[cell][f] for f in self.factors}
            rec["conditions"] = conditions
            rec["condition_cell"] = cell
            rec["condition_ordinal"] = ordinal
            rec["cell_ordinal"] = cell_ordinal
        logger.info("Assigned %s to condition %s", user_state.user_id, conditions)
        return conditions

    def _choose(self, user_id: str, ordinal: int, counts: List[int]) -> int:
        open_cells = [i for i in range(len(self.cells))
                      if self.max_per_cell is None or counts[i] < self.max_per_cell]
        if not open_cells:
            logger.warning(
                "Every condition cell has reached max_per_cell=%s; assigning the "
                "least-filled cell. Stop recruiting or raise the cap.",
                self.max_per_cell)
            open_cells = list(range(len(self.cells)))

        weights = {i: max(self.cells[i]["weight"], 1e-9) for i in open_cells}
        if self.assignment == "random":
            rng = random.Random(order_seed(user_id, "__condition__", "random"))
            return rng.choices(open_cells, weights=[weights[i] for i in open_cells])[0]
        if self.assignment == "round_robin":
            return open_cells[ordinal % len(open_cells)]
        # balanced: the cell furthest below its weighted share. Ties go to a
        # per-participant draw so arrival order does not fix the sequence.
        load = {i: counts[i] / weights[i] for i in open_cells}
        low = min(load.values())
        tied = [i for i in open_cells if load[i] == low]
        if len(tied) == 1:
            return tied[0]
        rng = random.Random(order_seed(user_id, "__condition__", "balanced"))
        return rng.choice(tied)


def validate_conditions_config(config_data: Dict[str, Any]) -> None:
    """Refuse a malformed ``conditions`` block."""
    from potato.server_utils.config_module import ConfigValidationError
    spec = config_data.get("conditions")
    if spec is None:
        return
    if not isinstance(spec, dict):
        raise ConfigValidationError("conditions must be a mapping with a 'factors' block")
    unknown = set(spec) - {"factors", "assignment", "balance_on", "max_per_cell", "cells"}
    if unknown:
        raise ConfigValidationError(
            f"conditions has unknown key(s): {', '.join(sorted(unknown))}")
    factors = spec.get("factors")
    if not isinstance(factors, dict) or not factors:
        raise ConfigValidationError(
            "conditions.factors must map each factor name to a list of levels, "
            "e.g. {feedback: [none, immediate]}")
    for name, levels in factors.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise ConfigValidationError(
                f"conditions.factors: '{name}' must be a plain identifier "
                "(letters, digits, underscores)")
        if not isinstance(levels, list) or len(levels) < 2:
            raise ConfigValidationError(
                f"conditions.factors.{name} must list at least two levels")
        as_str = [str(v) for v in levels]
        if any(isinstance(v, (dict, list)) for v in levels) or len(set(as_str)) != len(as_str):
            raise ConfigValidationError(
                f"conditions.factors.{name} levels must be distinct scalar values")
        if any(isinstance(v, bool) for v in levels):
            raise ConfigValidationError(
                f"conditions.factors.{name} has a true/false level. YAML reads "
                "unquoted yes/no/on/off as booleans; quote the level names.")
    if spec.get("assignment", "balanced") not in ASSIGNMENT_METHODS:
        raise ConfigValidationError(
            f"conditions.assignment must be one of {', '.join(ASSIGNMENT_METHODS)}")
    if spec.get("balance_on", "assigned") not in BALANCE_ON:
        raise ConfigValidationError(
            f"conditions.balance_on must be one of {', '.join(BALANCE_ON)}")
    cap = spec.get("max_per_cell")
    if cap is not None and (not isinstance(cap, int) or isinstance(cap, bool) or cap < 1):
        raise ConfigValidationError("conditions.max_per_cell must be a positive integer")
    cells = spec.get("cells")
    if cells is not None:
        if not isinstance(cells, list) or not cells:
            raise ConfigValidationError("conditions.cells must be a non-empty list")
        seen = set()
        for i, cell in enumerate(cells):
            if not isinstance(cell, dict):
                raise ConfigValidationError(f"conditions.cells[{i}] must be a mapping")
            extra = set(cell) - set(factors) - {"weight"}
            if extra:
                raise ConfigValidationError(
                    f"conditions.cells[{i}] names unknown factor(s): {', '.join(sorted(extra))}")
            for f, levels in factors.items():
                if f not in cell:
                    raise ConfigValidationError(f"conditions.cells[{i}] is missing factor '{f}'")
                if str(cell[f]) not in [str(v) for v in levels]:
                    raise ConfigValidationError(
                        f"conditions.cells[{i}].{f} = '{cell[f]}' is not a declared level")
            weight = cell.get("weight", 1)
            if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
                raise ConfigValidationError(f"conditions.cells[{i}].weight must be a positive number")
            key = tuple(str(cell[f]) for f in factors)
            if key in seen:
                raise ConfigValidationError(f"conditions.cells[{i}] repeats an earlier cell")
            seen.add(key)


def validate_condition_references(config_data: Dict[str, Any],
                                  schemes: Optional[List[Dict[str, Any]]] = None) -> None:
    """Every ``condition.<factor>`` a question's display_logic names must be a
    declared factor. Covers the inline annotation schemes, or ``schemes``
    when given (phase-file questions, checked at boot)."""
    from potato.server_utils.config_module import ConfigValidationError
    from potato.server_utils.phase_flow import CONDITION_PREFIX
    spec = config_data.get("conditions")
    factors = set((spec.get("factors") or {}) if isinstance(spec, dict) else {})
    if schemes is None:
        schemes = list(config_data.get("annotation_schemes") or [])
    for scheme in schemes:
        if not isinstance(scheme, dict):
            continue
        logic = scheme.get("display_logic")
        if not isinstance(logic, dict):
            continue
        for cond in logic.get("show_when") or []:
            ref = str((cond or {}).get("schema", "")) if isinstance(cond, dict) else ""
            if ref.startswith(CONDITION_PREFIX) and ref[len(CONDITION_PREFIX):] not in factors:
                declared = ", ".join(sorted(factors)) or "none declared"
                raise ConfigValidationError(
                    f"Question '{scheme.get('name')}' display_logic refers to '{ref}', "
                    f"but conditions.factors has no such factor ({declared})")
            if ref.startswith(CONDITION_PREFIX):
                check_condition_value(f"Question '{scheme.get('name')}' display_logic",
                                      cond, (spec.get("factors") or {}))


def validate_group_by_condition(config_data: Dict[str, Any]) -> None:
    """``batch_assignment.group_by_condition`` names a declared factor, and the
    auto-assigned groups are named exactly after its levels."""
    from potato.server_utils.config_module import ConfigValidationError
    batch = config_data.get("batch_assignment")
    if not isinstance(batch, dict) or "group_by_condition" not in batch:
        return
    factor = batch["group_by_condition"]
    factors = ((config_data.get("conditions") or {}).get("factors") or {}) \
        if isinstance(config_data.get("conditions"), dict) else {}
    if factor not in factors:
        raise ConfigValidationError(
            f"batch_assignment.group_by_condition is '{factor}', which is not a "
            "factor in conditions.factors")
    if not batch.get("auto_assign_annotators"):
        raise ConfigValidationError(
            "batch_assignment.group_by_condition needs "
            "batch_assignment.auto_assign_annotators: true")
    names = {str(g.get("name")) for g in batch.get("groups") or []
             if isinstance(g, dict) and not g.get("annotators") and not g.get("users")}
    levels = {str(v) for v in factors[factor]}
    if names != levels:
        raise ConfigValidationError(
            f"batch_assignment.group_by_condition: the auto-assigned groups must be "
            f"named after the levels of '{factor}' ({', '.join(sorted(levels))}); "
            f"found {', '.join(sorted(names)) or 'none'}")


#: Operators whose value names one or more levels.
_LEVEL_OPERATORS = ("equals", "not_equals", "contains", "not_contains")


def check_condition_value(where: str, cond: Dict[str, Any], factors: Dict[str, Any]) -> None:
    """A rule comparing ``condition.<factor>`` with a level must name a real one.

    ``value: c`` for a factor with levels ``[a, b]`` validates, boots, and the
    page or question it gates is never shown.
    """
    from potato.server_utils.config_module import ConfigValidationError
    from potato.server_utils.phase_flow import CONDITION_PREFIX
    schema = str(cond.get("schema", ""))
    if not schema.startswith(CONDITION_PREFIX):
        return
    factor = schema[len(CONDITION_PREFIX):]
    if factor not in factors or cond.get("operator") not in _LEVEL_OPERATORS:
        return
    levels = {str(v) for v in factors[factor]}
    values = cond.get("value")
    values = values if isinstance(values, list) else [values]
    unknown = [str(v) for v in values if str(v) not in levels]
    if unknown:
        raise ConfigValidationError(
            f"{where} compares '{schema}' with {', '.join(repr(u) for u in unknown)}, "
            f"which is not a level of '{factor}' ({', '.join(sorted(levels))})")
