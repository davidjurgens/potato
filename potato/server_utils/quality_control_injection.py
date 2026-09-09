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

        return user_state.assign_instance_at_index(item, insert_index)

    if qc_manager.should_inject_attention_check(username):
        attention_item = qc_manager.get_attention_check_item(username)
        if attention_item and inject_item(attention_item):
            logger.info("Injected attention check %s for user %s",
                        attention_item.get("id"), username)
            return True

    if qc_manager.should_inject_gold_standard(username):
        gold_item = qc_manager.get_gold_standard_item(username)
        if gold_item and inject_item(gold_item):
            logger.info("Injected gold standard %s for user %s",
                        gold_item.get("id"), username)
            return True

    return False


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
