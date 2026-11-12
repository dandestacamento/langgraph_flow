"""Vector index build: Level 4 (RAG retrieval). Not yet implemented -
will run `app.rag.ingestion` + `app.rag.chunking` + `app.rag.embeddings`
over every chapter in `knowledge_base/` and persist the result to a local
Chroma collection under `routing/.chroma/`.

Usage (once implemented):
    python scripts/build_index.py
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError(
        "Index building is implemented starting at Level 4 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md)."
    )


if __name__ == "__main__":
    main()
