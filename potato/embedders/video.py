"""
Video embeddings by frame sampling.

A clip becomes a handful of evenly spaced frames, each embedded with the image
backend, mean-pooled into one vector. That is not a video model — it has no
sense of motion — but it puts clips of the same scene, subject and setting near
each other, which is what a corpus map is for, and it needs no new dependency
beyond the frame extraction Potato already does for tracking.

    embeddings:
      backend: video
      frames: 4            # per clip
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import List, Optional, Sequence, Tuple

from potato.embedders.base import EmbeddingBackend, probe, require
from potato.embedders.image import ImageEmbeddingBackend

logger = logging.getLogger(__name__)


def _evenly_spaced(paths: List[str], count: int) -> List[str]:
    """`count` frames spread across the clip, not the first `count` of them.

    Taking the head would describe the opening second of every video, which for
    anything with a title card is a map of title cards.
    """
    if not paths or count <= 0:
        return []
    if len(paths) <= count:
        return list(paths)
    step = len(paths) / float(count)
    return [paths[min(len(paths) - 1, int(i * step))] for i in range(count)]


class VideoEmbeddingBackend(EmbeddingBackend):
    name = "video"
    modality = "video"
    default_model = "clip-ViT-B-32"
    source_fields = ("video_url", "video", "video_path", "clip")
    extensions = (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.frames = max(1, int(self.options.get("frames", 4)))
        self._images = ImageEmbeddingBackend(
            model=self.model, cache_dir=self.cache_dir,
            media_root=self.media_root)
        self._cache = None

    def available(self) -> Tuple[bool, Optional[str]]:
        ok, reason = self._images.available()
        if not ok:
            return ok, reason
        from potato.media.video import ffmpeg_available
        if not ffmpeg_available():
            return False, ("Video embeddings need ffmpeg on PATH to sample "
                           "frames (brew install ffmpeg / apt install ffmpeg)")
        return True, None

    def _cache_store(self):
        if self._cache is None and self.cache_dir:
            from potato.vision_features import EmbeddingCache
            self._cache = EmbeddingCache(
                self.cache_dir, f"video-{self.frames}f-{self.model}")
        return self._cache

    def _frames_for(self, reference: str) -> List[str]:
        """Sample frames from one clip; [] when it cannot be read."""
        from potato.media.video import extract_frames

        source = reference
        if self.media_root and not str(reference).startswith(
                ("http://", "https://", "/")):
            source = os.path.join(self.media_root, reference)
        try:
            with tempfile.TemporaryDirectory(prefix="potato-vemb-") as tmp:
                # extract_frames works in fps, so take one per second (capped)
                # and then thin the result to an even spread across the clip.
                paths = extract_frames(source, tmp, fps=1.0,
                                       limit=max(self.frames * 8, self.frames))
                paths = _evenly_spaced(paths, self.frames)
                # Embedded before the directory disappears: the image backend
                # opens paths, and returning them would hand back dead files.
                return self._embed_frame_paths(paths)
        except Exception as exc:
            logger.debug("Could not sample %s: %s", reference, exc)
            return []

    def _embed_frame_paths(self, paths):
        if not paths:
            return []
        return self._images.embed(list(paths))

    def embed(self, references: Sequence[str]):
        numpy = require("numpy", "numpy", "Video embeddings")
        refs = list(references)
        self.failures = []
        if not refs:
            return numpy.zeros((0, 1))

        from potato.vision_features import fingerprint

        cache = self._cache_store()
        vectors: List = [None] * len(refs)
        for index, reference in enumerate(refs):
            key = fingerprint(f"{reference}#{self.frames}")
            cached = cache.get(key) if cache else None
            if cached is not None:
                vectors[index] = cached
                continue
            frame_vectors = self._frames_for(reference)
            if len(frame_vectors) == 0:
                self.failures.append(reference)
                continue
            pooled = numpy.asarray(frame_vectors, dtype=float).mean(axis=0)
            vectors[index] = pooled
            if cache:
                cache.put(key, pooled)

        width = next((len(v) for v in vectors if v is not None), 1)
        return numpy.vstack([v if v is not None else numpy.zeros(width)
                             for v in vectors])
