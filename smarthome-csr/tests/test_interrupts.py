"""Human-in-the-loop interrupt/resume tests.

Phase 3 wires the Returns Agent to an Approval Gate: when a refund/
replacement exceeds data/policies.json's `requires_human_approval_above_aud`
threshold, `graph.workflow.approval_gate` pauses the graph with LangGraph's
`interrupt()`. These tests invoke the real router + Returns agent (hence
requiring OPENAI_API_KEY), then resume the paused thread with a CSR
decision via `Command(resume=...)`.
"""

from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph.workflow import build_graph

requires_openai_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"
)

# DISH-001 (Bosch dishwasher) is $1,349.00 AUD, well above the $100 AUD
# approval threshold in data/policies.json, so this always requires sign-off.
REFUND_MESSAGE = "I want a refund for my faulty dishwasher. My order is ORD-1098."


@requires_openai_key
def test_returns_request_triggers_approval_interrupt():
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test-approval-interrupt"}}

    result = graph.invoke({"customer_message": REFUND_MESSAGE}, config=config)

    assert "__interrupt__" in result, "Expected the graph to pause for CSR approval"
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload["agent"] == "returns"
    assert interrupt_payload["order_id"] == "ORD-1098"
    assert interrupt_payload["amount"] == pytest.approx(1349.00)


@requires_openai_key
def test_approval_gate_resumes_when_approved():
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test-approval-approved"}}

    graph.invoke({"customer_message": REFUND_MESSAGE}, config=config)
    result = graph.invoke(Command(resume="approve"), config=config)

    assert "__interrupt__" not in result
    assert result["approval_decision"] == "approved"
    assert result["pending_approval"] is None
    assert "approval granted" in result["final_response"].lower()


@requires_openai_key
def test_approval_gate_resumes_when_denied():
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test-approval-denied"}}

    graph.invoke({"customer_message": REFUND_MESSAGE}, config=config)
    result = graph.invoke(Command(resume="deny"), config=config)

    assert "__interrupt__" not in result
    assert result["approval_decision"] == "denied"
    assert result["pending_approval"] is None
    assert "supervisor will follow up" in result["final_response"].lower()
