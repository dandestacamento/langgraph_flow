"""Markdown-aware chunking: Level 4 (RAG retrieval). Not yet wired in.

Will split each chapter into passages along Markdown heading boundaries,
preserving topic/subtopic/chapter_id/document_id metadata on every chunk
so retrieved passages can be traced back to their exact source location.
"""

from __future__ import annotations


def chunk_markdown_document(text: str, metadata: dict):
    raise NotImplementedError(
        "RAG chunking is implemented starting at Level 4 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md)."
    )
