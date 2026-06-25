"""
Shared versioning orchestration for dataset storage backends.

``BaseVersionedStore`` implements the snapshot-per-mutation logic (add / update /
delete -> new full version, plus tag resolution and filtering) in terms of a
handful of backend primitives. ``FileDatasetStore`` and ``SQLiteDatasetStore``
only implement those primitives, guaranteeing identical versioning semantics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from potato.eval_datasets.models import Dataset, DatasetVersion, Example
from potato.eval_datasets.storage import DatasetStore, filter_examples


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class BaseVersionedStore(DatasetStore):
    # ----- backend primitives (implemented by subclasses) -----

    def _load_meta(self, name: str) -> Optional[Dataset]:  # pragma: no cover
        raise NotImplementedError

    def _save_meta(self, dataset: Dataset) -> None:  # pragma: no cover
        raise NotImplementedError

    def _load_version_examples(self, name: str, version_id: str) -> List[Example]:  # pragma: no cover
        raise NotImplementedError

    def _write_version_examples(self, name: str, version_id: str, examples: List[Example]) -> None:  # pragma: no cover
        raise NotImplementedError

    def _all_dataset_names(self) -> List[str]:  # pragma: no cover
        raise NotImplementedError

    def _remove_dataset(self, name: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    # ----- DatasetStore: datasets -----

    def create_dataset(self, name: str, description: str = "") -> Dataset:
        existing = self._load_meta(name)
        if existing is not None:
            return existing
        ds = Dataset(name=name, description=description, created_at=_now(), versions=[])
        self._save_meta(ds)
        return ds

    def get_dataset(self, name: str) -> Optional[Dataset]:
        return self._load_meta(name)

    def list_datasets(self) -> List[Dataset]:
        out = []
        for n in self._all_dataset_names():
            ds = self._load_meta(n)
            if ds is not None:
                out.append(ds)
        return out

    def delete_dataset(self, name: str) -> bool:
        return self._remove_dataset(name)

    # ----- versioning -----

    @staticmethod
    def _next_version_id(dataset: Dataset) -> str:
        return f"v{len(dataset.versions) + 1:04d}"

    def _current_examples(self, dataset: Dataset) -> List[Example]:
        latest = dataset.latest_version
        if latest is None:
            return []
        return self._load_version_examples(dataset.name, latest.version_id)

    def _commit_version(self, dataset: Dataset, examples: List[Example], note: str) -> DatasetVersion:
        version_id = self._next_version_id(dataset)
        version = DatasetVersion(
            version_id=version_id,
            created_at=_now(),
            example_count=len(examples),
            tags=[],
            note=note,
        )
        self._write_version_examples(dataset.name, version_id, examples)
        dataset.versions.append(version)
        self._save_meta(dataset)
        return version

    def _require(self, name: str) -> Dataset:
        ds = self._load_meta(name)
        if ds is None:
            ds = self.create_dataset(name)
        return ds

    def add_examples(self, name: str, examples: List[Example], note: str = "") -> DatasetVersion:
        ds = self._require(name)
        current = self._current_examples(ds)
        by_id = {e.id: e for e in current}
        for e in examples:
            by_id[e.id] = e  # add or replace
        merged = list(by_id.values())
        return self._commit_version(ds, merged, note or f"add {len(examples)} example(s)")

    def update_example(self, name: str, example: Example, note: str = "") -> DatasetVersion:
        ds = self._require(name)
        current = self._current_examples(ds)
        by_id = {e.id: e for e in current}
        by_id[example.id] = example
        return self._commit_version(ds, list(by_id.values()), note or f"update {example.id}")

    def delete_example(self, name: str, example_id: str, note: str = "") -> DatasetVersion:
        ds = self._require(name)
        current = self._current_examples(ds)
        remaining = [e for e in current if e.id != example_id]
        return self._commit_version(ds, remaining, note or f"delete {example_id}")

    # ----- reads -----

    def resolve_version(self, name: str, as_of: str) -> Optional[str]:
        ds = self._load_meta(name)
        if ds is None or not ds.versions:
            return None
        as_of = as_of or "latest"
        if as_of == "latest":
            return ds.versions[-1].version_id
        # tag match (most recent version carrying the tag)
        for v in reversed(ds.versions):
            if as_of in v.tags:
                return v.version_id
        # explicit version id
        for v in ds.versions:
            if v.version_id == as_of:
                return v.version_id
        return None

    def list_examples(
        self,
        name: str,
        as_of: str = "latest",
        splits: Optional[List[str]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Example]:
        version_id = self.resolve_version(name, as_of)
        if version_id is None:
            return []
        examples = self._load_version_examples(name, version_id)
        return filter_examples(examples, splits, metadata_filter)

    def list_versions(self, name: str) -> List[DatasetVersion]:
        ds = self._load_meta(name)
        return list(ds.versions) if ds else []

    def tag_version(self, name: str, version_id: str, tag: str) -> bool:
        ds = self._load_meta(name)
        if ds is None:
            return False
        # a tag points to exactly one version: remove it from any other version
        target = None
        for v in ds.versions:
            if tag in v.tags and v.version_id != version_id:
                v.tags.remove(tag)
            if v.version_id == version_id:
                target = v
        if target is None:
            return False
        if tag not in target.tags:
            target.tags.append(tag)
        self._save_meta(ds)
        return True
