"""Putting an attention check or a gold item into an annotator's ordering.

This lives here rather than in ``routes.py`` because more than one surface
serves work. The function had exactly one caller, inside the ``/annotate``
view, and ``/pocket/api/batch`` served the ordering as it found it -- so an
annotator working through the phone received no attention checks and no gold
items, ever, while ``pocket.auto_redirect`` defaults to true and sends phones
there. The accounting already crossed the surface: ``items_since_attention``
counts every save wherever it came from, so quality control knew a phone
annotator was overdue and simply never delivered.

Importing it from ``potato.routes`` is not an option for a blueprint. That
module registers its views with ``@app.route`` at import time, so importing it
from inside a request on a live server raises "View function mapping is
overwriting an existing endpoint function" -- which a try/except then turns
into a feature that is silently inert. A unit test that patches
``potato.routes`` never sees this, because nothing has registered the app yet.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def inject_quality_control_item_if_needed(username, user_state,
                                          config: Dict[str, Any]) -> bool:
    """Insert one check or gold item after the annotator's current position.

    Returns True if something was inserted. At most one per call: the manager
    resets its counter when it hands an item out, so a second call in the same
    request has nothing to give.
    """
    from potato.item_state_management import get_item_state_manager
    from potato.quality_control import get_quality_control_manager

    qc_manager = get_quality_control_manager()
    if not qc_manager:
        return False

    current_instance = user_state.get_current_instance()
    current_instance_id = current_instance.get_id() if current_instance else None
    if current_instance_id and (
        qc_manager.is_attention_check(current_instance_id)
        or qc_manager.is_gold_standard(current_instance_id)
    ):
        return False

    assigned_ids = set(user_state.get_assigned_instance_ids())
    annotated_ids = (set(user_state.get_annotated_instance_ids())
                     if hasattr(user_state, "get_annotated_instance_ids")
                     else set())
    seen_qc_ids = assigned_ids | annotated_ids

    current_index = user_state.get_current_instance_index()
    insert_index = current_index + 1 if current_index >= 0 else 0

    def inject_item(item_data):
        return _place_item(user_state, item_data, config, insert_index, seen_qc_ids)

    if qc_manager.should_inject_attention_check(username):
        attention_item = qc_manager.get_attention_check_item(username, exclude=seen_qc_ids)
        if attention_item and inject_item(attention_item):
            logger.info("Injected attention check %s for user %s",
                        attention_item.get("id"), username)
            return True

    if qc_manager.should_inject_gold_standard(username):
        gold_item = qc_manager.get_gold_standard_item(username, exclude=seen_qc_ids)
        if gold_item and inject_item(gold_item):
            logger.info("Injected gold standard %s for user %s",
                        gold_item.get("id"), username)
            return True

    return False


def _place_item(user_state, item_data, config, index, seen_qc_ids) -> bool:
    """Add a check or gold item to the item store and the user's ordering."""
    from potato.item_state_management import get_item_state_manager

    item_id = item_data.get("id")
    if not item_id or item_id in seen_qc_ids:
        return False

    prepared_item = dict(item_data)
    text_key = (config.get("item_properties") or {}).get("text_key", "text")
    if "displayed_text" not in prepared_item:
        raw_text = prepared_item.get(text_key, prepared_item.get("text", ""))
        prepared_item["displayed_text"] = (
            _displayed_text(raw_text) if raw_text is not None else "")

    item_manager = get_item_state_manager()
    if item_manager.has_item(item_id):
        existing_item = item_manager.get_item(item_id)
        if existing_item and isinstance(existing_item.get_data(), dict):
            existing_data = existing_item.get_data()
            if "displayed_text" not in existing_data:
                existing_data["displayed_text"] = prepared_item["displayed_text"]
        item = item_manager.get_item(item_id)
    else:
        item_manager.add_item(item_id, prepared_item)
        item = item_manager.get_item(item_id)

    placed = user_state.assign_instance_at_index(item, index)
    if placed:
        seen_qc_ids.add(item_id)
    return placed


def quality_control_page(username, user_state, config, normal_ids):
    """A page of item ids with attention checks and gold items placed in it.

    For surfaces that show several items at once (the grid). The single-item
    injector adds one item and resets the manager's counter, which is right
    for a page of one; on a page of 24 it delivered one check where the config
    asked for eight, and the grid -- the surface built for fast clicking --
    delivered none at all.

    Counts are projected across the page: with `frequency: N` a check goes in
    after every N regular items, starting from how many the annotator has done
    since their last one. Each placed item is assigned exactly as the
    single-item path assigns it, so saving it is scored the same way. Handing
    an item out resets the manager's counter, so the next page may open with
    a check: delivery errs towards more checks, never fewer.
    """
    from potato.quality_control import get_quality_control_manager

    qc = get_quality_control_manager()
    if not qc:
        return list(normal_ids)

    assigned = set(user_state.get_assigned_instance_ids())
    annotated = set(user_state.get_annotated_instance_ids())
    seen_qc_ids = assigned | annotated
    cfg = qc.qc_config

    attention_on = bool(cfg.attention_checks_enabled and qc.attention_items)
    gold_on = bool(cfg.gold_standards_enabled and qc.gold_items
                   and getattr(cfg, "gold_mode", None) != "training")
    since_attention = qc.user_items_since_attention.get(username, 0)
    since_gold = qc.user_items_since_gold.get(username, 0)

    def due(on, since, frequency, probability=None):
        if not on:
            return False
        if frequency:
            return since >= frequency
        if probability:
            import random
            return random.random() < probability
        return False

    page = []
    ordering = user_state.instance_id_ordering
    for iid in list(normal_ids) + [None]:
        # Before each regular item (and once after the last), place whatever
        # is due. `None` marks the end of the page.
        index = ordering.index(iid) if iid in ordering else len(ordering)
        if due(attention_on, since_attention, cfg.attention_frequency,
               getattr(cfg, "attention_probability", None)):
            item = qc.get_attention_check_item(username, exclude=seen_qc_ids)
            if item and _place_item(user_state, item, config, index, seen_qc_ids):
                page.append(item["id"])
                since_attention = 0
                index += 1
        if due(gold_on, since_gold, getattr(cfg, "gold_frequency", None)):
            item = qc.get_gold_standard_item(username, exclude=seen_qc_ids)
            if item and _place_item(user_state, item, config, index, seen_qc_ids):
                page.append(item["id"])
                since_gold = 0
        if iid is None:
            break
        page.append(iid)
        since_attention += 1
        since_gold += 1
    return page


def _displayed_text(raw_text):
    """`flask_server.get_displayed_text`, imported late.

    flask_server is heavy and imports this package's siblings, so pulling it in
    at module scope would make a blueprint's import order matter.
    """
    try:
        from potato.flask_server import get_displayed_text

        return get_displayed_text(raw_text)
    except Exception:  # pragma: no cover - fall back to the raw string
        return raw_text if isinstance(raw_text, str) else str(raw_text)
