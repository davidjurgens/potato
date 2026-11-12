"""Corpus map package: ingest-time embed/cluster/project/KNN + annotator map.

Import-light at module scope (numpy only); the ML stack is imported lazily inside
CorpusMapManager.build().
"""

from .manager import (
    CorpusMapManager,
    init_corpus_map_manager,
    get_corpus_map_manager,
    clear_corpus_map_manager,
)

__all__ = [
    "CorpusMapManager",
    "init_corpus_map_manager",
    "get_corpus_map_manager",
    "clear_corpus_map_manager",
]
