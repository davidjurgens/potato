"""
Guidelines + codebook RAG substrate.

A single embedding/vector layer shared by guideline retrieval, codebook-unit
retrieval (the "which parts of the codebook are relevant to this instance"
side feature), and ICL example retrieval. See:

- embedding_endpoint: pluggable embedding providers (Ollama / sentence-
  transformers / OpenAI), no hardcoded provider.
- store: project-scoped SQLite vector store + brute-force cosine.
- retriever: top-k guideline chunks and ranked codebook units.
"""

from .embedding_endpoint import (
    BaseEmbeddingEndpoint,
    EmbeddingEndpointFactory,
    EmbeddingError,
)

__all__ = [
    "BaseEmbeddingEndpoint",
    "EmbeddingEndpointFactory",
    "EmbeddingError",
]
