"""Shared state definition for the SmartHome CSR LangGraph workflow.

A single TypedDict is threaded through every node. Agent nodes only ever
write into `agent_responses` and append to `execution_log`; they never need
to know about each other. This keeps the graph easy to extend with parallel
agents and a response-aggregation step (Phase 3) without reworking the
state shape introduced here in Phase 1.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

AgentName = Literal["product", "technical", "warranty", "orders", "returns"]


def merge_dicts(left: dict, right: dict) -> dict:
    """Reducer that merges two dicts so parallel agent branches can each
    write their own key into `agent_responses` without clobbering each other."""
    return {**left, **right}


class RouterDecision(TypedDict):
    intents: list[AgentName]
    confidence: float
    reasoning: str


class CSRState(TypedDict):
    # Input
    customer_message: str
    order_id: str | None

    # Router output
    router_decision: RouterDecision | None
    selected_agents: list[AgentName]

    # Agent outputs, merged via reducer so multiple agents can run in parallel
    agent_responses: Annotated[dict[str, str], merge_dicts]

    # Final aggregated response shown to the CSR
    final_response: str

    # Execution trace for the Graph Execution Inspector (Phase 4)
    execution_log: Annotated[list[dict], operator.add]
