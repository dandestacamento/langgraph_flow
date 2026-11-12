"""Metadata lookup tool: Level 8 (tool selection and execution). Not yet
wired in - will answer questions about the knowledge base's own structure
(which chapters exist for a subtopic, a document's version number) using
the front-matter metadata written by `scripts/generate_knowledge_base.py`,
without needing a full vector search.
"""

from __future__ import annotations


def lookup_metadata(topic: str, subtopic: str | None = None):
    raise NotImplementedError(
        "The metadata lookup tool is implemented starting at Level 8 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md)."
    )
