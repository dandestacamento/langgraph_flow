"""Document search tool: deliberately left unimplemented for Level 8.

The architecture docs list `document_search` as a 4th explicit tool the
Tool Router could select, distinct from the always-on retrieval a RAG
agent performs automatically. In practice, every Level 8 test question
is answerable via `calculator`, `sql_query`, or `metadata_lookup`
precisely *because* `app.rag.retrieval.retrieve_evidence` already runs
automatically for every question regardless of tool selection (see
`app/graph.py`) - an explicit document-search tool call would be
redundant with that, not a new capability, for any scenario this
project's knowledge base actually needs. Left as a stub rather than
wired in with no genuine test case behind it; see the Level 8 README
section for this design decision.
"""

from __future__ import annotations


def search_documents(query: str, topic: str | None = None):
    raise NotImplementedError(
        "document_search is deliberately left unimplemented - see this module's "
        "docstring and the Level 8 section of README.md for why."
    )
