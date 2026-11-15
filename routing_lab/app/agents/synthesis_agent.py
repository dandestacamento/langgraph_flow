"""Synthesis Agent: combines per-topic agent responses into one final
answer.

For a single selected topic (Levels 1-6) this is a free pass-through -
there's nothing to synthesize, so no extra LLM call is made. Starting at
Level 7 (multi-topic parallel routing), a genuinely multi-topic question
has more than one topic agent's response to merge into a single coherent
answer; this uses one extra LLM call (only when len(topics) > 1, so
single-topic questions are unaffected in cost or behavior) to combine the
already-grounded, already-cited per-topic answers without re-retrieving
or re-verifying evidence - each topic agent's answer is itself already
grounded in its own retrieved passages (Level 4), so synthesis only needs
to merge and organize, not re-ground.
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from app.config import AGENT_MODEL
from app.state import RoutingState

_SYNTHESIS_SYSTEM_PROMPT = (
    "You are the Synthesis Agent. You are given one answer per topic from separate specialist "
    "agents, each already grounded in their own retrieved knowledge base excerpts and already "
    "carrying its own 'Sources: chapter_id, chapter_id, ...' line at the end. Combine them into "
    "ONE clear, well-organized answer to the original question. Preserve every fact and every "
    "cited chapter_id from every topic's answer - do not drop or alter any of them. Do not add "
    "any new information beyond what the topic answers already say. Each topic's answer below is "
    "introduced by a '--- TOPIC: <name> ---' header - this header is NOT a citation and must "
    "never appear in your own Sources line; only copy the real chapter_id values that already "
    "appear after each topic answer's own 'Sources:' line. End your answer with a single merged "
    "'Sources: ' line listing every one of those chapter_ids, without duplicates."
)


def _format_topic_answers(responses: dict[str, str], topics: list[str]) -> str:
    return "\n\n".join(f"--- TOPIC: {topic} ---\n{responses[topic]}" for topic in topics if topic in responses)


def synthesize(state: RoutingState) -> dict:
    responses = state["agent_responses"]
    topics = state["selected_topics"]

    if len(topics) <= 1:
        final_answer = responses.get(topics[0], "") if topics else ""
        duration_ms = 0.0
    else:
        start = time.perf_counter()
        llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
        human_message = (
            f"Original question: {state['question']}\n\n"
            f"Per-topic answers to combine:\n{_format_topic_answers(responses, topics)}"
        )
        response = llm.invoke(
            [
                ("system", _SYNTHESIS_SYSTEM_PROMPT),
                ("human", human_message),
            ]
        )
        final_answer = response.content.strip()
        duration_ms = (time.perf_counter() - start) * 1000

    return {
        "final_answer": final_answer,
        "execution_log": [
            {
                "node": "synthesis_agent",
                "action": "synthesize",
                "output": {"topics_merged": topics},
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }

