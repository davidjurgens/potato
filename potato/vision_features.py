"""
Image embeddings for active learning, diversity, and corpus mapping.

WHY THIS IS SO SMALL
--------------------
Potato's active learning is genuinely mature — uncertainty, diversity, BADGE,
BALD, background training, persistence — and entirely text-bound through one
call: ``item.get_text()``. Every ``QueryStrategy`` already takes a *vectorizer*
and calls ``vectorizer.transform(items)``.

So making all of it work on images needs one new vectorizer, not a parallel
pipeline. Uncertainty, diversity, BADGE, BALD and hybrid ranking are unchanged
code paths afterwards. **CVAT has no active learning at all**, so the target is
not "match a competitor's model stage" — it is to be the only self-hostable
annotation tool with real active learning over images.

WHY THE CACHE IS NOT OPTIONAL
-----------------------------
Embedding is the expensive step and the corpus does not change. Active learning
re-ranks after every batch of annotations, so an uncached embedder would
re-encode the entire unlabeled pool on every re-rank — minutes of GPU-less
compute repeated for no reason. The cache is keyed on file content, so an image
that is renamed or moved is not re-encoded, and one that is *edited* is.

OPTIONAL DEPENDENCY, ALWAYS
---------------------------
``sentence-transformers`` and Pillow are optional. Their absence produces a
clear message naming the install command, never a silent fallback to random
ordering — which would look like active learning while being nothing of the
kind.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: CLIP through sentence-transformers. Chosen over DINOv2 because the same
#: model embeds text into the same space, which makes cross-modal checks
#: ("is this crop far from its own class name?") free once it is loaded.
DEFAULT_IMAGE_MODEL = "clip-ViT-B-32"

#: Where embeddings are cached, relative to the project's output directory.
CACHE_DIRNAME = ".embeddings"

#: Bytes read when fingerprinting a local file. Hashing a whole corpus of
#: multi-megabyte images costs more than the embedding it is meant to save;
#: the head, the tail and the size together are enough to notice an edit.
FINGERPRINT_BYTES = 65536


class MissingDependency(RuntimeError):
    """Raised with the exact install command, never swallowed."""


def _require(module: str, package: str, purpose: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise MissingDependency(
            f"{purpose} needs {package}, which is not installed. "
            f"Install it with:  pip install {package}") from exc


def fingerprint(reference: str) -> str:
    """
    A stable cache key for one image.

    Content-derived for local files, so renaming or moving an image does not
    force a re-encode and editing it does. Remote URLs are keyed by the URL
    itself: fetching every image to hash it would defeat the cache's purpose.
    """
    path = Path(reference)
    try:
        if path.is_file():
            size = path.stat().st_size
            digest = hashlib.sha256()
            digest.update(str(size).encode())
            with open(path, "rb") as handle:
                digest.update(handle.read(FINGERPRINT_BYTES))
                if size > FINGERPRINT_BYTES * 2:
                    handle.seek(-FINGERPRINT_BYTES, os.SEEK_END)
                    digest.update(handle.read(FINGERPRINT_BYTES))
            return digest.hexdigest()[:32]
    except OSError:
        pass
    return hashlib.sha256(str(reference).encode()).hexdigest()[:32]


class EmbeddingCache:
    """
    An on-disk store of image embeddings, keyed by content fingerprint.

    One ``.npy`` per image rather than a single archive: a partially written
    archive loses every embedding in it, while a partially written single file
    loses one and is simply re-encoded.
    """

    def __init__(self, root: str, model_name: str = DEFAULT_IMAGE_MODEL):
        # Absolute, so the cache does not move with the process's cwd.
        self.root = (Path(root) / CACHE_DIRNAME / _safe(model_name)).resolve()

    def path_for(self, key: str) -> Path:
        return self.root / f"{key}.npy"

    def get(self, key: str):
        path = self.path_for(key)
        if not path.exists():
            return None
        try:
            numpy = _require("numpy", "numpy", "Embedding caching")
            return numpy.load(path)
        except Exception as exc:
            logger.debug("Dropping unreadable cache entry %s: %s", path, exc)
            try:
                path.unlink()
            except OSError:
                pass
            return None

    def put(self, key: str, vector) -> None:
        numpy = _require("numpy", "numpy", "Embedding caching")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(key)
        # Write-then-rename: a process killed mid-write otherwise leaves a
        # truncated .npy that loads as garbage rather than failing.
        partial = target.with_suffix(".part.npy")
        try:
            # Written through a HANDLE, not a path: numpy.save appends ".npy"
            # to any filename that lacks it, so saving to "k.npy.part" produced
            # "k.npy.part.npy" and the rename then failed silently -- every
            # put() looked like it worked and every get() missed.
            with open(partial, "wb") as handle:
                numpy.save(handle, vector)
            partial.replace(target)
        except OSError as exc:
            logger.debug("Could not cache embedding %s: %s", key, exc)
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass

    def clear(self) -> int:
        if not self.root.exists():
            return 0
        removed = 0
        for path in self.root.glob("*.npy"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(text))


class ImageEmbeddingVectorizer:
    """
    sklearn-compatible image embedder, the mirror of
    ``SentenceTransformerVectorizer``.

    ``transform`` takes image *references* — local paths or URLs — and returns
    one dense vector per image. Because the interface matches, every existing
    ``QueryStrategy`` (uncertainty, diversity, BADGE, BALD, hybrid) works on
    images without modification.

    Args:
        model_name: any CLIP-family model sentence-transformers can load
        cache_dir: project output directory; embeddings land in ``.embeddings/``
        image_root: prefix for relative references
    """

    def __init__(self, model_name: str = DEFAULT_IMAGE_MODEL,
                 cache_dir: Optional[str] = None,
                 image_root: Optional[str] = None):
        self.model_name = model_name
        self.image_root = image_root
        self._model = None
        self._cache = EmbeddingCache(cache_dir, model_name) if cache_dir else None
        #: Set when references could not be loaded, so callers can report a
        #: partial ranking honestly instead of presenting it as complete.
        self.failures: List[str] = []

    # -- sklearn surface ------------------------------------------------

    def fit(self, X=None, y=None):
        """Load the model. Lazy, exactly like the text vectorizer."""
        _require("sentence_transformers", "sentence-transformers",
                 "Image embeddings")
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self.model_name)
        return self

    def transform(self, X: Sequence[str]):
        numpy = _require("numpy", "numpy", "Image embeddings")
        references = list(X)
        self.failures = []
        if not references:
            return numpy.zeros((0, 1))

        vectors: List[Any] = [None] * len(references)
        pending: List[int] = []

        if self._cache is not None:
            for index, reference in enumerate(references):
                cached = self._cache.get(fingerprint(reference))
                if cached is not None:
                    vectors[index] = cached
                else:
                    pending.append(index)
        else:
            pending = list(range(len(references)))

        if pending:
            if self._model is None:
                self.fit()
            images, loaded_indices = [], []
            for index in pending:
                image = self._load(references[index])
                if image is None:
                    self.failures.append(references[index])
                    continue
                images.append(image)
                loaded_indices.append(index)

            if images:
                encoded = self._model.encode(images, show_progress_bar=False)
                for position, index in enumerate(loaded_indices):
                    vectors[index] = encoded[position]
                    if self._cache is not None:
                        self._cache.put(fingerprint(references[index]),
                                        encoded[position])

        width = next((len(v) for v in vectors if v is not None), 1)
        # An unreadable image becomes a zero vector rather than being dropped:
        # the caller indexes results against the input list, and silently
        # returning fewer rows would misalign every ranking after the gap.
        return numpy.vstack([
            v if v is not None else numpy.zeros(width) for v in vectors
        ])

    def fit_transform(self, X, y=None):
        self.fit(X, y)
        return self.transform(X)

    # -- loading --------------------------------------------------------

    def _load(self, reference: str):
        """Open one image reference, or None if it cannot be read."""
        _require("PIL", "Pillow", "Image embeddings")
        from PIL import Image

        candidate = str(reference)
        try:
            if candidate.startswith(("http://", "https://")):
                # Deliberately NOT fetched. Active learning ranks a whole
                # unlabeled pool, so this would fire thousands of requests from
                # a background thread. Serve images locally, or point
                # image_root at where they live.
                logger.debug("Skipping remote image %s", candidate)
                return None

            # Potato stores image references as URL paths -- "/media/a.png" --
            # which are absolute as URLs but NOT as filesystem paths. Testing
            # `is_absolute()` and skipping image_root on a leading slash would
            # therefore fail to resolve on essentially every real project.
            # Try the reference as given, then relative to image_root.
            path = Path(candidate)
            if not path.is_file() and self.image_root:
                path = Path(self.image_root) / candidate.lstrip("/")
            if not path.is_file():
                return None
            with Image.open(path) as image:
                return image.convert("RGB")
        except Exception as exc:
            logger.debug("Could not load %s: %s", reference, exc)
            return None

    # -- cross-modal ----------------------------------------------------

    def embed_text(self, phrases: Sequence[str]):
        """
        Embed text into the SAME space as the images.

        Free once CLIP is loaded, and it is what makes label-quality checks
        possible: an instance whose crop is far from its own class name is a
        candidate mislabel. Raises on a model that has no text tower rather
        than returning vectors from a different space, which would produce
        confident nonsense.
        """
        numpy = _require("numpy", "numpy", "Image embeddings")
        if self._model is None:
            self.fit()
        vectors = self._model.encode(list(phrases), show_progress_bar=False)
        return numpy.asarray(vectors)


def is_available() -> bool:
    """Whether image embedding can run at all, without importing the heavy bits."""
    import importlib.util

    return all(importlib.util.find_spec(name) is not None
               for name in ("sentence_transformers", "PIL", "numpy"))


def unavailable_reason() -> str:
    """A message naming what to install. Empty when everything is present."""
    import importlib.util

    missing = [
        package for module, package in (
            ("sentence_transformers", "sentence-transformers"),
            ("PIL", "Pillow"),
            ("numpy", "numpy"),
        )
        if importlib.util.find_spec(module) is None
    ]
    if not missing:
        return ""
    return (f"Image active learning needs {', '.join(missing)}. "
            f"Install with:  pip install {' '.join(missing)}")
