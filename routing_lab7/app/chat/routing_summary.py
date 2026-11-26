"""Trims `app.state.RoutingState`'s rich per-turn output (kept in full in
`ChatState.routing_result`, per `state.py`'s docstring) into a smaller,
frontend-friendly shape for generative UI - see
instructions/learnings/routing-lab6-chat-app-plan.md section 6's Phase 2.

Deliberately excludes `execution_log` (an internal evaluation/debugging
trace, not meant for end users) and the raw `*_decisions` dicts'
`confidence`/`reasoning` fields (useful for routing-accuracy debugging,
not for a chat user); keeps everything else a chat UI plausibly wants to
render: the topic/subtopic/chapter routing trail, retrieved passages
(citations), any tool that ran, and the multi-hop trace when present.
"""

from __future__ import annotations


def build_routing_summary(routing_result: dict) -> dict:
    passages_by_topic = routing_result.get("retrieved_passages", {})
    return {
        "topics": routing_result.get("selected_topics", []),
        "subtopics": routing_result.get("selected_subtopics", {}),
        "chapters": routing_result.get("selected_chapters", {}),
        "passages": {
            topic: [
                {
                    "chapter_id": passage.get("chapter_id"),
                    "document_id": passage.get("document_id"),
                    "source": passage.get("source"),
                    "version": passage.get("version"),
                    "page": passage.get("page"),
                    "subtopic": passage.get("subtopic"),
                    "score": passage.get("score"),
                    "text": passage.get("text"),
                }
                for passage in passages
            ]
            for topic, passages in passages_by_topic.items()
        },
        "tool_results": routing_result.get("tool_results", {}),
        "is_multi_hop": routing_result.get("is_multi_hop", False),
        "hop_results": routing_result.get("hop_results", []),
        "recovery_attempts": routing_result.get("recovery_attempts", {}),
    }
