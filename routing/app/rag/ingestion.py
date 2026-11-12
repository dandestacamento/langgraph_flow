"""Document ingestion: Level 4 (RAG retrieval). Not yet wired into
`app/graph.py` - Level 1 agents answer from the LLM directly.

Will walk `knowledge_base/`, parse each Markdown chapter's YAML front
matter (topic/subtopic/chapter_id/document_id/version) plus body, and hand
documents off to `chunking.py` before embedding and indexing.
"""

from __future__ import annotations


def load_knowledge_base_documents():
    raise NotImplementedError(
        "RAG ingestion is implemented starting at Level 4 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md)."
    )
