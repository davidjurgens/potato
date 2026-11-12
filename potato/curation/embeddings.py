"""
Pluggable, lazy text embedder.

Embedding backends, in priority order:
  1. an injected ``embed_fn`` (tests / custom endpoints),
  2. ``sentence_transformers`` (imported LAZILY on first use — never at import,
     per the boot-weight constraint in project memory).

``is_available()`` probes for ``sentence_transformers`` without importing it, so
the curation feature degrades gracefully when the ML stack isn't installed.
"""

from __future__ import annotations

from importlib.util import find_spec
from typing import Callable, List, Optional


def is_available() -> bool:
    return find_spec("sentence_transformers") is not None


class Embedder:
    def __init__(self, embed_fn: Optional[Callable[[str], List[float]]] = None,
                 model_name: str = "all-MiniLM-L6-v2"):
        self._embed_fn = embed_fn
        self.model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, text: str) -> List[float]:
        if self._embed_fn is not None:
            return list(self._embed_fn(text))
        return self._load_model().encode(text).tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if self._embed_fn is not None:
            return [list(self._embed_fn(t)) for t in texts]
        return [v.tolist() for v in self._load_model().encode(list(texts))]
