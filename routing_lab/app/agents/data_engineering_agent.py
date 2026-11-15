"""Data Engineering topic agent (Spark, Databricks, Azure Data Factory)."""

from __future__ import annotations

from app.agents._shared import run_topic_agent
from app.state import RoutingState


def run(state: RoutingState) -> dict:
    return run_topic_agent("data_engineering", state)
