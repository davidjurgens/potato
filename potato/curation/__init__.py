"""
Semantic curation — find *what to review* by similarity, not just rules.

An embedding index over traces/instances powers similarity search ("find traces
like this failure") and **dynamic slices** (saved semantic + metadata filters that
auto-include new matching traces, and can be curated into datasets). Embeddings
are lazy (no ML import at load) and pluggable.
"""

from potato.curation.config import CurationConfig
from potato.curation.embeddings import Embedder, is_available
from potato.curation.index import EmbeddingIndex, cosine
from potato.curation.slices import Slice, SliceStore, resolve_slice
from potato.curation.manager import (
    CurationManager,
    init_curation_manager,
    get_curation_manager,
    clear_curation_manager,
)

__all__ = [
    "CurationConfig",
    "Embedder",
    "is_available",
    "EmbeddingIndex",
    "cosine",
    "Slice",
    "SliceStore",
    "resolve_slice",
    "CurationManager",
    "init_curation_manager",
    "get_curation_manager",
    "clear_curation_manager",
]
