"""
Which order the options were shown in, and how that order is chosen.

Potato showed every annotator the same options in the same order on every
item, and never recorded that it had. Both halves are problems, and the second
one is the worse of the two.

**Why a fixed order is a validity defect, not a preference.** Judges -- human
and model alike -- favour the first option offered. When every annotator shares
that pull, the bias does not cancel: it *inflates* agreement while biasing the
estimate, so the reliability figure comes out confidently wrong. That is worse
for Potato than for a pure collection tool, because telling researchers whether
their annotations are reliable is the claim the whole project rests on.

**Why recording matters more than randomising.** Randomisation only helps data
collected after it is switched on. Recording the order means a study that ran
without it -- or one whose data was pre-shuffled by hand somewhere upstream --
can still be corrected afterwards, because the analyst can condition on what
each annotator actually saw. So the order is written down for every ordered
scheme, whether or not randomisation is enabled.

**Why the seed is derived, not stored.** An annotator who reloads a page must
see the same order; one who sees a different arrangement each time is being
asked a different question each time. Deriving the seed from
``(user_id, instance_id, scheme_name)`` gives that stability for free, with no
extra state to keep in sync -- the same reasoning behind Potato's hash-based
deterministic span colours.

The hash is ``blake2b``, deliberately not Python's builtin ``hash()``. String
hashing is salted per process unless ``PYTHONHASHSEED`` is pinned, so a builtin
hash re-orders every option set on every server restart -- which is exactly the
"different question each time" this is supposed to prevent.
"""

from __future__ import annotations

import hashlib
import logging
import random
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Schema types whose option order can bias the answer, and which therefore
#: accept ``randomize_order``.
ORDER_SENSITIVE_TYPES = frozenset({
    # Comparative judgements. First-position preference is strongest and best
    # documented here -- "which of these two is better" is exactly the
    # question a judge answers by picking whatever came first.
    "pairwise", "bws", "ranking", "rollout_evaluation", "trajectory_eval",
    "conjoint",
    # Categorical option lists. The pull is weaker but the exposure is the
    # whole study, since these are the schemes most projects are built from.
    "radio", "multiselect", "hierarchical_multiselect", "select", "multirate",
})

#: The subset of :data:`ORDER_SENSITIVE_TYPES` whose order Potato can actually
#: change today. The rest still get their order RECORDED -- knowing what was
#: shown is what makes a study correctable afterwards -- but asking to shuffle
#: them would be a promise the renderer does not keep, so it warns instead.
#:
#: ``radio``/``multiselect``/``select``/``multirate`` are reordered in the
#: rendered markup by ``flask_server.randomize_options``. ``pairwise`` is
#: different: its two candidates come from the item's own data and are laid out
#: by the client, so it is reordered by permuting the list handed to the page.
RANDOMIZABLE_TYPES = frozenset({
    "radio", "multiselect", "select", "multirate", "pairwise",
})

#: Comparative schemes whose options are the item's own data rather than the
#: scheme's ``labels``. Their recorded order is a list of SOURCE INDICES -- the
#: candidates differ per item, so the position each one came from is the only
#: thing an analyst can condition on.
DATA_DRIVEN_TYPES = frozenset({"pairwise"})

#: The field name on BehavioralData, and the key the exporters read.
#: Recording is done by ``UserState.record_presentation_order`` rather than
#: here: ``update_annotation_state`` replaces the behavioural record wholesale
#: on every save, so an order written onto it at render time would not survive
#: the first autosave.
ORDER_FIELD = "presentation_order"


def order_seed(user_id: str, instance_id: str, scheme_name: str) -> int:
    """
    A stable 64-bit seed for one (annotator, item, scheme).

    Stable across processes and restarts, unlike ``hash()``. Including all
    three parts is what makes the bias cancel: seeding on the annotator alone
    gives one person the same arrangement on every item, so their
    first-position preference lands on the same label every time and is
    perfectly correlated across the study rather than averaged out.
    """
    key = f"{user_id}\x1f{instance_id}\x1f{scheme_name}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")


def permutation(n: int, seed: int) -> List[int]:
    """
    A deterministic permutation of ``range(n)``.

    Uses a private ``random.Random`` rather than the module-level functions.
    ``random.seed()`` reaches into global state shared by every other caller in
    the process, so seeding it here to lay out one radio group would silently
    reset the stream that task assignment or quality-control sampling was
    drawing from.
    """
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return order


def label_names(scheme: Dict[str, Any]) -> List[str]:
    """The scheme's option names in configured order, whatever shape they are in."""
    names = []
    for label in scheme.get("labels") or []:
        if isinstance(label, dict):
            name = label.get("name")
            if name is not None:
                names.append(str(name))
        else:
            names.append(str(label))
    return names


def is_order_sensitive(scheme: Dict[str, Any]) -> bool:
    return (scheme.get("annotation_type") or "") in ORDER_SENSITIVE_TYPES


def wants_randomization(scheme: Dict[str, Any]) -> bool:
    """
    Whether this scheme's options should be shuffled.

    ``option_randomization`` is the older key and stays authoritative where it
    is set, so existing configs keep working unchanged; ``randomize_order`` is
    the name used across the comparative schemes, where "options" is not what
    is being reordered.
    """
    asked = bool(scheme.get("randomize_order")
                 or scheme.get("option_randomization"))
    if not asked:
        return False
    atype = scheme.get("annotation_type") or ""
    if atype not in RANDOMIZABLE_TYPES:
        logger.warning(
            "Scheme '%s' asks for randomize_order, but %s options cannot be "
            "reordered yet -- the shown order is still recorded, so the data "
            "stays correctable, but it is NOT randomized.",
            scheme.get("name"), atype)
        return False
    return True


def item_order(scheme: Dict[str, Any], item_data: Dict[str, Any], user_id: str,
               instance_id: str) -> Optional[List[int]]:
    """
    Source indices, in shown order, for a scheme whose options come from data.

    ``pairwise`` compares two blobs pulled out of the item under ``items_key``,
    and the client lays them out in the order it receives them -- so the way to
    swap them is to permute that list before it reaches the page, and the way
    to record what happened is to say where each shown position came from.

    Returns None when the scheme is not data-driven, is not randomized, or the
    item has fewer than two candidates.
    """
    if (scheme.get("annotation_type") or "") not in DATA_DRIVEN_TYPES:
        return None
    if not wants_randomization(scheme):
        return None
    items = (item_data or {}).get(scheme.get("items_key", "text"))
    if not isinstance(items, list) or len(items) < 2:
        return None
    seed = order_seed(user_id, instance_id, scheme.get("name") or "")
    return permutation(len(items), seed)


def presentation_order(scheme: Dict[str, Any], user_id: str,
                       instance_id: str) -> Optional[List[str]]:
    """
    The option names in the order this annotator will see them.

    Returns None for a scheme with no ordered option list -- a textbox has no
    order to record, and writing an empty list for it would put a meaningless
    key on every item.

    The configured order is returned unchanged when randomisation is off. That
    is the point: the record says what was shown, and "shown as configured" is
    a fact worth having.
    """
    if not is_order_sensitive(scheme):
        return None
    if (scheme.get("annotation_type") or "") in DATA_DRIVEN_TYPES:
        # Its record is a list of source indices, written by `item_order`.
        # Two meanings under one scheme name would make the record
        # uninterpretable without knowing the config that produced it.
        return None
    names = label_names(scheme)
    if len(names) < 2:
        # One option cannot be presented in a biased order.
        return None
    if not wants_randomization(scheme):
        return names
    seed = order_seed(user_id, instance_id, scheme.get("name") or "")
    return [names[i] for i in permutation(len(names), seed)]


def orders_for_item(schemes: Iterable[Dict[str, Any]], user_id: str,
                    instance_id: str) -> Dict[str, List[str]]:
    """``{scheme_name: shown order}`` for every ordered scheme on one item."""
    orders: Dict[str, List[str]] = {}
    for scheme in schemes or ():
        name = scheme.get("name")
        if not name:
            continue
        order = presentation_order(scheme, user_id, instance_id)
        if order:
            orders[str(name)] = order
    return orders


def record(user_state, instance_id: str, orders: Dict[str, Any]) -> Dict[str, Any]:
    """
    Record the shown order, and return whatever is on file for this item.

    Defensive on purpose. The presentation order is diagnostic metadata: it
    makes a study correctable after the fact, but nobody can annotate anything
    if failing to write it takes down the page. A user-state object without the
    method -- a stub in a test, or a backend that predates the field -- logs and
    carries on.

    Returns the recorded orders, which may differ from ``orders``: an item
    rendered before is answered against the order it was FIRST shown in, not
    the one we would derive now.
    """
    if not orders:
        return {}
    recorder = getattr(user_state, "record_presentation_order", None)
    getter = getattr(user_state, "get_presentation_order", None)
    if recorder is None or getter is None:
        logger.debug("%s cannot record presentation order; skipping",
                     type(user_state).__name__)
        return dict(orders)
    try:
        recorder(instance_id, orders)
        return getter(instance_id)
    except Exception:
        logger.warning("Could not record the presentation order for %s",
                       instance_id, exc_info=True)
        return dict(orders)


def position_of(order: Sequence[str], label: str) -> Optional[int]:
    """
    Where ``label`` sat in the shown order, 0-based, or None.

    The primitive an analyst needs to correct for position bias after the fact:
    with this and the stored answer, "how often did this annotator pick
    whatever was first" is a one-line computation.
    """
    try:
        return list(order).index(label)
    except ValueError:
        return None
