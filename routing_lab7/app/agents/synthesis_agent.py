"""Synthesis Agent: combines per-topic agent responses into one final
answer.

For a single selected topic (Levels 1-6) this is a free pass-through -
there's nothing to synthesize, so no extra LLM call is made. Starting at
Level 7 (multi-topic parallel routing), a genuinely multi-topic question
has more than one topic agent's response to merge into a single coherent
answer. The merged answer is checked against the retrieved evidence; if
the check fails, the individual topic responses are returned instead.
"""

from __future__ import annotations

import json
import time

from langchain_openai import ChatOpenAI

from app import llm_gateway
from app.agents._shared import INSUFFICIENT_INFO_MARKER, UNVERIFIED_ANSWER_MARKER, _answer_is_supported
from app.config import AGENT_MODEL
from app.state import RoutingState

_SYNTHESIS_SYSTEM_PROMPT = (
    "You are the Synthesis Agent. You are given one answer per topic from separate specialist "
    "agents, each already grounded in their own retrieved knowledge base excerpts (and, for some "
    "topics, a tool result) and already carrying its own 'Sources: ' line listing chapter IDs, "
    "document names with page details, "
    "and/or a 'tool:<name>' entry. Combine them into ONE clear, well-organized answer to the "
    "original question. Preserve every fact and every cited source from every topic's answer - "
    "do not drop or alter any of them, including document names, page details, and 'tool:<name>' entries. Do "
    "not add any new information beyond what the topic answers already say. "
    "Preserve conditions and uncertainty; do not turn conditional eligibility or coverage "
    "into a likely or confirmed outcome. "
    "If a topic reports insufficient information or an unverified answer, preserve that limitation; "
    "do not fill its gaps or imply that part was answered. "
    "Each topic's answer below is introduced by a '--- TOPIC: <name> ---' header - this header is "
    "NOT a citation and must never appear in your own Sources line; only copy the real "
    "source entries that already appear after each topic answer's own 'Sources:' line. "
    "End your answer with a single merged 'Sources: ' line listing every one of those values, "
    "without duplicates."
)


def _format_topic_answers(responses: dict[str, str], topics: list[str]) -> str:
    return "\n\n".join(f"--- TOPIC: {topic} ---\n{responses[topic]}" for topic in topics if topic in responses)


def synthesize(state: RoutingState) -> dict:
    responses = state["agent_responses"]
    topics = state["selected_topics"]
    verification_fallback = False

    if len(topics) <= 1:
        final_answer = responses.get(topics[0], "") if topics else ""
        duration_ms = 0.0
    elif any(
        marker in responses.get(topic, "")
        for topic in topics
        for marker in (INSUFFICIENT_INFO_MARKER, UNVERIFIED_ANSWER_MARKER)
    ):
        final_answer = _format_topic_answers(responses, topics)
        duration_ms = 0.0
    else:
        start = time.perf_counter()
        llm = ChatOpenAI(model=AGENT_MODEL, temperature=0, **llm_gateway.llm_kwargs())
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
        evidence = [
            passage
            for topic in topics
            for passage in state.get("retrieved_passages", {}).get(topic, [])
        ]
        evidence.extend(
            {"text": json.dumps({"topic": topic, "tool_result": tool_result})}
            for topic in topics
            if (tool_result := state.get("tool_results", {}).get(topic))
            and tool_result.get("error") is None
        )
        if not _answer_is_supported(state["question"], final_answer, evidence, None):
            final_answer = _format_topic_answers(responses, topics)
            verification_fallback = True
        duration_ms = (time.perf_counter() - start) * 1000

    return {
        "final_answer": final_answer,
        "execution_log": [
            {
                "node": "synthesis_agent",
                "action": "synthesize",
                "output": {"topics_merged": topics, "verification_fallback": verification_fallback},
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }

