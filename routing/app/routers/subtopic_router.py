"""Subtopic Router: stage 2b of the hybrid routing architecture (Level 2 -
subtopic routing). Takes the topic(s) selected by
`topic_router.classify_topic` and narrows each one down to a specific
subtopic (e.g. appliances -> washing_machines) using the subtopic lists in
`app.config.TOPIC_SUBTOPICS`.

One structured-output LLM call is made per selected topic, each
constrained (via a dynamically built Pydantic model) to that topic's own
subtopic list - this keeps the output space small and unambiguous instead
of asking the model to pick from all ~19 subtopics across every topic at
once. Level 1-6 only ever select a single topic, so this is one LLM call
per question; Level 7 (multi-topic) will make one call per selected
topic, run in sequence here since each is cheap and independent.
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI
from pydantic import Field, create_model

from app.config import ROUTER_MODEL, SUBTOPIC_DESCRIPTIONS, TOPIC_SUBTOPICS
from app.state import RoutingState


def _subtopic_system_prompt(topic: str) -> str:
    lines = [
        f"You are the Subtopic Router for the '{topic}' topic in a routing accuracy test lab. "
        "The question has already been classified into this topic - classify it into exactly one "
        "of these subtopics:",
        "",
    ]
    for subtopic in TOPIC_SUBTOPICS[topic]:
        description = SUBTOPIC_DESCRIPTIONS.get((topic, subtopic), "")
        lines.append(f"- {subtopic}: {description}")
    lines.append("")
    lines.append("Pick the single subtopic that best matches the specific thing being asked about.")
    return "\n".join(lines)


def _build_subtopic_output_model(topic: str):
    """Build a one-off Pydantic model whose `subtopic` field is restricted
    (via an enum constraint) to this topic's own subtopics, so structured
    output can't select a subtopic that belongs to a different topic."""
    subtopics = list(TOPIC_SUBTOPICS[topic])
    return create_model(
        f"SubtopicOutput_{topic}",
        subtopic=(str, Field(description="The selected subtopic.", json_schema_extra={"enum": subtopics})),
        confidence=(float, Field(ge=0.0, le=1.0, description="Confidence in this classification, 0-1.")),
        reasoning=(str, Field(description="One sentence explaining the classification.")),
    )


def classify_subtopic(state: RoutingState) -> dict:
    """Router node: classify each selected topic's question into one of
    that topic's subtopics."""
    subtopic_decisions: dict = {}
    selected_subtopics: dict = {}
    log_entries: list[dict] = []

    for topic in state["selected_topics"]:
        start = time.perf_counter()
        model = _build_subtopic_output_model(topic)
        llm = ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(model)
        result = llm.invoke(
            [
                ("system", _subtopic_system_prompt(topic)),
                ("human", state["question"]),
            ]
        )
        duration_ms = (time.perf_counter() - start) * 1000

        subtopic = result.subtopic if result.subtopic in TOPIC_SUBTOPICS[topic] else TOPIC_SUBTOPICS[topic][0]
        decision = {
            "subtopic": subtopic,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }
        subtopic_decisions[topic] = decision
        selected_subtopics[topic] = subtopic
        log_entries.append(
            {
                "node": "subtopic_router",
                "action": f"classify_subtopic[{topic}]",
                "output": decision,
                "duration_ms": round(duration_ms, 1),
            }
        )

    return {
        "subtopic_decisions": subtopic_decisions,
        "selected_subtopics": selected_subtopics,
        "execution_log": log_entries,
    }
