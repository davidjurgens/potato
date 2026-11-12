"""
Per-participant question order on survey pages (``randomize_questions``).

.. code-block:: yaml

    phases:
      big5:
        type: poststudy
        instrument: tipi
        randomize_questions: true          # or {pin_first: [...], pin_last: [...]}

The page is generated once at boot, so the reordering happens on the rendered
page: each question's form, together with any wrapper around it (the
display_logic container), is one unit, and the units trade places inside the
element that holds them all. Anything else in that element (headings,
instructions) keeps its slot. The order is seeded on (participant, page) and
recorded on ``flow_record["question_orders"]`` the first time it is shown, so
a reload or a return visit shows the same order.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from potato.server_utils.phase_flow import flow_record, phase_entry
from potato.server_utils.presentation_order import order_seed, permutation

logger = logging.getLogger(__name__)


def question_order_spec(config: dict, page: Optional[str]) -> Optional[Dict[str, List[str]]]:
    """``{pin_first, pin_last}`` when the page randomizes its questions, else None."""
    entry = phase_entry(config, page)
    spec = (entry or {}).get("randomize_questions")
    if not spec:
        return None
    if spec is True:
        return {"pin_first": [], "pin_last": []}
    if isinstance(spec, dict):
        return {"pin_first": [str(x) for x in spec.get("pin_first") or []],
                "pin_last": [str(x) for x in spec.get("pin_last") or []]}
    return None


def _forms(soup) -> list:
    return [f for f in soup.find_all("form", attrs={"data-schema-name": True})
            if "annotation-form" in (f.get("class") or [])]


def _lowest_common_parent(nodes):
    chains = []
    for node in nodes:
        chain = [p for p in node.parents]
        chains.append(chain)
    first = chains[0]
    for candidate in first:
        if all(any(candidate is p for p in chain) for chain in chains[1:]):
            return candidate
    return None


def _unit_under(node, container):
    """The ancestor of ``node`` (or ``node``) that is a direct child of ``container``."""
    cur = node
    while cur is not None and cur.parent is not container:
        cur = cur.parent
    return cur


def planned_order(user_id: str, page: str, names: List[str],
                  spec: Dict[str, List[str]]) -> List[str]:
    first = [n for n in spec["pin_first"] if n in names]
    last = [n for n in spec["pin_last"] if n in names and n not in first]
    middle = [n for n in names if n not in first and n not in last]
    perm = permutation(len(middle), order_seed(str(user_id), "__question_order__", page))
    return first + [middle[i] for i in perm] + last


def apply_question_order(config: dict, user_state, page: Optional[str], soup):
    """Reorder the page's questions in ``soup`` for this participant.

    Returns ``(order, newly_recorded)``, or ``(None, False)`` when the page
    does not randomize or its markup cannot be reordered safely.
    """
    spec = question_order_spec(config, page)
    if spec is None:
        return None, False
    layout = (phase_entry(config, page) or {}).get("layout")
    if isinstance(layout, dict) and layout.get("groups"):
        logger.warning("Page '%s' uses layout.groups, which places its questions; "
                       "randomize_questions is ignored", page)
        return None, False

    forms = _forms(soup)
    if len(forms) < 2:
        return None, False
    container = _lowest_common_parent(forms)
    if container is None:
        return None, False
    units = {}
    for form in forms:
        unit = _unit_under(form, container)
        name = form.get("data-schema-name")
        if unit is None or any(unit is u for u in units.values()):
            # Two questions share one wrapper: they cannot be separated.
            logger.warning("Questions on page '%s' share a wrapper; "
                           "randomize_questions is ignored", page)
            return None, False
        units[name] = unit
    names = list(units)

    rec = flow_record(user_state)
    recorded = rec.setdefault("question_orders", {})
    order = recorded.get(page)
    newly = False
    if not (isinstance(order, list) and sorted(order) == sorted(names)):
        order = planned_order(user_state.user_id, page, names, spec)
        recorded[page] = order
        newly = True

    # Fill the units' existing slots in the new order. Each slot is marked
    # with a placeholder first so moving one unit cannot shift another's slot.
    placeholders = []
    for name in names:
        marker = soup.new_tag("span")
        units[name].replace_with(marker)
        placeholders.append(marker)
    for marker, name in zip(placeholders, order):
        marker.replace_with(units[name])
    return order, newly
