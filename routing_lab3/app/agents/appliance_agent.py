"""Appliances topic agent (refrigerators, washing machines, dishwashers)."""

from __future__ import annotations

from app.agents._shared import run_topic_agent
from app.state import RoutingState


def run(state: RoutingState) -> dict:
    return run_topic_agent("appliances", state)
