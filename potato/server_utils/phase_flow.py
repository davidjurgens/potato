"""
Experiment flow: which phase pages a participant sees, and in what order.

Three per-participant decisions live here, all made on the server when the
participant moves between pages:

- ``show_when`` on a phase page skips that page unless the condition holds.
  The grammar is the one ``display_logic`` uses for single questions, so a
  page can be gated on any earlier answer, from any phase, or on the
  participant's assigned condition (``condition.<factor>``).
- ``exit_when`` on a phase page ends the study for the participant when the
  condition holds as they leave the page (a screener).
- ``phases.counterbalance`` permutes groups of same-type pages per
  participant, at random or by a balanced Latin square row.

Everything is recorded on ``user_state.flow_record`` so the export can show
what each participant was actually shown. The functions take the config and a
user state and import nothing from Flask, so they can be tested directly.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from potato.server_utils.display_logic import (
    DisplayLogicEvaluator,
    DisplayLogicRule,
    flatten_phase_annotations,
)
from potato.server_utils.presentation_order import order_seed, permutation

logger = logging.getLogger(__name__)

#: Prefix that addresses an assigned between-subjects condition in a rule,
#: e.g. ``{schema: condition.feedback, operator: equals, value: immediate}``.
CONDITION_PREFIX = "condition."

#: Keys inside ``phases`` that are not phase definitions.
RESERVED_PHASE_KEYS = frozenset({"order", "counterbalance"})

COUNTERBALANCE_METHODS = ("random", "latin_square")


# --------------------------------------------------------------------------
# Config access
# --------------------------------------------------------------------------

def phases_dict(config: dict) -> Dict[str, dict]:
    """``{page_name: entry}`` for both the dict and list ``phases`` formats."""
    phases = (config or {}).get("phases")
    if isinstance(phases, list):
        return {p["name"]: p for p in phases if isinstance(p, dict) and p.get("name")}
    if isinstance(phases, dict):
        return {k: v for k, v in phases.items()
                if k not in RESERVED_PHASE_KEYS and isinstance(v, dict)}
    return {}


def phase_entry(config: dict, page_name: Optional[str]) -> Optional[dict]:
    if not page_name:
        return None
    return phases_dict(config).get(page_name)


def counterbalance_groups(config: dict) -> List[dict]:
    phases = (config or {}).get("phases")
    if not isinstance(phases, dict):
        return []
    groups = phases.get("counterbalance") or []
    return [g for g in groups if isinstance(g, dict) and g.get("pages")]


def has_flow_rules(config: dict) -> bool:
    """True when any page uses show_when/exit_when or pages are counterbalanced."""
    if counterbalance_groups(config):
        return True
    return any(("show_when" in e or "exit_when" in e or "randomize_questions" in e)
               for e in phases_dict(config).values())


# --------------------------------------------------------------------------
# Flow record
# --------------------------------------------------------------------------

def flow_record(user_state) -> Dict[str, Any]:
    """The participant's flow record, created on first use.

    A MySQL-backed state, or one built by an older test helper, may not have
    the attribute; it gets one rather than raising.
    """
    rec = getattr(user_state, "flow_record", None)
    if not isinstance(rec, dict):
        rec = {}
        try:
            user_state.flow_record = rec
        except AttributeError:
            pass
    return rec


def conditions_for(user_state) -> Dict[str, str]:
    return dict(flow_record(user_state).get("conditions") or {})


# --------------------------------------------------------------------------
# Answers
# --------------------------------------------------------------------------

def _schema_types(config: dict) -> Dict[str, str]:
    types = {}
    for scheme in list(config.get("annotation_schemes") or []) + \
            list(config.get("_surveyflow_schemes") or []):
        if isinstance(scheme, dict) and scheme.get("name"):
            types[scheme["name"]] = scheme.get("annotation_type")
    return types


def collect_flow_answers(config: dict, user_state) -> Dict[str, Any]:
    """Every phase-page answer the participant has given, flattened to
    ``{schema: value}``, plus ``condition.<factor>`` for each assigned factor.

    Answers from all phases are merged; a page can depend on a question asked
    in any earlier phase. Conditions are layered underneath answers, so a
    question that happens to be named ``condition.x`` still wins.
    """
    flat: Dict[str, Any] = {
        CONDITION_PREFIX + factor: level
        for factor, level in conditions_for(user_state).items()
    }
    types = _schema_types(config)
    store = getattr(user_state, "phase_to_page_to_label_to_value", None) or {}
    for _phase, pages in store.items():
        try:
            flat.update(flatten_phase_annotations(pages, schema_types=types))
        except Exception as e:  # malformed legacy data must not block navigation
            logger.warning("Could not flatten phase answers for %s: %s",
                           getattr(user_state, "user_id", "?"), e)
    return flat


def _rule_from(spec: dict) -> DisplayLogicRule:
    return DisplayLogicRule.from_dict({
        "show_when": spec.get("show_when") or [],
        "logic": spec.get("logic", "all"),
    })


def _rule_holds(spec: dict, answers: Dict[str, Any], where: str) -> Optional[bool]:
    try:
        return DisplayLogicEvaluator.evaluate_rule(_rule_from(spec), answers)
    except Exception as e:
        # Boot validation rejects malformed rules; this is a backstop.
        logger.error("Could not evaluate flow rule on %s: %s", where, e)
        return None


# --------------------------------------------------------------------------
# show_when / exit_when
# --------------------------------------------------------------------------

def page_visible(config: dict, user_state, page_name: Optional[str],
                 answers: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the participant should see this phase page.

    Pages without ``show_when`` are always visible. A rule that cannot be
    evaluated shows the page: hiding a consent form by accident is worse than
    showing a follow-up page by accident.
    """
    entry = phase_entry(config, page_name)
    if not entry or not entry.get("show_when"):
        return True
    if answers is None:
        answers = collect_flow_answers(config, user_state)
    holds = _rule_holds(entry, answers, f"page '{page_name}'")
    return True if holds is None else holds


def should_exit(config: dict, user_state, page_name: Optional[str],
                answers: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The page's ``exit_when`` spec when it matches, else None."""
    entry = phase_entry(config, page_name)
    spec = (entry or {}).get("exit_when")
    if not isinstance(spec, dict) or not spec.get("show_when"):
        return None
    if answers is None:
        answers = collect_flow_answers(config, user_state)
    if _rule_holds(spec, answers, f"exit_when on '{page_name}'"):
        return spec
    return None


def record_skip(user_state, phase, page: str) -> None:
    rec = flow_record(user_state)
    skipped = rec.setdefault("skipped_pages", [])
    if any(s.get("page") == page for s in skipped):
        return
    skipped.append({"phase": _phase_name(phase), "page": page, "at": time.time()})


def record_screen_out(user_state, page: str, spec: Dict[str, Any]) -> None:
    flow_record(user_state)["screened_out"] = {
        "page": page,
        "at": time.time(),
        "message": spec.get("message"),
    }


def screened_out(user_state) -> Optional[Dict[str, Any]]:
    return flow_record(user_state).get("screened_out")


# --------------------------------------------------------------------------
# Counterbalanced page order
# --------------------------------------------------------------------------

def williams_rows(n: int) -> List[List[int]]:
    """Rows of a balanced (Williams) Latin square over ``range(n)``.

    Each item appears once in each position across the rows, and for even
    ``n`` each item immediately follows every other item exactly once. Odd
    ``n`` needs the mirrored rows as well, so it returns ``2n`` rows.
    """
    if n <= 0:
        return []
    if n == 1:
        return [[0]]
    # Standard construction: 0, 1, n-1, 2, n-2, ... shifted per row.
    first =[0] + [((i + 1) // 2) if i % 2 == 1 else (n - i // 2) for i in range(1, n)]
    rows = [[(x + r) % n for x in first] for r in range(n)]
    if n % 2 == 1:
        rows += [list(reversed(row)) for row in rows]
    return rows


def _group_order(user_state, group: dict) -> List[str]:
    pages = [str(p) for p in group.get("pages") or []]
    method = group.get("method", "random")
    if method == "latin_square":
        rows = williams_rows(len(pages))
        rec = flow_record(user_state)
        # Within-cell arrival number when conditions are configured (so the
        # square is balanced inside each cell), else the study-wide arrival
        # number. Both are assigned by UserStateManager before this runs.
        ordinal = rec.get("cell_ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            ordinal = rec.get("latin_ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            # A state from before arrival numbers existed: a stable row from
            # the user id, so its order still survives a restart.
            ordinal = order_seed(str(user_state.user_id), "__latin_square__",
                                 ",".join(pages))
        row = rows[ordinal % len(rows)]
        return [pages[i] for i in row]
    seed = order_seed(str(user_state.user_id), "__page_order__", ",".join(pages))
    return [pages[i] for i in permutation(len(pages), seed)]


def uses_latin_square(config: dict) -> bool:
    return any(g.get("method") == "latin_square" for g in counterbalance_groups(config))


def apply_counterbalance(config: dict, user_state, phase,
                         pages: Tuple[str, ...]) -> Tuple[str, ...]:
    """Permute counterbalanced groups within one phase's page list.

    A group's pages keep the slots they occupy in the configured order; only
    which page fills which slot changes. The first order a participant is
    given is recorded and reused, so editing the config mid-study does not
    reshuffle someone halfway through.
    """
    groups = counterbalance_groups(config)
    if not groups or not pages:
        return pages
    result = list(pages)
    rec = flow_record(user_state)
    recorded = rec.setdefault("page_orders", {})
    changed = False
    for idx, group in enumerate(groups):
        members = [p for p in (str(x) for x in group.get("pages") or []) if p in result]
        if len(members) < 2:
            continue
        key = f"group_{idx}"
        order = recorded.get(key)
        if not (isinstance(order, list) and sorted(order) == sorted(members)):
            order = [p for p in _group_order(user_state, group) if p in members]
            recorded[key] = order
            changed = True
        slots = [i for i, p in enumerate(result) if p in members]
        for slot, page in zip(slots, order):
            result[slot] = page
    if changed:
        logger.debug("Page order for %s in %s: %s", user_state.user_id,
                     _phase_name(phase), result)
    return tuple(result)


def _phase_name(phase) -> str:
    return phase.value if hasattr(phase, "value") else str(phase)
