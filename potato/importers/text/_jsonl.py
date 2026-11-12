"""
Shared JSONL reading for the doccano and Prodigy importers.

The two formats are close enough that a single reader handles the container
and the offset convention, and different enough in their *keys* that they get
one importer each. Putting the shared half here is deliberate: on the CV side
the same helper was copy-pasted into five importers, and three of them then
quietly stopped honouring a flag the other two did.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

#: Both formats write character offsets with an exclusive end, matching Potato.
#: Recorded here so a future format that does not can be spotted by its absence
#: from this module rather than by a shifted span in someone's project.
OFFSETS_ARE_EXCLUSIVE_CODEPOINTS = True


def read_jsonl(path: Path) -> List[dict]:
    """
    Read newline-delimited JSON, tolerating a plain JSON array.

    Every doccano export is JSONL, but people hand-edit them and a
    ``json.dumps(list)`` round trip is the most common way one arrives as an
    array instead. Failing on that with "Extra data: line 2" reads as file
    corruption rather than as a different container.
    """
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("["):
        loaded = json.loads(text)
        if not isinstance(loaded, list):
            raise ValueError(f"{path} is JSON but not a list of records")
        return [r for r in loaded if isinstance(r, dict)]

    records = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno} is not valid JSON: {exc}") from exc
        if isinstance(record, dict):
            records.append(record)
    return records


def peek_jsonl(path: Path, limit: int = 5) -> Iterator[dict]:
    """
    Yield the first few records without reading a large file into memory.

    Detection runs against every registered importer in turn, so it must not
    cost a full parse of a multi-gigabyte export just to answer "is this
    yours?".
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            first = handle.readline().lstrip()
            if first.startswith("["):
                # An array: reading it properly needs the whole file, so
                # detection reads a bounded prefix and gives up rather than
                # loading it.
                return
            handle.seek(0)
            for _ in range(limit):
                line = handle.readline()
                if not line:
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    return
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def coerce_span(entry: Any) -> Optional[Tuple[int, int, str]]:
    """
    Read one label entry into ``(start, end, label)``.

    doccano has emitted at least three shapes across versions -- a bare
    ``[start, end, label]`` list, a ``{"start_offset", "end_offset", "label"}``
    dict, and a ``{"start", "end", "label"}`` dict -- and a reader that knows
    only the current one silently imports zero spans from an older export
    while reporting success.
    """
    if isinstance(entry, (list, tuple)) and len(entry) >= 3:
        try:
            return int(entry[0]), int(entry[1]), str(entry[2])
        except (TypeError, ValueError):
            return None

    if not isinstance(entry, dict):
        return None

    start = entry.get("start_offset", entry.get("start"))
    end = entry.get("end_offset", entry.get("end"))
    label = entry.get("label", entry.get("type"))
    if start is None or end is None or label is None:
        return None
    try:
        return int(start), int(end), str(label)
    except (TypeError, ValueError):
        return None
