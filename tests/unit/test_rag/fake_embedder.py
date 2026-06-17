"""Deterministic, offline embedding endpoint for RAG tests.

Hashed bag-of-words into a small fixed-dim vector: texts that share words
get high cosine similarity, so retrieval-quality assertions are meaningful
without any model download or server. Shared across the RAG test modules.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, List

import numpy as np

from potato.rag.embedding_endpoint import BaseEmbeddingEndpoint

_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbeddingEndpoint(BaseEmbeddingEndpoint):
    """Hashing bag-of-words embedder. `provider`/`model` are configurable so
    tests can simulate a model switch (Amendment 1)."""

    provider = "fake"

    def __init__(self, model: str = "fake-32", dim: int = 32,
                 provider: str = "fake", salt: str = "", **opts: Any):
        super().__init__(model, **opts)
        self.provider = provider
        self._fixed_dim = dim
        self._salt = salt

    def _embed(self, texts: List[str]) -> List[Any]:
        out = []
        for t in texts:
            v = np.zeros(self._fixed_dim, dtype=np.float32)
            for tok in _WORD.findall(str(t).lower()):
                h = int(hashlib.md5((self._salt + tok).encode()).hexdigest(), 16)
                v[h % self._fixed_dim] += 1.0
            out.append(v)
        return out
