"""Subtopic Router: stage 2b of the routing architecture (Level 2 -
subtopic routing). Not yet wired into `app/graph.py` - Level 1 only tests
topic-level routing accuracy.

Will take the topic(s) selected by `topic_router.classify_topic` and
narrow each one down to a specific subtopic (e.g. appliances ->
washing_machines) using the subtopic lists in `app.config.TOPIC_SUBTOPICS`,
before chapter-level routing (Level 3) and RAG retrieval (Level 4) are
added on top.
"""

from __future__ import annotations

from app.state import RoutingState


def classify_subtopic(state: RoutingState) -> dict:
    raise NotImplementedError(
        "Subtopic routing is implemented starting at Level 2 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md). "
        "Level 1 only exercises topic_router.classify_topic."
    )
