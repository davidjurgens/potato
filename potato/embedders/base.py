"""
The embedding backend contract.

One project-wide embedder feeds every consumer that needs vectors — the corpus
map, diversity ordering, near-duplicate detection, cluster-based gold seeding.
Before this existed each consumer reached for sentence-transformers directly
over ``item.get_text()``, and ``get_text()`` returns the *first string value* of
an item when there is no text key. On a vision project that is the instance id,
so the corpus map was plotting a UMAP of ids and saying nothing about it.

A backend answers three questions:

* can I run here (is my dependency installed, is my model reachable)?
* which field of an item do I read?
* given those references, what are the vectors?

Everything a backend needs to be honest about is on ``EmbeddingSpec``, which is
returned to the admin UI: an embedder that fell back, or refused, says so in the
place where its output would otherwise be shown.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingSpec:
    """What the resolver settled on, and why. Surfaced in the admin UI."""

    backend: str
    modality: str
    model: str
    source_field: Optional[str] = None
    #: Set when the backend cannot run. The UI shows this instead of a plot.
    unavailable_reason: Optional[str] = None
    #: How the backend/field was chosen ("configured", "detected: image_url").
    chosen_because: str = ""
    #: Fields that were also candidates, so a surprising choice is explicable.
    alternatives: List[str] = dataclass_field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "modality": self.modality,
            "model": self.model,
            "source_field": self.source_field,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "chosen_because": self.chosen_because,
            "alternatives": list(self.alternatives),
        }


class MissingDependency(RuntimeError):
    """A backend's optional dependency is not installed."""


class EmbeddingBackend(ABC):
    """Turns item references into vectors.

    Subclasses declare what they can read so the resolver can detect a
    project's modality without importing anything heavy: ``source_fields`` are
    field-name hints and ``extensions`` are the file suffixes that mark a value
    as this modality.
    """

    #: Registry key, and what an admin writes in ``embeddings.backend``.
    name: str = ""
    #: text | image | audio | video
    modality: str = ""
    #: Used when the config names no model.
    default_model: str = ""
    #: Item field names this backend reads, best first.
    source_fields: Tuple[str, ...] = ()
    #: File extensions that identify this modality, lowercase with the dot.
    extensions: Tuple[str, ...] = ()

    def __init__(self, model: Optional[str] = None,
                 cache_dir: Optional[str] = None,
                 media_root: Optional[str] = None,
                 options: Optional[Dict[str, Any]] = None):
        self.model = model or self.default_model
        self.cache_dir = cache_dir
        self.media_root = media_root
        self.options = options or {}
        #: References that could not be read. Callers report partial results
        #: rather than presenting a gappy map as complete.
        self.failures: List[str] = []

    # -- capability ------------------------------------------------------

    def available(self) -> Tuple[bool, Optional[str]]:
        """(ok, reason). Must not import the model — only probe for it."""
        return True, None

    # -- work ------------------------------------------------------------

    @abstractmethod
    def embed(self, references: Sequence[str]):
        """Vectors for these references, one row each, in order.

        An unreadable reference becomes a zero row rather than a missing one:
        callers index results against the input list, and dropping a row
        silently misaligns everything after it.
        """

    # -- description -----------------------------------------------------

    def spec(self, source_field: Optional[str] = None,
             chosen_because: str = "") -> EmbeddingSpec:
        ok, reason = self.available()
        return EmbeddingSpec(
            backend=self.name,
            modality=self.modality,
            model=self.model,
            source_field=source_field,
            unavailable_reason=None if ok else reason,
            chosen_because=chosen_because,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} model={self.model!r}>"


def require(module: str, package: str, purpose: str):
    """Import an optional dependency or explain what to install."""
    try:
        return __import__(module)
    except ImportError as exc:
        raise MissingDependency(
            f"{purpose} needs the '{package}' package. "
            f"Install it with: pip install {package}"
        ) from exc


def probe(module: str, package: str, purpose: str) -> Tuple[bool, Optional[str]]:
    """available()-shaped check that does not construct anything."""
    import importlib.util
    if importlib.util.find_spec(module) is None:
        return False, (f"{purpose} needs the '{package}' package "
                       f"(pip install {package})")
    return True, None
