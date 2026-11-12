"""
CLIP image embeddings.

Wraps ``potato.vision_features.ImageEmbeddingVectorizer`` rather than
re-implementing it: that class already handles the disk cache, the
load-failure bookkeeping and the zero-row alignment that keeps a caller's
indexes valid. Two implementations of the same thing is how the client and the
exporters ended up disagreeing about mask geometry.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence, Tuple

from potato.embedders.base import EmbeddingBackend, probe

logger = logging.getLogger(__name__)


class ImageEmbeddingBackend(EmbeddingBackend):
    """CLIP through sentence-transformers, image references in, vectors out."""

    name = "image"
    modality = "image"
    #: Same default as the active-learning vectorizer: CLIP rather than DINOv2,
    #: because a shared image/text space makes cross-modal checks free later.
    default_model = "clip-ViT-B-32"
    source_fields = ("image_url", "image", "image_path", "img", "photo")
    extensions = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
                  ".tif", ".tiff", ".avif", ".heic", ".heif")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._vectorizer = None

    def available(self) -> Tuple[bool, Optional[str]]:
        ok, reason = probe("sentence_transformers", "sentence-transformers",
                           "Image embeddings")
        if not ok:
            return ok, reason
        return probe("PIL", "pillow", "Image embeddings")

    def _load(self):
        if self._vectorizer is None:
            from potato.vision_features import ImageEmbeddingVectorizer
            logger.info("embedders: loading image model %s", self.model)
            self._vectorizer = ImageEmbeddingVectorizer(
                model_name=self.model,
                cache_dir=self.cache_dir,
                image_root=self.media_root,
            )
        return self._vectorizer

    def embed(self, references: Sequence[str]):
        vectorizer = self._load()
        vectors = vectorizer.transform(list(references))
        # Surface unreadable images so the map can say "412 of 500 points".
        self.failures = list(vectorizer.failures)
        if self.failures:
            logger.warning("embedders: %d image reference(s) could not be read",
                           len(self.failures))
        return vectors

    def embed_text(self, phrases: Sequence[str]):
        """Text in the same space — for cross-modal checks (crop vs class name)."""
        return self._load().embed_text(list(phrases))
