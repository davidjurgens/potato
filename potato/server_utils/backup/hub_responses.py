"""Annotators' answers as a Hugging Face dataset, beside the backup.

The backup mirrors the annotation directory file for file, which restores a
task but is not something ``datasets`` can read: per-user state files hold
every answer in Potato's own layout. With ``responses: true`` on a
huggingface sink, the backup also writes

* ``_responses/<annotator>.responses.jsonl``, one row per item and scheme,
  and
* ``README.md``, a dataset card whose ``configs`` entry points
  ``datasets.load_dataset(repo_id)`` at those files and nothing else.

The annotation directory is mirrored to the same repo root, one folder per
user id, and every annotator folder holds ``annotation_history.jsonl``. A
plain ``responses/*.jsonl`` glob would therefore pick up the folder of a user
named ``responses``. No file Potato writes for an annotator ends in
``.responses.jsonl``, so the glob below matches only this export whatever
the user ids are.

Every row has the same columns whatever the scheme, so files from different
annotators load as one table:

``instance_id``, ``annotator``, ``scheme``, ``kind`` (``labels`` or
``spans``), ``labels`` (the label names chosen, or the span labels), and
``value`` (the stored answer, JSON-encoded).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

RESPONSES_DIR = "_responses"
RESPONSES_SUFFIX = ".responses.jsonl"
CARD_NAME = "README.md"


def annotator_filename(annotator: str) -> str:
    """A safe, distinct file name for an annotator's rows."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", annotator).strip("._") or "annotator"
    safe = safe[:80]
    if safe != annotator:
        # Two names that sanitize alike must not share a file.
        safe += "-" + hashlib.sha1(annotator.encode("utf-8")).hexdigest()[:8]
    return safe + RESPONSES_SUFFIX


def response_rows(config: Dict[str, Any]) -> Dict[str, List[dict]]:
    """Every stored answer, grouped by annotator."""
    from potato.export.cli import load_annotations_from_output_dir
    from potato.server_utils.backup import output_dir

    records = load_annotations_from_output_dir(
        output_dir(config), config.get("annotation_schemes") or [], config)
    by_annotator: Dict[str, List[dict]] = {}
    for record in sorted(records, key=lambda r: (str(r.get("user_id")),
                                                 str(r.get("instance_id")))):
        annotator = str(record.get("user_id", ""))
        rows = by_annotator.setdefault(annotator, [])
        base = {"instance_id": str(record.get("instance_id", "")), "annotator": annotator}
        for scheme, labels in sorted((record.get("labels") or {}).items()):
            if not labels:
                continue
            names = [str(n) for n in labels] if isinstance(labels, dict) else []
            rows.append({**base, "scheme": str(scheme), "kind": "labels",
                         "labels": names,
                         "value": json.dumps(labels, ensure_ascii=False, sort_keys=True)})
        for scheme, spans in sorted((record.get("spans") or {}).items()):
            if not spans:
                continue
            names = [str(s.get("label") or s.get("name") or "")
                     for s in spans if isinstance(s, dict)]
            rows.append({**base, "scheme": str(scheme), "kind": "spans",
                         "labels": names,
                         "value": json.dumps(spans, ensure_ascii=False, sort_keys=True)})
    return {annotator: rows for annotator, rows in by_annotator.items() if rows}


def dataset_card(config: Dict[str, Any], repo_id: str) -> str:
    task = config.get("annotation_task_name") or "Potato task"
    return f"""---
configs:
- config_name: default
  data_files:
  - split: train
    path: {RESPONSES_DIR}/*{RESPONSES_SUFFIX}
tags:
- potato
- annotation
---

# {task}: annotations

Collected with [Potato](https://www.potatoannotator.com). `{RESPONSES_DIR}/`
holds one file per annotator (`<annotator>{RESPONSES_SUFFIX}`), with one row
per item and annotation scheme:

| Column | Holds |
|---|---|
| `instance_id` | The item's id |
| `annotator` | Who answered |
| `scheme` | The annotation scheme's name |
| `kind` | `labels` for a choice, rating or text answer, `spans` for highlighted text |
| `labels` | The label names chosen, or the span labels |
| `value` | The answer as Potato stores it, JSON-encoded |

```python
from datasets import load_dataset

rows = load_dataset("{repo_id}", split="train")
```

The other files in this repository are Potato's backup of the task, which it
restores when the server restarts. Potato rewrites this card and the
`{RESPONSES_DIR}/` files as annotations come in.
"""


def _write(path: str, text: str) -> bool:
    """Write atomically; False when the file already held this text."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            if handle.read() == text:
                return False
    except OSError:
        pass
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(partial, path)
    return True


def write_hub_export(config: Dict[str, Any], dest: str, repo_id: str) -> int:
    """Write the card and every annotator's file under ``dest``.

    Returns the number of rows. Files are replaced atomically and left alone
    when unchanged, so an upload never sees half a file and an idle task
    commits nothing. A file whose annotator no longer has answers is removed.
    """
    responses = os.path.join(dest, RESPONSES_DIR)
    os.makedirs(responses, exist_ok=True)
    rows_by_annotator = response_rows(config)
    keep = set()
    total = 0
    for annotator, rows in rows_by_annotator.items():
        name = annotator_filename(annotator)
        keep.add(name)
        total += len(rows)
        _write(os.path.join(responses, name),
               "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    for name in os.listdir(responses):
        if name.endswith(RESPONSES_SUFFIX) and name not in keep:
            os.remove(os.path.join(responses, name))
    _write(os.path.join(dest, CARD_NAME), dataset_card(config, repo_id))
    return total


def is_export_path(relative: str) -> bool:
    """Whether a repo path is one of this export's files (not restored)."""
    parts = relative.replace(os.sep, "/").split("/")
    return len(parts) == 2 and parts[0] == RESPONSES_DIR \
        and parts[1].endswith(RESPONSES_SUFFIX)
