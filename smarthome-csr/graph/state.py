"""Shared state definition for the SmartHome CSR LangGraph workflow.

A single TypedDict is threaded through every node. Agent nodes only ever
write into `agent_responses` and append to `execution_log`; they never need
to know about each other. This keeps the graph easy to extend with parallel
agents and a response-aggregation step (Phase 3) without reworking the
state shape introduced here in Phase 1.

Phase 2 adds conversation memory: `graph.workflow.build_graph` can be given
a LangGraph checkpointer, and callers invoke it with a stable `thread_id`
(one per customer conversation). `order_id` and `conversation_history` have
no "overwrite" semantics forced on every turn - a node only changes a field
by including that key in its returned dict, so as long as `extract_context`
(see graph/workflow.py) only returns `order_id` when it actually finds one
in the latest message, a value learned on an earlier turn stays in the
checkpointed state for the rest of the conversation (use case 8: "I already
gave you my order number").
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

    # Per-turn history for this conversation (Phase 2 conversation memory),
    # appended to by the aggregator node. Also lets the Technical Agent
    # detect repeat visits to the same fault and escalate (troubleshooting
    # loop across turns rather than within a single graph run).
    conversation_history: Annotated[list[dict], operator.add]

    # Execution trace for the Graph Execution Inspector (Phase 4)
    execution_log: Annotated[list[dict], operator.add]
