"""
The item view sources read.

Sources never touch ``ItemStateManager`` or the item store directly. The
runner hands them ``ItemView`` objects built by whoever is driving the run:
the live server reads them from the item manager, the headless CLI from the
data files. Either way the text is the configured ``text_key`` field, which is
what an annotator sees, not the item id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .model.records import content_hash


@dataclass
class ItemView:
    item_id: str
    text: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    stratum: Optional[str] = None

    def content_hash(self) -> str:
        return content_hash(self.data or self.text)[:32]


def text_of(data: Dict[str, Any], text_key: str = "text") -> str:
    value = data.get(text_key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    # Dialogue turns, lists of sentences, nested records: give the model the
    # same JSON a reviewer would see, not Python's repr.
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def views_from_records(records: Iterable[Dict[str, Any]], id_key: str = "id",
                       text_key: str = "text") -> List[ItemView]:
    return [ItemView(item_id=str(r.get(id_key)), text=text_of(r, text_key), data=dict(r))
            for r in records if r.get(id_key) is not None]


def views_from_item_manager(ism, config: Dict[str, Any],
                            item_ids: Optional[Iterable[str]] = None) -> List[ItemView]:
    """ItemViews for items in a live ItemStateManager."""
    props = config.get("item_properties") or {}
    text_key = props.get("text_key", "text")
    ids = list(item_ids) if item_ids is not None else list(ism.get_instance_ids())
    out = []
    for iid in ids:
        item = ism.get_item(iid)
        if item is None:
            continue
        data = item.get_data() if hasattr(item, "get_data") else (item.item_data or {})
        out.append(ItemView(item_id=str(iid), text=text_of(data, text_key), data=dict(data)))
    return out
