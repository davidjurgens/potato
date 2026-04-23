"""
Persistent library of validated ICL examples.

Each entry has been shown to improve validation accuracy. Strategies add
entries; the labeling thread reads them via the existing `examples_getter`
callback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ICLEntry:
    """A single validated ICL example."""
    instance_id: str
    text: str
    label: str
    principle: str = ""  # optional one-line rationale
    added_at_cycle: int = 0
    val_accuracy_gain: float = 0.0  # proven improvement on val set when added
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ICLEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ICLLibrary:
    """Manages validated ICL examples.

    The library is per-dataset (keyed by state_dir), keeping validated
    examples from SST-2 out of GoEmotions' prompts.

    Entries are returned by the `examples_getter` callback used by the
    LLM labeling thread.
    """

    def __init__(self, max_size: int = 10):
        """
        Args:
            max_size: maximum number of examples to return via get_examples().
                      The library can store more; get_examples() returns the
                      top-K by val_accuracy_gain.
        """
        self.max_size = max_size
        self._entries: List[ICLEntry] = []

    def add(self, entry: ICLEntry) -> None:
        """Add a validated entry. Dedupe by instance_id."""
        existing_ids = {e.instance_id for e in self._entries}
        if entry.instance_id in existing_ids:
            logger.debug(f"[ICLLibrary] Skipping duplicate for {entry.instance_id}")
            return
        self._entries.append(entry)
        logger.info(
            f"[ICLLibrary] Added {entry.instance_id} "
            f"(label={entry.label}, gain=+{entry.val_accuracy_gain:.3f})"
        )

    def remove(self, instance_id: str) -> bool:
        """Remove an entry by instance_id. Returns True if removed."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.instance_id != instance_id]
        return len(self._entries) < before

    def get_examples(self, max_per_label: int = 1, max_total: int = 5) -> List[Dict[str, str]]:
        """Get the current ICL examples for injection into a labeling prompt.

        Returns highest-gain entries, at most max_per_label per label, up to
        max_total total examples.
        """
        # Sort by gain descending
        sorted_entries = sorted(self._entries, key=lambda e: e.val_accuracy_gain, reverse=True)

        by_label: Dict[str, int] = {}
        result: List[Dict[str, str]] = []
        for entry in sorted_entries:
            count = by_label.get(entry.label, 0)
            if count >= max_per_label:
                continue
            result.append({
                "text": entry.text[:200],
                "label": entry.label,
                "principle": entry.principle,
            })
            by_label[entry.label] = count + 1
            if len(result) >= max_total:
                break

        return result

    def size(self) -> int:
        return len(self._entries)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_size": self.max_size,
            "entries": [e.to_dict() for e in self._entries],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ICLLibrary":
        lib = cls(max_size=data.get("max_size", 10))
        lib._entries = [ICLEntry.from_dict(e) for e in data.get("entries", [])]
        return lib

    def list_all(self) -> List[ICLEntry]:
        return list(self._entries)
