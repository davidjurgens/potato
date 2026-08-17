"""
One project-wide embedder, chosen by the admin or detected from the items.

Consumers (corpus map, diversity ordering, near-duplicate detection) ask for
vectors and get told, alongside them, exactly what produced them:

    from potato.embedders import resolve

    embedder = resolve(config, samples=[item.get_data() for item in items[:50]],
                       cache_dir=output_dir)
    if not embedder.available:
        show(embedder.spec.unavailable_reason)
    else:
        vectors = embedder.embed_items({item.get_id(): item.get_data() ...})

Importing this package pulls in no model libraries: backends are registered by
module path and imported on first use.
"""

from potato.embedders.base import (
    EmbeddingBackend,
    EmbeddingSpec,
    MissingDependency,
)
from potato.embedders.registry import (
    EmbeddingsConfig,
    ResolvedEmbedder,
    backend_names,
    detect,
    get_backend_class,
    parse_config,
    register,
    register_lazy,
    resolve,
    unregister,
)

__all__ = [
    "EmbeddingBackend",
    "EmbeddingSpec",
    "EmbeddingsConfig",
    "MissingDependency",
    "ResolvedEmbedder",
    "backend_names",
    "detect",
    "get_backend_class",
    "parse_config",
    "register",
    "register_lazy",
    "resolve",
    "unregister",
]
