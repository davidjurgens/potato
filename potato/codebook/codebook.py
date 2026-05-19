"""
Codebook read-model.

A thin, read-only view over the `codes` table for one project: builds
the code tree and the flat label list the schema-loader bridge needs.
Mutations go through `service.py` (the single audited write path).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from potato.codebook import store


class Codebook:
    """In-memory snapshot of a project's codebook.

    Construct via `Codebook.load(task_dir, project)`. Cheap to rebuild;
    callers reload after a mutation rather than mutating the snapshot.
    """

    def __init__(self, project: str, codes: List[Dict[str, Any]]):
        self.project = project
        self._codes = codes
        self._by_id: Dict[str, Dict[str, Any]] = {c["id"]: c for c in codes}

    @classmethod
    def load(cls, task_dir: str, project: str) -> "Codebook":
        return cls(project, store.list_codes(task_dir, project))

    def __len__(self) -> int:
        return len(self._codes)

    def is_empty(self) -> bool:
        return not self._codes

    def get(self, code_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(code_id)

    def children(self, parent_id: str = store.ROOT) -> List[Dict[str, Any]]:
        kids = [c for c in self._codes if c["parent_id"] == parent_id]
        kids.sort(key=lambda c: (c["sort_order"], c["name"]))
        return kids

    def labels(self) -> List[str]:
        """Flat list of code names in tree order — the legacy label list
        the radio/multiselect/span loaders consume when a scheme opts in
        via `codebook: true`."""
        out: List[str] = []

        def walk(parent: str) -> None:
            for c in self.children(parent):
                out.append(c["name"])
                walk(c["id"])

        walk(store.ROOT)
        return out

    def label_to_id(self) -> Dict[str, str]:
        """Map code name -> code id (first occurrence in tree order).
        Lets the annotation pipeline store a parallel `code_id` while
        keeping the legacy `label` string."""
        mapping: Dict[str, str] = {}
        for name in self.labels():
            if name not in mapping:
                match = next(
                    (c for c in self._codes if c["name"] == name), None)
                if match:
                    mapping[name] = match["id"]
        return mapping

    def as_tree(self) -> List[Dict[str, Any]]:
        """Nested [{id,name,color,children:[...]}] for the codebook UI."""

        def node(c: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "id": c["id"],
                "name": c["name"],
                "color": c["color"],
                "children": [node(k) for k in self.children(c["id"])],
            }

        return [node(c) for c in self.children(store.ROOT)]
