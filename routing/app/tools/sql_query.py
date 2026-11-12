"""SQL query tool: Level 8 (tool selection and execution). Not yet wired
in - will query the structured CSV/JSON reference data under
`knowledge_base/` (e.g. `appliances/washing_machines/specifications.csv`)
via an in-memory SQL engine (e.g. DuckDB) for exact-value lookups that
Markdown-chapter RAG retrieval handles poorly (specific price/capacity
rows across many models).
"""

from __future__ import annotations


def run_sql_query(query: str):
    raise NotImplementedError(
        "The SQL query tool is implemented starting at Level 8 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md)."
    )
