"""End-to-end workflow tests.

These invoke the full LangGraph workflow (router + Product/Technical/
Warranty/Orders agents) and require OPENAI_API_KEY since they call the real
LLMs. Most tests use a single stateless call; the conversation-memory tests
use an InMemorySaver checkpointer with a shared thread_id to exercise
Phase 2's cross-turn behaviour (sticky order_id, troubleshooting escalation).
"""

from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from graph.workflow import build_graph

pytestmark = pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


def test_product_inquiry_produces_response():
    graph = build_graph()
    result = graph.invoke({"customer_message": "Do you have a Bosch Series 6 dishwasher in stock?"})
    assert result["final_response"]
    assert "product" in result["agent_responses"]


def test_warranty_inquiry_uses_warranty_agent():
    graph = build_graph()
    result = graph.invoke({"customer_message": "Is my refrigerator still under warranty? Order ORD-1045."})
    assert "warranty" in result["agent_responses"]


def test_orders_inquiry_uses_orders_agent():
    graph = build_graph()
    result = graph.invoke({"customer_message": "Where is my order ORD-1098? It was supposed to arrive yesterday."})
    assert "orders" in result["agent_responses"]


def test_execution_log_records_router_and_agent_nodes():
    graph = build_graph()
    result = graph.invoke({"customer_message": "My dryer won't start."})
    node_names = {entry["node"] for entry in result["execution_log"]}
    assert "router" in node_names
    assert "aggregator" in node_names


def test_conversation_memory_retains_order_id_across_turns():
    """Use case 8: 'I already gave you my order number.' The order id
    mentioned on turn 1 should still resolve the warranty lookup on turn 2,
    even though turn 2's message doesn't repeat it."""
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test-memory-thread"}}

    first = graph.invoke(
        {"customer_message": "My order is ORD-1045, is it still under warranty?"}, config=config
    )
    assert first["order_id"] == "ORD-1045"

    second = graph.invoke({"customer_message": "Can you check that again please?"}, config=config)
    assert second["order_id"] == "ORD-1045"
    assert "warranty" in second["agent_responses"] or "warranty" in second["final_response"].lower()


def test_technical_agent_escalates_on_repeat_visit():
    """Use case 3: troubleshooting loop. The second visit about the same
    fault within a conversation should escalate rather than repeat advice."""
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test-escalation-thread"}}

    first = graph.invoke(
        {"customer_message": "My washing machine makes a loud banging noise during spinning."},
        config=config,
    )
    first_log = [e for e in first["execution_log"] if e["node"] == "technical_agent"][-1]
    assert first_log["action"] == "diagnose_fault"

    second = graph.invoke(
        {"customer_message": "I tried that already and it's still banging. What now?"}, config=config
    )
    second_log = [e for e in second["execution_log"] if e["node"] == "technical_agent"][-1]
    assert second_log["action"] == "escalate_fault"
    assert second_log["prior_visits"] >= 1
