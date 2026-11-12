"""End-to-end workflow tests, plus fast unit tests for the Product Agent's
underlying search tool.

The `test_*_workflow` / `test_*_agent` integration tests invoke the full
LangGraph workflow (router + Product/Technical/Warranty/Orders agents) and
require OPENAI_API_KEY since they call the real LLMs. The `test_search_
products_*` tests exercise `tools.product_tools.search_products` directly
and need no API key - they're regression tests for bugs found during manual
dashboard testing (exact catalog ids, and brand/model keyword matching with
punctuation or short brand names like "LG").
"""

from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from graph.workflow import build_graph
from tools.product_tools import search_products

requires_openai_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"
)


def test_search_products_finds_exact_catalog_id():
    results = search_products("do you have FRIDGE-001")
    assert [p["product_id"] for p in results] == ["FRIDGE-001"]


def test_search_products_matches_model_despite_punctuation():
    # Regression test: a trailing "?" used to stop "GSL360?" from matching
    # the catalog's "GSL360" token, and the 2-letter brand "LG" used to be
    # filtered out by a `len(word) > 2` heuristic.
    results = search_products("Do you sell LG GSL360?")
    assert [p["product_id"] for p in results] == ["FRIDGE-002"]


def test_search_products_matches_dishwasher_not_washing_machine():
    # Regression test: "washer" is a substring of "dishwasher", which used
    # to misclassify dishwasher queries as washing-machine queries.
    results = search_products("Do you have a Bosch Series 6 dishwasher in stock?")
    assert {p["product_id"] for p in results} == {"DISH-001", "DISH-002"}


@requires_openai_key
def test_product_inquiry_produces_response():
    graph = build_graph()
    result = graph.invoke({"customer_message": "Do you have a Bosch Series 6 dishwasher in stock?"})
    assert result["final_response"]
    assert "product" in result["agent_responses"]


@requires_openai_key
def test_warranty_inquiry_uses_warranty_agent():
    graph = build_graph()
    result = graph.invoke({"customer_message": "Is my refrigerator still under warranty? Order ORD-1045."})
    assert "warranty" in result["agent_responses"]


@requires_openai_key
def test_orders_inquiry_uses_orders_agent():
    graph = build_graph()
    result = graph.invoke({"customer_message": "Where is my order ORD-1098? It was supposed to arrive yesterday."})
    assert "orders" in result["agent_responses"]


@requires_openai_key
def test_execution_log_records_router_and_agent_nodes():
    graph = build_graph()
    result = graph.invoke({"customer_message": "My dryer won't start."})
    node_names = {entry["node"] for entry in result["execution_log"]}
    assert "router" in node_names
    assert "aggregator" in node_names


@requires_openai_key
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


@requires_openai_key
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
