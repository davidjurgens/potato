"""
Search service (universal).

Resolves the `search:` config block, builds the configured backend, and
holds a process singleton so the index is built once on server start and
reused per request. Mirrors the init/get/clear pattern of the other
managers.
"""

from __future__ import annotations

import json
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
    # Two different reasons to skip, which need two different pieces of advice.
    # They used to share one counter and one message -- "media-only items; name
    # a caption field with item_properties.text_key" -- which named the right
    # items and the wrong reason for the second kind. An author whose text_key
    # is populated has already done what that message asks, so they change
    # nothing and it repeats next boot.
    no_text_field = 0
    unusable_value = []
    for i, iid in enumerate(ism.get_instance_ids()):
        if i >= cap:
            logger.warning(
                f"search.max_instances ({cap}) reached; not indexing the rest")
            break
        data = ism.get_item(iid).get_data()
        if isinstance(data, dict):
            raw = data.get(text_key)
            text = raw if isinstance(raw, str) else None
            if text is None or not text.strip():
                # A dict or a list under text_key is a SUPPORTED shape -- the
                # page renders it as indented JSON -- so it is searchable, and
                # skipping it made the item unfindable by its own contents.
                if isinstance(raw, (dict, list)):
                    text = _structured_text(raw)
                    if text is None:
                        unusable_value.append((str(iid), type(raw).__name__))
                else:
                    if raw is not None and not isinstance(raw, str):
                        unusable_value.append((str(iid), type(raw).__name__))
                    text = _searchable_text(data)
        else:
            text = str(data)
        if not isinstance(text, str) or not text.strip():
            # Better to have nothing to find than to find ids. `get_text()`
            # returns an item's first string value, so a media corpus used to
            # index "img_01", "img_02" — a full-text index of its own filenames.
            if not unusable_value or unusable_value[-1][0] != str(iid):
                no_text_field += 1
            continue
        yield str(iid), text
    if no_text_field:
        logger.info(
            "search: %d instance(s) had no indexable text (media-only items); "
            "name a caption field with item_properties.text_key to include them",
            no_text_field)
    if unusable_value:
        shown = ", ".join(f"{iid} ({kind})" for iid, kind in unusable_value[:5])
        more = (f" and {len(unusable_value) - 5} more"
                if len(unusable_value) > 5 else "")
        logger.info(
            "search: %d instance(s) have a populated '%s' that is not text, so "
            "there is nothing to index for them: %s%s. This is not the "
            "media-only case -- the field is set; its value is a type the "
            "index cannot read.",
            len(unusable_value), text_key, shown, more)


def _structured_text(value) -> Optional[str]:
    """A dict or list rendered the way the page renders it, for indexing.

    The display path emits indented JSON for these, so indexing the same string
    means a search for a value the annotator can see on screen finds the item.
    """
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
    return text if text.strip() else None


#: Fields worth indexing when the configured text_key is absent — a caption or
#: a transcript is real text about the item; a file path is not.
_TEXTUAL_FALLBACKS = ("caption", "description", "transcript", "prompt",
                      "question", "title", "content", "message")


def _searchable_text(data: Dict[str, Any]) -> Optional[str]:
    for key in _TEXTUAL_FALLBACKS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


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


def reindex_from_item_state(config: Dict[str, Any]) -> int:
    """Rebuild the index over whatever is loaded now.

    The boot index is built before the `data_directory` load runs, so a
    directory-loaded study indexed nothing -- "FTS5 indexed 0 instances" -- and
    the watcher's later additions did not index either. `/admin/api/search`
    then answered `{"count": 0}` on a corpus where every item matched, which is
    indistinguishable from "no matches", and everything built on it (the
    curation catalog) went with it.

    Returns the number of instances indexed, or 0 when search is off.
    """
    settings = search_settings(config)
    if not settings["enabled"]:
        return 0
    backend = get_search()
    if backend is None:
        backend = init_search_from_item_state(config)
        return 0 if backend is None else 1
    try:
        return backend.index(_rows_from_item_state(config))
    except Exception as exc:
        logger.warning("Search reindex failed: %s", exc)
        return 0


def get_search() -> Optional[SearchBackend]:
    return _SEARCH


def clear_search() -> None:
    """Reset the singleton. Tests only."""
    global _SEARCH
    with _LOCK:
        _SEARCH = None
