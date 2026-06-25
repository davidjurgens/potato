"""
Data model for Datasets, versions, and examples.

A Dataset is a named collection of Examples (inputs + optional reference
outputs). Every mutation (add/update/delete) produces a new immutable
*version* — a full snapshot of the example set at that point — identified by a
monotonic sequence id (``v0001``). Versions may carry human-readable tags
(e.g. ``prod``) used by ``as_of`` resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Example:
    """One dataset row."""

    id: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    reference_outputs: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    split: str = "test"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "inputs": self.inputs,
            "reference_outputs": self.reference_outputs,
            "metadata": self.metadata,
            "split": self.split,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Example":
        return cls(
            id=str(d.get("id", "")),
            inputs=d.get("inputs", {}) or {},
            reference_outputs=d.get("reference_outputs"),
            metadata=d.get("metadata", {}) or {},
            split=d.get("split", "test") or "test",
        )


@dataclass
class DatasetVersion:
    """Metadata for one immutable version snapshot."""

    version_id: str  # monotonic, e.g. "v0001"
    created_at: str  # ISO timestamp
    example_count: int = 0
    tags: List[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "created_at": self.created_at,
            "example_count": self.example_count,
            "tags": list(self.tags),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DatasetVersion":
        return cls(
            version_id=d["version_id"],
            created_at=d.get("created_at", ""),
            example_count=int(d.get("example_count", 0)),
            tags=list(d.get("tags", [])),
            note=d.get("note", ""),
        )


@dataclass
class Dataset:
    """A named dataset with its version history."""

    name: str
    description: str = ""
    created_at: str = ""
    versions: List[DatasetVersion] = field(default_factory=list)

    @property
    def latest_version(self) -> Optional[DatasetVersion]:
        return self.versions[-1] if self.versions else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "versions": [v.to_dict() for v in self.versions],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Dataset":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            created_at=d.get("created_at", ""),
            versions=[DatasetVersion.from_dict(v) for v in d.get("versions", [])],
        )
