"""Embeddings: Level 4 (RAG retrieval). Not yet wired in.

Will embed chunks with OpenAI's `text-embedding-3-small`
(see `app.config.EMBEDDING_MODEL`) for indexing into Chroma.
"""

from __future__ import annotations


def embed_texts(texts: list[str]) -> list[list[float]]:
    raise NotImplementedError(
        "Embeddings are implemented starting at Level 4 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md)."
    )
