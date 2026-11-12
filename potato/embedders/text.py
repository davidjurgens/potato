"""Sentence-transformers text embeddings — today's behaviour, behind the protocol."""

from __future__ import annotations

import logging
from typing import Optional, Sequence, Tuple

from potato.embedders.base import EmbeddingBackend, probe, require

logger = logging.getLogger(__name__)

DEFAULT_TEXT_MODEL = "all-MiniLM-L6-v2"


class TextEmbeddingBackend(EmbeddingBackend):
    """The default. Output matches what DiversityManager produced before."""

    name = "text"
    modality = "text"
    default_model = DEFAULT_TEXT_MODEL
    source_fields = ("text", "content", "message", "title", "caption",
                     "description", "transcript")
    extensions = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = None

    def available(self) -> Tuple[bool, Optional[str]]:
        return probe("sentence_transformers", "sentence-transformers",
                     "Text embeddings")

    def _load(self):
        if self._model is None:
            require("sentence_transformers", "sentence-transformers",
                    "Text embeddings")
            from sentence_transformers import SentenceTransformer
            logger.info("embedders: loading text model %s", self.model)
            self._model = SentenceTransformer(self.model)
        return self._model

    def embed(self, references: Sequence[str]):
        numpy = require("numpy", "numpy", "Text embeddings")
        texts = [r if isinstance(r, str) else "" for r in references]
        if not texts:
            return numpy.zeros((0, 1))
        self.failures = [t for t in texts if not t.strip()]
        return self._load().encode(texts, show_progress_bar=False)
