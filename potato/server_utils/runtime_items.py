"""Items added while the server runs, kept across a restart.

The data files are reread on every boot, but items that arrive later -- a
trace posted to the ingestion webhook, an item an agent adds through MCP --
existed only in memory. After a restart they were gone, and loading each
annotator's state pruned them from the annotator's queue and saved the
shorter queue back, so the loss outlived the next restart too.

Each such item is appended to ``<output_annotation_dir>/runtime_items.jsonl``
when it is added, and :func:`load_runtime_items` adds them back after the data
files load and before annotator state does.
"""

from __future__ import annotations

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

JOURNAL_NAME = "runtime_items.jsonl"
_lock = threading.Lock()


def _journal_path(config) -> str | None:
    out = (config or {}).get("output_annotation_dir")
    return os.path.join(out, JOURNAL_NAME) if out else None


def record_runtime_item(config, instance_id: str, data: dict, source: str) -> None:
    """Append an item added at runtime so the next boot adds it again."""
    path = _journal_path(config)
    if not path:
        logger.warning("No output_annotation_dir: runtime item %s will not survive a restart",
                       instance_id)
        return
    line = json.dumps({"id": str(instance_id), "source": source, "data": data},
                      ensure_ascii=False, default=str)
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_runtime_items(config, ism) -> int:
    """Add back every journalled item the data files did not already supply."""
    path = _journal_path(config)
    if not path or not os.path.isfile(path):
        return 0
    added = 0
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                instance_id = str(record["id"])
                data = record["data"]
            except (ValueError, KeyError, TypeError):
                logger.error("%s line %d is not a runtime item record; skipped", path, number)
                continue
            if ism.has_item(instance_id):
                continue
            ism.add_item(instance_id, data)
            added += 1
    if added:
        logger.info("Restored %d item(s) added at runtime before the last restart", added)
    return added
