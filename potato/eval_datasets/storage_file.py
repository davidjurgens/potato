"""
File-based dataset storage (the default backend).

Layout under ``<base_dir>/datasets/<name>/``:
    meta.json          -- Dataset metadata (versions, tags)
    v0001.jsonl        -- full example snapshot for version v0001
    v0002.jsonl        -- ...

Git-diffable and consistent with ``judge_calibration/storage.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from typing import List, Optional

from potato.eval_datasets.models import Dataset, Example
from potato.eval_datasets.storage_base import BaseVersionedStore


class FileDatasetStore(BaseVersionedStore):
    def __init__(self, base_dir: str = "."):
        self._root = os.path.join(base_dir, "datasets")
        self._lock = threading.RLock()
        os.makedirs(self._root, exist_ok=True)

    def _dataset_dir(self, name: str) -> str:
        return os.path.join(self._root, name)

    def _meta_path(self, name: str) -> str:
        return os.path.join(self._dataset_dir(name), "meta.json")

    def _version_path(self, name: str, version_id: str) -> str:
        return os.path.join(self._dataset_dir(name), f"{version_id}.jsonl")

    # ----- primitives -----

    def _load_meta(self, name: str) -> Optional[Dataset]:
        path = self._meta_path(name)
        if not os.path.exists(path):
            return None
        with self._lock, open(path, "r", encoding="utf-8") as f:
            return Dataset.from_dict(json.load(f))

    def _save_meta(self, dataset: Dataset) -> None:
        with self._lock:
            os.makedirs(self._dataset_dir(dataset.name), exist_ok=True)
            path = self._meta_path(dataset.name)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dataset.to_dict(), f, indent=2)
            os.replace(tmp, path)

    def _load_version_examples(self, name: str, version_id: str) -> List[Example]:
        path = self._version_path(name, version_id)
        if not os.path.exists(path):
            return []
        out = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(Example.from_dict(json.loads(line)))
        return out

    def _write_version_examples(self, name: str, version_id: str, examples: List[Example]) -> None:
        with self._lock:
            os.makedirs(self._dataset_dir(name), exist_ok=True)
            path = self._version_path(name, version_id)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for e in examples:
                    f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
            os.replace(tmp, path)

    def _all_dataset_names(self) -> List[str]:
        if not os.path.isdir(self._root):
            return []
        return sorted(
            d for d in os.listdir(self._root)
            if os.path.exists(self._meta_path(d))
        )

    def _remove_dataset(self, name: str) -> bool:
        d = self._dataset_dir(name)
        if os.path.isdir(d):
            shutil.rmtree(d)
            return True
        return False
