"""Vector retrieval: Level 4 (RAG retrieval). Not yet wired in.

Will query the Chroma collection built by `scripts/build_index.py`,
optionally filtered by topic/subtopic metadata narrowed down by the
Subtopic Router (Level 2) and Chapter Selector (Level 3), and return
passages with their source topic/subtopic/chapter_id/document_id intact
for citation.
"""

from __future__ import annotations


def retrieve(query: str, top_k: int = 5, metadata_filter: dict | None = None):
    raise NotImplementedError(
        "Vector retrieval is implemented starting at Level 4 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md)."
    )
