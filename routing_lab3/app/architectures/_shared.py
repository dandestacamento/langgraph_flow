"""Shared helper for Architectures A and B: both use the exact same
single-topic-only classifier (one LLM call, no subtopic/chapter
awareness, no multi-topic planning, no ambiguity detection) - the only
difference between them is what happens *after* topic classification (A
answers directly; B adds subtopic and chapter narrowing first). Sharing
this one classifier isolates that as the variable under test, and
guarantees both architectures get the exact same topic decision for a
given question (rather than two independently-worded prompts that might
happen to classify differently for unrelated reasons) - as a side
benefit, since the prompt is byte-identical, whichever architecture runs
second for a given question hits the LLM response cache for this stage
(see `app/cache.py`).
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import ROUTER_MODEL, TOPICS
from app.routers.topic_router import TopicLiteral, _TOPIC_DESCRIPTIONS
from app.state import RoutingState


def _simple_topic_system_prompt() -> str:
    lines = [
        "You are a simple topic router. Classify the user's question into exactly ONE of these "
        "six topics - pick whichever single topic is the best overall match:",
        "",
    ]
    for topic in TOPICS:
        lines.append(f"- {topic}: {_TOPIC_DESCRIPTIONS[topic]}")
    return "\n".join(lines)


SIMPLE_TOPIC_SYSTEM_PROMPT = _simple_topic_system_prompt()


class TopicOnlyOutput(BaseModel):
    """Structured output the LLM must produce - a single topic, with none
    of `app.routers.topic_router.TopicOutput`'s subtopic/chapter/
    ambiguity/multi-topic fields."""

    topic: TopicLiteral = Field(description="The single best-matching topic.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this classification, 0-1.")
    reasoning: str = Field(description="One sentence explaining the classification.")


def classify_topic_only(node_name: str):
    """Build a LangGraph node function for the simple single-topic
    classifier, labeled with `node_name` in the execution log (so
    Architecture A's and B's traces are distinguishable even though they
    share this exact logic)."""

    def _node(state: RoutingState) -> dict:
        start = time.perf_counter()
        llm = ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(TopicOnlyOutput)
        result: TopicOnlyOutput = llm.invoke(
            [
                ("system", SIMPLE_TOPIC_SYSTEM_PROMPT),
                ("human", state["question"]),
            ]
        )
        duration_ms = (time.perf_counter() - start) * 1000

        return {
            "selected_topics": [result.topic],
            "execution_log": [
                {
                    "node": node_name,
                    "action": "classify_topic_only",
                    "output": {
                        "topic": result.topic,
                        "confidence": result.confidence,
                        "reasoning": result.reasoning,
                    },
                    "duration_ms": round(duration_ms, 1),
                }
            ],
        }

    return _node
