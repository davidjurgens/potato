"""
Search service (universal).

Resolves the `search:` config block, builds the configured backend, and
holds a process singleton so the index is built once on server start and
reused per request. Mirrors the init/get/clear pattern of the other
managers.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Iterable, Optional, Tuple

from .backend import SearchBackend
from .fts5 import FTS5Backend

logger = logging.getLogger(__name__)

_SEARCH: Optional[SearchBackend] = None
_LOCK = threading.Lock()

_DEFAULTS = {
    "enabled": True,          # universal — on by default
    "backend": "fts5",
    "max_instances": 100000,
    "annotator_claim": False,  # annotator search-and-claim is opt-in
}


def search_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolved search settings with defaults applied."""
    raw = config.get("search")
    raw = raw if isinstance(raw, dict) else {}
    s = dict(_DEFAULTS)
    for k in _DEFAULTS:
        if k in raw:
            s[k] = raw[k]
    return s


def _build(config: Dict[str, Any]) -> Optional[SearchBackend]:
    s = search_settings(config)
    if not s["enabled"]:
        return None
    task_dir = config.get("task_dir", ".")
    if s["backend"] == "fts5":
        be = FTS5Backend(task_dir)
        if be.available():
            return be
        logger.warning("FTS5 not available in this SQLite build; "
                        "search disabled.")
        return None
    logger.warning(f"Unknown search backend {s['backend']!r}; search disabled.")
    return None


def init_search(
    config: Dict[str, Any],
    rows: Optional[Iterable[Tuple[str, str]]] = None,
) -> Optional[SearchBackend]:
    """Build the backend singleton and (optionally) index *rows*.

    Returns None when search is disabled/unavailable. Calling twice keeps
    the existing singleton (but re-indexes if rows are provided)."""
    global _SEARCH
    with _LOCK:
        if _SEARCH is None:
            _SEARCH = _build(config)
        if _SEARCH is not None and rows is not None:
            try:
                _SEARCH.index(rows)
            except Exception as e:
                logger.error(f"Search index build failed: {e}")
        return _SEARCH


def _rows_from_item_state(config: Dict[str, Any]):
    """Yield (instance_id, text) for every loaded instance, using the
    config's text_key. Bounded by search.max_instances."""
    from potato.item_state_management import get_item_state_manager

    text_key = (config.get("item_properties") or {}).get("text_key", "text")
    cap = search_settings(config)["max_instances"]
    ism = get_item_state_manager()
    for i, iid in enumerate(ism.get_instance_ids()):
        if i >= cap:
            logger.warning(
                f"search.max_instances ({cap}) reached; not indexing the rest")
            break
        data = ism.get_item(iid).get_data()
        if isinstance(data, dict):
            text = data.get(text_key) or ism.get_item(iid).get_text()
        else:
            text = str(data)
        yield str(iid), text if isinstance(text, str) else str(text)


def init_search_from_item_state(
    config: Dict[str, Any]
) -> Optional[SearchBackend]:
    """Server-start entry point: build the backend and index all loaded
    instances. No-op when search is disabled/unavailable."""
    settings = search_settings(config)
    if not settings["enabled"]:
        logger.info("Search disabled in config")
        return None
    return init_search(config, rows=_rows_from_item_state(config))


def get_search() -> Optional[SearchBackend]:
    return _SEARCH


def clear_search() -> None:
    """Reset the singleton. Tests only."""
    global _SEARCH
    with _LOCK:
        _SEARCH = None
