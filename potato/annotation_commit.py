"""
The end of every annotation write: both sides of the record, then listeners.

An annotation lives on the user side (``UserState``, saved to disk) and is
counted on the item side (``ItemStateManager.instance_annotators``), which is
what caps, saturation, IAA, adjudication routing, crowd auto-scaling and MACE
read. A writer that updated only the user side made the work invisible to all
of those: the MCP path did this, and /admin/iaa reported zero annotators on a
fully labeled scheme.

``finish_annotation_write`` is the one place that does both, in the order that
keeps them consistent, and then tells the labeling engine a person has
answered. Every writer calls it after putting labels on the user state.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def finish_annotation_write(user_state, instance_id: str, username: str,
                            register_always: bool = False) -> None:
    """Register (or unregister) the annotator, save, and notify listeners.

    A save that left nothing on the item (every answer cleared) takes the
    annotator back off it, unless ``register_always`` is set by a writer that
    has just confirmed it wrote something.
    """
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager

    ism = get_item_state_manager()
    try:
        if register_always or user_state.has_annotated(instance_id):
            ism.register_annotator(instance_id, username)
        else:
            ism.unregister_annotator(instance_id, username)
    except Exception as e:  # noqa: BLE001 - bookkeeping must not lose the write
        logger.warning(
            "Stored %s's annotation of %s but could not update the item's annotator "
            "set, so agreement and progress will undercount: %s",
            username, instance_id, e)

    get_user_state_manager().save_user_state(user_state)

    from potato.labeling_engine.integration.hooks import on_human_save
    on_human_save(user_state, instance_id)
