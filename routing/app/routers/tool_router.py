"""Tool Router: Level 8 (tool selection and execution). Not yet wired into
`app/graph.py` - Level 1 agents answer directly from the LLM and do not
yet call any tools.

Will select which tool(s) in `app/tools` (document search, calculator,
SQL query, metadata lookup) are needed to answer a question, and with
what arguments, once the graph reaches multi-chapter retrieval and
structured lookups (e.g. "what's the APR on a WM-500's financing plan"
needing both a document search and a calculator call).
"""

from __future__ import annotations

from app.state import RoutingState


def select_tools(state: RoutingState) -> dict:
    raise NotImplementedError(
        "Tool routing is implemented starting at Level 8 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md)."
    )
