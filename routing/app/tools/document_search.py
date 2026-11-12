"""Document search tool: Level 8 (tool selection and execution). Not yet
wired in - will call `app.rag.retrieval.retrieve` as an explicit tool the
Tool Router can select, distinct from the always-on retrieval a RAG agent
performs automatically.
"""

from __future__ import annotations


def search_documents(query: str, topic: str | None = None):
    raise NotImplementedError(
        "Tool-based document search is implemented starting at Level 8 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md)."
    )
