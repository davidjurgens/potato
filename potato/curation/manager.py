"""
Curation manager (singleton).

Owns the embedder, the embedding index, and the slice store. Provides
embed-on-ingest, similarity search (by text or by an anchor instance), slice
resolution, and a one-shot index build over the current ItemStateManager items.
Initialized in ``configure_app()`` when a ``curation:`` block is enabled.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from potato.curation.config import CurationConfig
from potato.curation.embeddings import Embedder
from potato.curation.index import EmbeddingIndex
from potato.curation.slices import Slice, SliceStore, resolve_slice

logger = logging.getLogger("potato.curation")


class CurationManager:
    def __init__(self, config: Dict[str, Any], embed_fn=None):
        self.config = config or {}
        self.settings = CurationConfig.from_config(config)
        self.embedder = Embedder(embed_fn=embed_fn, model_name=self.settings.model_name)
        self.index = EmbeddingIndex()
        base = self._resolve_base_dir(config)
        self.slices = SliceStore(base)
        self.embed_on_ingest = self.settings.embed_on_ingest
        logger.info("CurationManager initialized (model=%s, embed_on_ingest=%s)",
                    self.settings.model_name, self.embed_on_ingest)

    @staticmethod
    def _resolve_base_dir(config: Dict[str, Any]) -> str:
        base = os.path.join((config or {}).get("output_annotation_dir") or ".", "curation")
        os.makedirs(base, exist_ok=True)
        return base

    # ----- indexing -----

    def _item_text(self, instance_id: str) -> str:
        from potato.item_state_management import get_item_state_manager
        ism = get_item_state_manager()
        if ism is None:
            return ""
        try:
            item = ism.get_item(instance_id)
        except KeyError:
            return ""
        if self.settings.text_key:
            data = item.get_data()
            if isinstance(data, dict) and self.settings.text_key in data:
                return str(data[self.settings.text_key])
        return item.get_text() if item else ""

    def embed_instance(self, instance_id: str, text: Optional[str] = None) -> None:
        text = text if text is not None else self._item_text(instance_id)
        if not text:
            return
        self.index.add(instance_id, self.embedder.embed(text))

    def build_index(self, max_items: Optional[int] = None) -> int:
        """Embed all current ItemStateManager items. Returns count indexed."""
        from potato.item_state_management import get_item_state_manager
        ism = get_item_state_manager()
        if ism is None:
            return 0
        ids = ism.get_instance_ids()
        if max_items:
            ids = ids[:max_items]
        count = 0
        for iid in ids:
            text = self._item_text(iid)
            if text:
                self.index.add(iid, self.embedder.embed(text))
                count += 1
        return count

    # ----- search -----

    def search(self, query: str = "", anchor_id: str = "", top_k: int = 10,
               threshold: float = 0.0) -> List[Tuple[str, float]]:
        if anchor_id:
            vec = self.index.get(anchor_id)
            if vec is None:
                return []
            return self.index.search(vec, top_k=top_k, threshold=threshold,
                                     exclude={anchor_id})
        if query:
            return self.index.search(self.embedder.embed(query), top_k=top_k,
                                     threshold=threshold)
        return []

    # ----- slices -----

    def _metadata_for(self, instance_id: str) -> Dict[str, Any]:
        from potato.item_state_management import get_item_state_manager
        ism = get_item_state_manager()
        if ism is None:
            return {}
        try:
            item = ism.get_item(instance_id)
        except KeyError:
            return {}
        data = item.get_data() if item else {}
        return data if isinstance(data, dict) else {}

    def resolve(self, slc: Slice) -> List[str]:
        return resolve_slice(slc, self.index, self.embedder, self._metadata_for)

    def discover_failure_modes(self, k: int = 6, instance_ids: Optional[List[str]] = None,
                               use_llm: bool = True, max_examples: int = 4):
        """Cluster embedded traces into candidate failure modes (E1). Returns a list
        of ``DiscoveredCluster`` (largest cluster first), each with representative
        examples and — when an LLM judge is configured — a suggested axial code that
        a human confirms or edits."""
        from potato.curation.discovery import discover_failure_modes
        llm = None
        if use_llm:
            try:
                from potato.ai.judge import JudgeService
                llm = JudgeService(self.config)._get_endpoint()
            except Exception as e:  # pragma: no cover - provider-dependent
                logger.warning("discovery: no judge endpoint (%s); clustering only", e)
        return discover_failure_modes(
            self.index, self._item_text, k=k, llm=llm,
            max_examples=max_examples, instance_ids=instance_ids)


# ----- singleton -----

_manager: Optional[CurationManager] = None


def init_curation_manager(config: Dict[str, Any], embed_fn=None) -> CurationManager:
    global _manager
    _manager = CurationManager(config, embed_fn=embed_fn)
    return _manager


def get_curation_manager() -> Optional[CurationManager]:
    return _manager


def clear_curation_manager() -> None:
    global _manager
    _manager = None
