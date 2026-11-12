"""Routing tests.

`test_route_to_agents_*` are pure unit tests of the conditional-edge logic
(no LLM calls). `test_router_classifies_*` call the real router (requires
OPENAI_API_KEY) and are based on the scenarios in
instructions/SmartHome_Appliances/4_interacative_routing.md.
"""

from __future__ import annotations

import os

import pytest

from graph.router import classify_intent
from graph.routing_rules import route_to_agents

requires_openai_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"
)


def _state(selected_agents: list[str]) -> dict:
    return {"selected_agents": selected_agents}


def test_route_to_agents_single_implemented_agent():
    assert route_to_agents(_state(["product"])) == ["product"]


def test_route_to_agents_filters_unimplemented_agents():
    # `returns` isn't wired into the graph until Phase 3 (needs the human
    # approval gate), so it should be filtered out of the routing decision.
    assert route_to_agents(_state(["warranty", "returns"])) == ["warranty"]


def test_route_to_agents_multiple_agents_preserved():
    result = route_to_agents(_state(["technical", "warranty"]))
    assert set(result) == {"technical", "warranty"}


def test_route_to_agents_falls_back_to_product_when_empty():
    assert route_to_agents(_state([])) == ["product"]


@requires_openai_key
@pytest.mark.parametrize(
    "message,expected_agents",
    [
        ("Do you have a Bosch Series 6 dishwasher in stock?", {"product"}),
        ("My washing machine makes a loud banging noise during spinning.", {"technical"}),
        (
            "My fridge stopped cooling. It's still under warranty. Can I get a replacement?",
            {"technical", "warranty"},
        ),
        ("Where is order ORD-1045? It was supposed to arrive yesterday.", {"orders"}),
        ("I want a refund for my faulty dishwasher.", {"returns"}),
        (
            "Find a fridge under $1,500 with at least 400L capacity and delivery included.",
            {"product"},
        ),
    ],
)
def test_router_classifies_expected_agents(message: str, expected_agents: set[str]):
    state = {"customer_message": message}
    result = classify_intent(state)
    intents = set(result["router_decision"]["intents"])
    assert expected_agents & intents, f"Expected overlap with {expected_agents}, got {intents}"
