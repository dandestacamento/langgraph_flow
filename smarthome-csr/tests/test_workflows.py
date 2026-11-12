"""End-to-end workflow tests.

These invoke the full Phase 1 graph (router + Product/Technical/Warranty
agents) and require OPENAI_API_KEY since they call the real LLMs.
"""

from __future__ import annotations

import os

import pytest

from graph.workflow import build_graph

pytestmark = pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


def _initial_state(message: str) -> dict:
    return {
        "customer_message": message,
        "order_id": None,
        "router_decision": None,
        "selected_agents": [],
        "agent_responses": {},
        "final_response": "",
        "execution_log": [],
    }


def test_product_inquiry_produces_response():
    graph = build_graph()
    result = graph.invoke(_initial_state("Do you have a Bosch Series 6 dishwasher in stock?"))
    assert result["final_response"]
    assert "product" in result["agent_responses"]


def test_warranty_inquiry_uses_warranty_agent():
    graph = build_graph()
    result = graph.invoke(_initial_state("Is my refrigerator still under warranty? Order ORD-1045."))
    assert "warranty" in result["agent_responses"]


def test_execution_log_records_router_and_agent_nodes():
    graph = build_graph()
    result = graph.invoke(_initial_state("My dryer won't start."))
    node_names = {entry["node"] for entry in result["execution_log"]}
    assert "router" in node_names
    assert "aggregator" in node_names
