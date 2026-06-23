"""
Datasets/Experiments manager (singleton, mirrors the judge_calibration pattern).

Owns the configured dataset + experiment stores and the experiment-id sequence.
Initialized in ``create_app()`` when a ``datasets:`` config block is enabled.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional

from potato.eval_datasets.config import DatasetsConfig
from potato.eval_datasets.export import export_examples
from potato.eval_datasets.models import DatasetVersion, Example
from potato.eval_datasets.storage import create_store, DatasetStore

# NOTE: ``potato.experiments`` is imported lazily (inside __init__ / run) to
# avoid a circular import: experiments/__init__ -> runner -> datasets.storage ->
# datasets/__init__ -> manager. Keeping these imports at function scope breaks
# the cycle so either package can be imported first.

logger = logging.getLogger(__name__)


class DatasetsManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.settings = DatasetsConfig.from_config(config)
        base_dir = self._resolve_base_dir(config)
        self.store: DatasetStore = create_store(self.settings.storage, base_dir)
        from potato.experiments.storage import create_experiment_store
        self.experiments = create_experiment_store(self.settings.storage, base_dir)
        self._lock = threading.RLock()
        logger.info(
            f"DatasetsManager initialized (storage={self.settings.storage}, base={base_dir})"
        )

    @staticmethod
    def _resolve_base_dir(config: Dict[str, Any]) -> str:
        out_dir = (config or {}).get("output_annotation_dir") or "."
        base = os.path.join(out_dir, "eval_store")
        os.makedirs(base, exist_ok=True)
        return base

    # ----- experiments -----

    def next_experiment_id(self) -> str:
        with self._lock:
            return f"exp-{len(self.experiments.list()) + 1:04d}"

    def run(
        self,
        dataset_name: str,
        evaluator_specs: List[Dict[str, Any]],
        *,
        name: str = "",
        outputs_map: Optional[Dict[str, Any]] = None,
        as_of: str = "latest",
        splits: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "Experiment":  # noqa: F821 - lazily imported below
        from potato.experiments.runner import run_experiment
        exp = run_experiment(
            self.store,
            dataset_name,
            evaluator_specs,
            experiment_id=self.next_experiment_id(),
            name=name,
            outputs_map=outputs_map,
            as_of=as_of,
            splits=splits,
            metadata=metadata,
        )
        self.experiments.save(exp)
        return exp

    # ----- export -----

    def export_jsonl(self, dataset_name: str, fmt: str, as_of: str = "latest"):
        """Export a dataset version to SFT/DPO JSONL. Returns (jsonl, skipped)."""
        examples = self.store.list_examples(dataset_name, as_of=as_of)
        return export_examples(examples, fmt)

    # ----- curate from the live annotation task -----

    # id prefixes / source markers that identify a runtime-ingested trace
    _TRACE_SOURCES = ("webhook", "langsmith", "langfuse")
    _TRACE_ID_PREFIXES = ("webhook_", "langsmith_", "langfuse_")

    @staticmethod
    def _item_source(item) -> str:
        data = item.get_data() if hasattr(item, "get_data") else {}
        if isinstance(data, dict):
            src = (data.get("metadata") or {}).get("source")
            if src:
                return str(src)
        return "instances"

    def _is_ingested_trace(self, instance_id: str, item) -> bool:
        if str(instance_id).startswith(self._TRACE_ID_PREFIXES):
            return True
        return self._item_source(item) in self._TRACE_SOURCES

    def _build_examples(self, ism, ids, include_annotations: bool):
        """Build Example objects from live instances, optionally with aggregated
        human annotations as reference_outputs."""
        get_user_annotations = usernames = None
        if include_annotations:
            from potato.flask_server import get_annotations_for_user_on, get_users
            from potato.eval_datasets.annotation_aggregation import aggregate_instance_annotations
            get_user_annotations = get_annotations_for_user_on
            usernames = list(get_users())

        examples = []
        for iid in ids:
            try:
                item = ism.get_item(iid)
            except KeyError:
                continue
            data = item.get_data()
            inputs = data if isinstance(data, dict) else {"text": data}
            meta = {"source": self._item_source(item)}
            reference = None
            if include_annotations:
                reference, agg_meta = aggregate_instance_annotations(
                    str(iid), usernames, get_user_annotations)
                meta["annotation_aggregation"] = agg_meta
            examples.append(Example(id=str(iid), inputs=inputs,
                                    reference_outputs=reference, metadata=meta))
        return examples

    def import_from_instances(self, dataset_name: str, instance_ids=None,
                              include_annotations: bool = False,
                              note: str = "") -> DatasetVersion:
        """Curate dataset examples from the live task's loaded instances.

        Each instance's raw data becomes an example's ``inputs`` (the instance id
        becomes the example id). With ``include_annotations`` the majority human
        annotation per scheme is aggregated into ``reference_outputs``; otherwise
        references are left unset (score against ``metadata['outputs']`` / a
        target, or add references later).
        """
        from potato.item_state_management import get_item_state_manager
        ism = get_item_state_manager()
        if ism is None:
            raise RuntimeError("No item state manager available")

        ids = instance_ids if instance_ids else ism.get_instance_ids()
        examples = self._build_examples(ism, ids, include_annotations)
        if not examples:
            raise ValueError("No matching instances to import")
        self.store.create_dataset(dataset_name)
        return self.store.add_examples(
            dataset_name, examples, note=note or f"import {len(examples)} instance(s)")

    def import_from_traces(self, dataset_name: str, source: Optional[str] = None,
                           include_annotations: bool = False,
                           note: str = "") -> DatasetVersion:
        """Curate examples from runtime-ingested traces only (webhook / langsmith
        / langfuse), optionally filtered to a single ``source``.
        """
        from potato.item_state_management import get_item_state_manager
        ism = get_item_state_manager()
        if ism is None:
            raise RuntimeError("No item state manager available")

        ids = []
        for iid in ism.get_instance_ids():
            try:
                item = ism.get_item(iid)
            except KeyError:
                continue
            if not self._is_ingested_trace(iid, item):
                continue
            if source and self._item_source(item) != source:
                continue
            ids.append(iid)

        examples = self._build_examples(ism, ids, include_annotations)
        if not examples:
            raise ValueError("No ingested traces to import"
                             + (f" for source '{source}'" if source else ""))
        self.store.create_dataset(dataset_name)
        return self.store.add_examples(
            dataset_name, examples, note=note or f"import {len(examples)} ingested trace(s)")


# ----- singleton -----

_manager: Optional[DatasetsManager] = None


def init_datasets_manager(config: Dict[str, Any]) -> DatasetsManager:
    global _manager
    _manager = DatasetsManager(config)
    return _manager


def get_datasets_manager() -> Optional[DatasetsManager]:
    return _manager


def clear_datasets_manager() -> None:
    global _manager
    _manager = None
