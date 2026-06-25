"""
Persistence for Judge Calibration LLM results.

LLM verdicts are stored in a dedicated JSON file under ``state_dir`` — NOT as
pseudo-users in the annotation store. This keeps them entirely out of the
human annotation data path (guaranteeing humans never see them) and avoids
polluting assignment/quota logic.

The on-disk shape is a flat list of ``ModelItemResult`` dicts keyed implicitly
by (model, instance_id, schema_name). ``ResultStore`` provides idempotent
upsert so an interrupted GENERATING phase can resume without duplicating work.
"""

import json
import logging
import os
import threading
from typing import Dict, List, Optional, Tuple

from potato.judge_calibration.aggregation import ModelItemResult

logger = logging.getLogger(__name__)


class ResultStore:
    """In-memory store of ModelItemResults with atomic JSON persistence."""

    _RESULTS_FILE = "llm_results.json"

    def __init__(self, state_dir: Optional[str] = None):
        self._lock = threading.RLock()
        self.state_dir = state_dir
        # (model, instance_id, schema_name) -> ModelItemResult
        self._results: Dict[Tuple[str, str, str], ModelItemResult] = {}

    @staticmethod
    def _key(model: str, instance_id: str, schema_name: str) -> Tuple[str, str, str]:
        return (model, instance_id, schema_name)

    def upsert(self, result: ModelItemResult, save: bool = True) -> None:
        with self._lock:
            self._results[self._key(result.model, result.instance_id, result.schema_name)] = result
            if save:
                self._save()

    def upsert_many(self, results: List[ModelItemResult]) -> None:
        with self._lock:
            for r in results:
                self._results[self._key(r.model, r.instance_id, r.schema_name)] = r
            self._save()

    def has(self, model: str, instance_id: str, schema_name: str) -> bool:
        with self._lock:
            return self._key(model, instance_id, schema_name) in self._results

    def get(self, model: str, instance_id: str, schema_name: str) -> Optional[ModelItemResult]:
        with self._lock:
            return self._results.get(self._key(model, instance_id, schema_name))

    def all_results(self) -> List[ModelItemResult]:
        with self._lock:
            return list(self._results.values())

    def models(self) -> List[str]:
        with self._lock:
            return sorted({r.model for r in self._results.values()})

    def labeled_instance_ids(self) -> List[str]:
        """Instance ids that have at least one model result."""
        with self._lock:
            return sorted({r.instance_id for r in self._results.values()})

    def count(self) -> int:
        with self._lock:
            return len(self._results)

    def clear(self) -> None:
        with self._lock:
            self._results = {}
            self._save()

    # ----- persistence ----------------------------------------------------

    def _save(self) -> None:
        if not self.state_dir:
            return
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            path = os.path.join(self.state_dir, self._RESULTS_FILE)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump([r.to_dict() for r in self._results.values()], f)
            os.replace(tmp, path)
        except Exception as e:
            logger.error("Error saving JC results: %s", e)

    def load(self) -> bool:
        if not self.state_dir:
            return False
        path = os.path.join(self.state_dir, self._RESULTS_FILE)
        if not os.path.exists(path):
            return False
        try:
            with open(path) as f:
                data = json.load(f)
            with self._lock:
                self._results = {}
                for d in data:
                    r = ModelItemResult.from_dict(d)
                    self._results[self._key(r.model, r.instance_id, r.schema_name)] = r
            logger.info("Loaded %d JC results", len(self._results))
            return True
        except Exception as e:
            logger.error("Error loading JC results: %s", e)
            return False
