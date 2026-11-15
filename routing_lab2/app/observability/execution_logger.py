"""Execution log helpers shared by routers, agents, and the evaluation
harness.

Every router/agent node appends its own entry to `RoutingState.execution_log`
directly, using the `{"node", "action", "output", "duration_ms"}` shape
documented in `app/state.py`. This module centralizes reading that trace
back out for the dashboard and for `app/evaluation`, so the log entry
shape only needs to be agreed on in one place.
"""

from __future__ import annotations

from typing import Any


def get_node_sequence(execution_log: list[dict]) -> list[str]:
    """The ordered list of node names that actually executed in a run -
    the "actual route" to compare against a ground-truth expected route."""
    return [entry["node"] for entry in execution_log]


def get_log_for_node(execution_log: list[dict], node: str) -> dict[str, Any] | None:
    """The most recent log entry for a given node name, or None if that
    node did not run."""
    for entry in reversed(execution_log):
        if entry["node"] == node:
            return entry
    return None


def total_duration_ms(execution_log: list[dict]) -> float:
    return sum(entry.get("duration_ms", 0.0) for entry in execution_log)
