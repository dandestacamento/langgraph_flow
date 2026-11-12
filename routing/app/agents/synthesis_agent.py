"""Synthesis Agent: combines per-topic agent responses into one final
answer.

For Level 1 (always exactly one selected topic) this is a pass-through -
there's nothing to synthesize. It becomes meaningful starting at Level 7
(multi-topic parallel routing), where it needs to merge potentially
conflicting or complementary answers from more than one topic agent into
a single coherent response.
"""

from __future__ import annotations

from app.state import RoutingState


def synthesize(state: RoutingState) -> dict:
    responses = state["agent_responses"]
    topics = state["selected_topics"]

    if len(topics) == 1:
        final_answer = responses.get(topics[0], "")
    else:
        # Multi-topic synthesis (concatenation placeholder) - a real
        # cross-topic merge/validation step belongs here once Level 7
        # test scenarios exist to drive its design.
        final_answer = "\n\n".join(
            f"[{topic}]\n{responses[topic]}" for topic in topics if topic in responses
        )

    return {
        "final_answer": final_answer,
        "execution_log": [
            {
                "node": "synthesis_agent",
                "action": "synthesize",
                "output": {"topics_merged": topics},
                "duration_ms": 0.0,
            }
        ],
    }
