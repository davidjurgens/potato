"""
Storage interface for datasets + a factory selecting the backend.

Two backends implement this interface (selected via ``datasets.storage``):
  - ``file``   -> storage_file.FileDatasetStore   (JSONL snapshots; default)
  - ``sqlite`` -> storage_sqlite.SQLiteDatasetStore

Both are exercised by the same parametrized test suite so they stay in parity.
Versioning is snapshot-per-mutation: every add/update/delete writes a new full
version. ``as_of`` accepts "latest", a tag name, or an explicit version id.
"""

from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional

from potato.eval_datasets.models import Dataset, DatasetVersion, Example


class DatasetStore(abc.ABC):
    """Abstract persistence for datasets, versions, and examples."""

    # ----- datasets -----
    @abc.abstractmethod
    def create_dataset(self, name: str, description: str = "") -> Dataset: ...

    @abc.abstractmethod
    def get_dataset(self, name: str) -> Optional[Dataset]: ...

    @abc.abstractmethod
    def list_datasets(self) -> List[Dataset]: ...

    @abc.abstractmethod
    def delete_dataset(self, name: str) -> bool: ...

    # ----- examples (mutations create a new version) -----
    @abc.abstractmethod
    def add_examples(self, name: str, examples: List[Example], note: str = "") -> DatasetVersion: ...

    @abc.abstractmethod
    def update_example(self, name: str, example: Example, note: str = "") -> DatasetVersion: ...

    @abc.abstractmethod
    def delete_example(self, name: str, example_id: str, note: str = "") -> DatasetVersion: ...

    # ----- reads -----
    @abc.abstractmethod
    def list_examples(
        self,
        name: str,
        as_of: str = "latest",
        splits: Optional[List[str]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Example]: ...

    @abc.abstractmethod
    def list_versions(self, name: str) -> List[DatasetVersion]: ...

    # ----- version tags -----
    @abc.abstractmethod
    def tag_version(self, name: str, version_id: str, tag: str) -> bool: ...

    @abc.abstractmethod
    def resolve_version(self, name: str, as_of: str) -> Optional[str]:
        """Resolve 'latest' | <tag> | <version_id> to a concrete version id."""
        ...


def create_store(backend: str = "file", base_dir: str = ".") -> DatasetStore:
    """Factory: build the configured storage backend."""
    backend = (backend or "file").lower()
    if backend == "file":
        from potato.eval_datasets.storage_file import FileDatasetStore
        return FileDatasetStore(base_dir)
    if backend == "sqlite":
        from potato.eval_datasets.storage_sqlite import SQLiteDatasetStore
        return SQLiteDatasetStore(base_dir)
    raise ValueError(f"Unknown dataset storage backend: {backend!r} (use 'file' or 'sqlite')")


# ----- shared filtering helpers (used by both backends) -----

def filter_examples(
    examples: List[Example],
    splits: Optional[List[str]] = None,
    metadata_filter: Optional[Dict[str, Any]] = None,
) -> List[Example]:
    out = examples
    if splits:
        split_set = set(splits)
        out = [e for e in out if e.split in split_set]
    if metadata_filter:
        out = [
            e for e in out
            if all(e.metadata.get(k) == v for k, v in metadata_filter.items())
        ]
    return out
